import hashlib
import hmac
import json
from datetime import timedelta, datetime
from app.db import connect
from app.tools import IST, today
from app.payments import tick
from tests.test_tools import tool, verify


def test_mock_payment_end_to_end_idempotent(session):
    verify(session)
    assert tool(session,'send_payment_link',{'consent':True}).json()['sent']
    client,s,call=session
    with connect(s) as db:
        link=dict(db.execute('SELECT * FROM links').fetchone())
    assert client.get('/pay/'+link['token']).status_code==200
    assert client.get('/pay/C002').status_code==404
    assert client.post('/pay/'+link['token']).json()['status']=='RECOVERED'
    assert client.post('/pay/'+link['token']).status_code==200
    assert tool(session,'log_outcome',{'outcome':'LINK_SENT'}).json()['outcome']=='RECOVERED'
    assert tool(session,'retry_payment',{'consent':True}).json()['status']=='already_recovered'
    with connect(s) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='payment_confirmed'").fetchone()[0]==1


def test_expired_link(session):
    verify(session);tool(session,'send_payment_link',{'consent':True})
    with connect(session[1]) as db:
        token=db.execute('SELECT token FROM links').fetchone()[0]
        db.execute('UPDATE links SET expires_at=?',((datetime.now(IST)-timedelta(days=1)).isoformat(),))
    assert session[0].post('/pay/'+token).status_code==410


def test_razorpay_signature_amount_and_duplicate(session):
    verify(session);tool(session,'send_payment_link',{'consent':True})
    client,s,call=session
    s.razorpay_webhook_secret='test-signature-secret'
    with connect(s) as db:
        db.execute("UPDATE links SET provider_id='plink_test',state='ready'")
    body={'event':'payment_link.paid','payload':{'payment_link':{'entity':{'id':'plink_test','status':'paid','currency':'INR','amount':299900,'amount_paid':299900}}}}
    raw=json.dumps(body).encode()
    signature=hmac.new(s.razorpay_webhook_secret.encode(),raw,hashlib.sha256).hexdigest()
    assert client.post('/webhooks/razorpay',content=raw).status_code==401
    assert client.post('/webhooks/razorpay',content=raw,headers={'X-Razorpay-Signature':signature}).status_code==200
    assert client.post('/webhooks/razorpay',content=raw,headers={'X-Razorpay-Signature':signature}).status_code==200
    body['payload']['payment_link']['entity']['amount_paid']=1
    raw=json.dumps(body).encode();signature=hmac.new(s.razorpay_webhook_secret.encode(),raw,hashlib.sha256).hexdigest()
    assert client.post('/webhooks/razorpay',content=raw,headers={'X-Razorpay-Signature':signature}).status_code==409


def test_due_schedule_runs_once(session):
    verify(session)
    tool(session,'schedule_retry',{'consent':True,'date':(today()+timedelta(days=1)).isoformat()})
    with connect(session[1]) as db:
        db.execute('UPDATE schedules SET due_date=?',(today().isoformat(),))
    tick(session[1]);tick(session[1])
    with connect(session[1]) as db:
        assert db.execute('SELECT state FROM schedules').fetchone()[0]=='failed'
        assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='scheduled_mock_retry'").fetchone()[0]==1


def test_dnc_cancels_schedule(session):
    verify(session)
    tool(session,'schedule_retry',{'consent':True,'date':(today()+timedelta(days=1)).isoformat()})
    tool(session,'mark_dnc')
    with connect(session[1]) as db:
        assert db.execute('SELECT state FROM schedules').fetchone()[0]=='cancelled'


def test_live_keys_rejected(env):
    s=env[1];s.razorpay_key_id='rzp_live_forbidden'
    import pytest
    with pytest.raises(ValueError,match='TEST'):
        s.validate()
