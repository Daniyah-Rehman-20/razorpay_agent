import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from pydantic import ValidationError
from app.db import connect, event, now
from app.models import MODELS

IST = ZoneInfo('Asia/Kolkata')


def today():
    return datetime.now(IST).date()


def redact(value):
    return re.sub(r'\b\d{4,}\b', '[redacted]', value)


def customer(db, cid):
    row = db.execute('SELECT * FROM customers WHERE customer_id=?', (cid,)).fetchone()
    if not row:
        raise HTTPException(404, 'customer_not_found')
    return row


def record_outcome(db, cid, call_id, outcome, notes=''):
    c = customer(db, cid)
    if c['dnc']:
        outcome = 'DNC'
    elif c['status'] == 'RECOVERED':
        outcome = 'RECOVERED'
    db.execute('UPDATE calls SET outcome=? WHERE id=?', (outcome, call_id))
    db.execute('''INSERT INTO call_log(customer_id,call_id,outcome,notes,created_at) VALUES(?,?,?,?,?)
        ON CONFLICT(call_id) DO UPDATE SET outcome=excluded.outcome,notes=excluded.notes''',
        (cid, call_id, outcome, redact(notes), now()))
    db.execute('UPDATE customers SET last_outcome=?,updated_at=? WHERE customer_id=? AND last_call_id=?',
               (outcome, now(), cid, call_id))
    return outcome


def _execute(settings, name, data, call_id, request_id):
    if name not in MODELS:
        raise HTTPException(404, 'unknown_tool')
    try:
        payload = MODELS[name].model_validate(data).model_dump(mode='json')
    except ValidationError:
        raise HTTPException(422, 'invalid_tool_arguments')
    if not call_id or not request_id or len(request_id) > 160:
        raise HTTPException(400, 'call_id_and_idempotency_key_required')
    # HMAC avoids retaining a reversible or brute-forceable hash of birth years.
    fingerprint = hmac.new(settings.webhook_secret.encode(), json.dumps([name,payload],sort_keys=True).encode(), hashlib.sha256).hexdigest()
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        c = customer(db, payload['customer_id'])
        call = db.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
        if not call or call['customer_id'] != c['customer_id']:
            raise HTTPException(403, 'call_customer_mismatch')
        cached = db.execute('SELECT * FROM idempotency WHERE call_id=? AND request_id=?', (call_id, request_id)).fetchone()
        if cached:
            if cached['fingerprint'] != fingerprint:
                raise HTTPException(409, 'idempotency_key_reused')
            return json.loads(cached['result'])
        if call['state'] != 'active':
            raise HTTPException(409, 'call_not_active')
        cid = c['customer_id']
        result = run_tool(db, settings, name, payload, c, call)
        # Never persist the verification answer, raw arguments or raw provider transcript.
        event(db, cid, call_id, name, {'result': {k:v for k,v in result.items() if k not in {'url'}}})
        db.execute('INSERT INTO idempotency VALUES(?,?,?,?)', (call_id,request_id,fingerprint,json.dumps(result)))
        return result


def run_tool(db, settings, name, p, c, call):
    cid, call_id = c['customer_id'], call['id']
    if name == 'mark_dnc':
        # The same approved test number can represent several fictional customers.
        if re.fullmatch(r'\+[1-9]\d{7,14}',c['phone']):
            db.execute('UPDATE customers SET dnc=1,updated_at=? WHERE phone=?', (now(), c['phone']))
        else:
            db.execute('UPDATE customers SET dnc=1,updated_at=? WHERE customer_id=?', (now(),cid))
        db.execute("UPDATE schedules SET state='cancelled' WHERE customer_id IN (SELECT customer_id FROM customers WHERE dnc=1)")
        record_outcome(db,cid,call_id,'DNC')
        return {'dnc':True}
    if name == 'log_outcome':
        outcome = p['outcome']
        if outcome == 'RECOVERED' and c['status'] != 'RECOVERED':
            raise HTTPException(409, 'recovery_not_confirmed')
        if outcome == 'DNC' and not c['dnc']:
            raise HTTPException(409, 'dnc_not_recorded')
        if outcome == 'LINK_SENT' and not db.execute("SELECT 1 FROM links WHERE call_id=? AND state IN ('ready','paid')", (call_id,)).fetchone():
            raise HTTPException(409, 'link_not_ready')
        if outcome == 'PROMISE_TO_PAY' and not db.execute('SELECT 1 FROM schedules WHERE call_id=?', (call_id,)).fetchone():
            raise HTTPException(409, 'schedule_not_recorded')
        return {'logged':True, 'outcome':record_outcome(db,cid,call_id,outcome,p['notes'])}
    if c['dnc']:
        raise HTTPException(409, 'do_not_contact')
    if name == 'request_callback':
        ref = 'CB-' + uuid4().hex[:12]
        db.execute('INSERT INTO callbacks VALUES(?,?,?,?,?)', (ref,cid,call_id,redact(p['time_window']),now()))
        return {'requested':True,'callback_id':ref}
    if name == 'escalate_to_human':
        ref = 'TKT-' + uuid4().hex[:12]
        event(db,cid,call_id,'human_ticket',{'ticket_id':ref,'reason':redact(p['reason'])})
        return {'ticket_id':ref,'message':'A team member will call back. The demo records a ticket; no automatic callback is placed.'}
    if name == 'verify_identity':
        if call['verified']:
            return {'verified':True}
        if call['verify_attempts'] >= 2:
            return {'verified':False,'locked':True,'attempts_left':0}
        normalized = lambda s: ' '.join(s.strip().casefold().split())
        valid = hmac.compare_digest(normalized(p['answer']).encode(),normalized(c['verification_answer']).encode())
        count = call['verify_attempts'] + 1
        db.execute('UPDATE calls SET verified=?,verify_attempts=? WHERE id=?', (int(valid),count,call_id))
        db.execute('UPDATE customers SET verified=?,verify_attempts=?,updated_at=? WHERE customer_id=?', (int(valid),count,now(),cid))
        return {'verified':True} if valid else {'verified':False,'attempts_left':max(0,2-count),'locked':count>=2}
    if not call['verified']:
        raise HTTPException(403, 'not_verified')
    if name == 'get_payment_details':
        return {k:c[k] for k in ('plan','amount_due','currency','due_date','failure_reason','payment_method','instrument_last4','attempt_count')}
    if name == 'retry_payment' and call['retries']:
        return {'status':'not_allowed','reason':'retry_already_used'}
    if c['status'] == 'RECOVERED':
        return {'status':'already_recovered'}
    if name == 'retry_payment':
        if call['retries']:
            return {'status':'not_allowed','reason':'retry_already_used'}
        if any(x in c['failure_reason'].lower() for x in ('expired','revoked','paused')):
            return {'status':'not_allowed','reason':'payment_method_update_required'}
        success = c['retry_result']=='success'
        db.execute('UPDATE calls SET retries=1 WHERE id=?',(call_id,))
        db.execute('UPDATE customers SET retries_this_call=1, status=?,updated_at=? WHERE customer_id=?',('RECOVERED' if success else c['status'],now(),cid))
        record_outcome(db,cid,call_id,'RECOVERED' if success else 'RETRY_FAILED')
        return {'status':'success' if success else 'failed','message':'Simulated payment succeeded.' if success else 'Simulated payment failed.','txn_ref':'MOCK-'+uuid4().hex[:12]}
    if name == 'send_payment_link':
        row = db.execute('SELECT * FROM links WHERE call_id=?',(call_id,)).fetchone()
        if not row:
            token = secrets.token_urlsafe(32)
            external = bool(settings.razorpay_key_id)
            url = '' if external else f'{settings.public_base_url}/pay/{token}'
            db.execute('INSERT INTO links VALUES(?,?,?,?,?,?,?,?,?)',(token,cid,call_id,url,'pending' if external else 'ready',
                       (datetime.now(IST)+timedelta(hours=24)).isoformat(),None,int(Decimal(str(c['amount_due']))*100),now()))
            row = db.execute('SELECT * FROM links WHERE token=?',(token,)).fetchone()
            if not external:
                event(db,cid,call_id,'sms_demo_outbox',{'channel':'sms','delivery':'logged_only','link_token_suffix':token[-6:]})
        if row['state']=='ready':
            record_outcome(db,cid,call_id,'LINK_SENT')
        return {'sent':row['state'] in ('ready','paid'),'status':row['state'], 'channel':'sms','delivery':'demo_log_only',
                'link_last_chars':row['url'][-6:], 'message':'Link recorded in the demo outbox; no real SMS was sent.' if row['state']=='ready' else 'Link creation queued. Do not claim it was sent; check again or offer a callback.'}
    if name == 'schedule_retry':
        try:
            due = datetime.strptime(p['date'],'%Y-%m-%d').date()
            if due.isoformat()!=p['date']:
                raise ValueError()
        except ValueError:
            return {'scheduled':False,'reason':'Use ISO yyyy-mm-dd'}
        if not today()+timedelta(days=1)<=due<=today()+timedelta(days=7):
            return {'scheduled':False,'reason':'Choose tomorrow through today plus 7 days'}
        if any(x in c['failure_reason'].lower() for x in ('expired','revoked','paused')):
            return {'scheduled':False,'reason':'payment_method_update_required'}
        db.execute('''INSERT INTO schedules VALUES(?,?,?,?,?,?) ON CONFLICT(call_id)
            DO UPDATE SET due_date=excluded.due_date,state='pending' ''',('SCH-'+uuid4().hex[:12],cid,call_id,due.isoformat(),'pending',now()))
        record_outcome(db,cid,call_id,'PROMISE_TO_PAY')
        return {'scheduled':True,'date':due.isoformat(),'mode':'mock_retry'}
    raise HTTPException(404,'unknown_tool')


def execute(settings, name, data, call_id, request_id):
    try:
        return _execute(settings,name,data,call_id,request_id)
    except HTTPException as exc:
        with connect(settings) as db:
            call=db.execute('SELECT customer_id FROM calls WHERE id=?',(call_id,)).fetchone()
            if call:
                event(db,call['customer_id'],call_id,'tool_rejected',{'tool':name,'reason':exc.detail})
        raise
