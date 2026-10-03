import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
import httpx
from fastapi import HTTPException
from app.db import connect, event, now
from app.tools import IST, record_outcome, today


def recover(db, link):
    db.execute("UPDATE links SET state='paid' WHERE token=?",(link['token'],))
    db.execute("UPDATE customers SET status='RECOVERED',updated_at=? WHERE customer_id=?",(now(),link['customer_id']))
    db.execute("UPDATE schedules SET state='cancelled' WHERE customer_id=? AND state='pending'",(link['customer_id'],))
    record_outcome(db,link['customer_id'],link['call_id'],'RECOVERED')
    event(db,link['customer_id'],link['call_id'],'payment_confirmed',{'mode':'razorpay_test' if link['provider_id'] else 'mock'})


def complete_mock(settings,token):
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        link=db.execute('SELECT * FROM links WHERE token=?',(token,)).fetchone()
        if not link:
            raise HTTPException(404,'link_not_found')
        if link['provider_id'] or link['state'] not in ('ready','paid'):
            raise HTTPException(409,'not_a_mock_link')
        if datetime.fromisoformat(link['expires_at'])<datetime.now(IST):
            raise HTTPException(410,'link_expired')
        if link['state']!='paid':
            recover(db,link)
        return {'status':'RECOVERED','mode':'mock','message':'Demo complete. No money was charged.'}


def payment_webhook(settings,raw,signature):
    if not settings.razorpay_webhook_secret:
        raise HTTPException(503,'test_payments_not_configured')
    expected=hmac.new(settings.razorpay_webhook_secret.encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,expected):
        raise HTTPException(401,'invalid_signature')
    try:
        body=json.loads(raw)
        if body.get('event')!='payment_link.paid':
            return {'ignored':True}
        entity=body['payload']['payment_link']['entity']
        ref=entity['id']
    except (ValueError,KeyError,TypeError):
        raise HTTPException(422,'invalid_payment_event')
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        link=db.execute('SELECT * FROM links WHERE provider_id=?',(ref,)).fetchone()
        if not link:
            raise HTTPException(404,'unknown_payment_link')
        if entity.get('status')!='paid' or entity.get('currency')!='INR' or entity.get('amount_paid')!=link['amount_paise'] or entity.get('amount')!=link['amount_paise']:
            raise HTTPException(409,'payment_amount_or_status_mismatch')
        if link['state']!='paid':
            recover(db,link)
    return {'received':True}


def tick(settings):
    """Durable jobs. One process owns the worker. External timeouts are never blindly retried."""
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        link=db.execute("SELECT * FROM links WHERE state='pending' LIMIT 1").fetchone()
        if link:
            db.execute("UPDATE links SET state='creating' WHERE token=?",(link['token'],))
    if link:
        try:
            with httpx.Client(timeout=10) as client:
                response=client.post('https://api.razorpay.com/v1/payment_links',
                    auth=(settings.razorpay_key_id,settings.razorpay_key_secret),json={
                        'amount':link['amount_paise'],'currency':'INR','accept_partial':False,
                        'reference_id':link['customer_id']+'-'+link['token'][:16],
                        'description':'Fictional autopay recovery demo',
                        'notify':{'sms':False,'email':False},'reminder_enable':False,
                        'expire_by':int(datetime.fromisoformat(link['expires_at']).timestamp())})
                response.raise_for_status()
                data=response.json()
                if not data['short_url'].startswith('https://'):
                    raise ValueError('Invalid provider link')
            with connect(settings) as db:
                db.execute("UPDATE links SET state='ready',url=?,provider_id=? WHERE token=?",(data['short_url'],data['id'],link['token']))
                event(db,link['customer_id'],link['call_id'],'sms_demo_outbox',{'delivery':'logged_only','mode':'razorpay_test'})
                record_outcome(db,link['customer_id'],link['call_id'],'LINK_SENT')
        except Exception as exc:
            with connect(settings) as db:
                db.execute("UPDATE links SET state='needs_review' WHERE token=?",(link['token'],))
                event(db,link['customer_id'],link['call_id'],'link_creation_uncertain',{'error_type':type(exc).__name__})
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        for job in db.execute("SELECT s.*,c.dnc,c.status,c.retry_result FROM schedules s JOIN customers c USING(customer_id) WHERE s.state='pending' AND s.due_date<=?",(today().isoformat(),)).fetchall():
            state='cancelled' if job['dnc'] or job['status']=='RECOVERED' else ('succeeded' if job['retry_result']=='success' else 'failed')
            db.execute('UPDATE schedules SET state=? WHERE id=?',(state,job['id']))
            if state=='succeeded':
                db.execute("UPDATE customers SET status='RECOVERED',updated_at=? WHERE customer_id=?",(now(),job['customer_id']))
                record_outcome(db,job['customer_id'],job['call_id'],'RECOVERED')
            event(db,job['customer_id'],job['call_id'],'scheduled_mock_retry',{'state':state,'mode':'mock'})
