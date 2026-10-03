import re
import sqlite3
from datetime import datetime
from uuid import uuid4
from fastapi import HTTPException
from app.db import connect, event, now
from app.provider import Provider
from app.tools import IST, customer, record_outcome


def skip_reason(c, settings, override_hours=False, current=None):
    if c['dnc']:
        return 'do_not_contact'
    if c['status']=='RECOVERED':
        return 'already_recovered'
    if c['attempt_count']>=3:
        return 'attempt_cap_reached'
    if not re.fullmatch(r'\+[1-9]\d{7,14}',c['phone']) or c['phone'] not in settings.allowed_numbers:
        return 'number_not_allowlisted'
    current=current or datetime.now(IST)
    if not override_hours and not 9<=current.astimezone(IST).hour<19:
        return 'outside_calling_hours'
    return None


def start(settings, cid, simulation=False, override_hours=False):
    call_id='CALL-'+uuid4().hex
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        c=customer(db,cid)
        if simulation:
            reason='do_not_contact' if c['dnc'] else ('already_recovered' if c['status']=='RECOVERED' else ('attempt_cap_reached' if c['attempt_count']>=3 else None))
        else:
            reason=skip_reason(c,settings,override_hours)
        if reason:
            raise HTTPException(409,reason)
        try:
            db.execute('INSERT INTO calls(id,customer_id,state,created_at,mode) VALUES(?,?,?,?,?)',
                       (call_id,cid,'active' if simulation else 'placing',now(),'mock' if simulation else settings.provider))
        except sqlite3.IntegrityError:
            raise HTTPException(409,'another_call_is_active')
        db.execute('UPDATE customers SET last_call_id=?,verified=0,verify_attempts=0,retries_this_call=0,updated_at=? WHERE customer_id=?',(call_id,now(),cid))
        variables={'customer_id':cid,'first_name':c['name'].split()[0],'company':'Razorpay','language':c['language'],'current_date':datetime.now(IST).date().isoformat()}
        phone=c['phone']
        if simulation:
            db.execute('UPDATE customers SET attempt_count=attempt_count+1 WHERE customer_id=?',(cid,))
            db.execute('UPDATE calls SET provider_id=? WHERE id=?',('mock-'+call_id,call_id))
            event(db,cid,call_id,'call_started',{'mode':'mock','network_call':False})
            return {'call_id':call_id,'mode':'mock','variables':variables}
    try:
        provider_id=Provider(settings).start_call(cid,phone,variables)
    except Exception as exc:
        # An ambiguous timeout may have placed a call. Block the global dialer until an operator reconciles it.
        with connect(settings) as db:
            db.execute("UPDATE calls SET state='uncertain' WHERE id=?",(call_id,))
            db.execute('UPDATE customers SET attempt_count=attempt_count+1 WHERE customer_id=?',(cid,))
            event(db,cid,call_id,'provider_error',{'error_type':type(exc).__name__,'action':'reconcile_in_provider_dashboard'})
        raise HTTPException(502,'provider_result_uncertain_reconcile_before_retry')
    with connect(settings) as db:
        db.execute("UPDATE calls SET provider_id=?,state='active' WHERE id=?",(provider_id,call_id))
        db.execute('UPDATE customers SET attempt_count=attempt_count+1 WHERE customer_id=?',(cid,))
        event(db,cid,call_id,'call_started',{'mode':settings.provider,'override_hours':override_hours})
    return {'call_id':call_id,'provider_id':provider_id,'mode':settings.provider}


def finish(settings, call_id, info=None):
    info=info or {}
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        call=db.execute('SELECT * FROM calls WHERE id=?',(call_id,)).fetchone()
        if not call:
            raise HTTPException(404,'call_not_found')
        if call['state']=='ended':
            return {'received':True,'duplicate':True}
        outcome=record_outcome(db,call['customer_id'],call_id,call['outcome'] or info.get('outcome','DROPPED'))
        db.execute("UPDATE calls SET state='ended',ended_at=?,duration=?,cost=?,transcript_url=?,recording_url=? WHERE id=?",
                   (now(),info.get('duration',0),info.get('cost',0),info.get('transcript_url'),info.get('recording_url'),call_id))
        db.execute('UPDATE customers SET verified=0 WHERE customer_id=? AND last_call_id=?',(call['customer_id'],call_id))
        event(db,call['customer_id'],call_id,'call_ended',{'outcome':outcome})
        return {'received':True,'outcome':outcome}
