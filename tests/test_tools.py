from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import json
import pytest
from app.db import connect
from app.tools import today


def tool(session,name,payload=None,cid='C002',key=None):
    client,s,call=session
    return client.post('/tools/'+name,json={'customer_id':cid,**(payload or {})},headers={'X-Webhook-Secret':s.webhook_secret,'X-Call-Id':call,'Idempotency-Key':key or uuid4().hex})

def verify(session):
    assert tool(session,'verify_identity',{'answer':'  1988  '}).json()=={'verified':True}


def test_auth_and_no_details_before_verification(session):
    client,s,call=session
    assert client.post('/tools/get_payment_details',json={'customer_id':'C002'}).status_code==401
    assert tool(session,'get_payment_details').status_code==403
    assert client.get('/api/dashboard').status_code==401
    assert client.get('/health').status_code==200


def test_verification_and_lockout(session):
    assert tool(session,'verify_identity',{'answer':'no'}).json()['attempts_left']==1
    assert tool(session,'verify_identity',{'answer':'bad'}).json()['locked']
    assert tool(session,'verify_identity',{'answer':'1988'}).json()['locked']
    assert tool(session,'get_payment_details').status_code==403


def test_success_and_no_answer_in_audit(session):
    verify(session)
    assert tool(session,'get_payment_details').json()['plan']=='RazorpayX Payroll Starter'
    with connect(session[1]) as db:
        rows=db.execute('SELECT payload_json FROM events').fetchall()
        assert all('1988' not in r[0] for r in rows)
        assert all('1988' not in r[0] for r in db.execute('SELECT fingerprint FROM idempotency'))


def test_identity_does_not_leak_across_calls(session):
    verify(session)
    client,s,call=session
    headers={'Authorization':'Bearer '+s.admin_token}
    assert client.post(f'/api/simulate/{call}/end',headers=headers).status_code==200
    second=client.post('/api/simulate/C002',headers=headers).json()['call_id']
    assert tool((client,s,second),'get_payment_details').status_code==403
    assert tool(session,'get_payment_details').status_code==409


def test_cross_customer_denied(session):
    assert tool(session,'verify_identity',{'answer':'1990'},cid='C001').status_code==403


def test_retry_once_and_consent(session):
    verify(session)
    assert tool(session,'retry_payment').status_code==422
    assert tool(session,'retry_payment',{'consent':False}).status_code==422
    first=tool(session,'retry_payment',{'consent':True}).json()
    assert first['status']=='failed' and first['txn_ref'].startswith('MOCK-')
    assert tool(session,'retry_payment',{'consent':True}).json()['reason']=='retry_already_used'


def test_retry_atomic_under_concurrency(session):
    verify(session)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:tool(session,'retry_payment',{'consent':True}).json()['status'],range(2)))
    assert sorted(results)==['failed','not_allowed']


def test_idempotency_replays_without_counting_twice(session):
    a=tool(session,'verify_identity',{'answer':'wrong'},key='same')
    b=tool(session,'verify_identity',{'answer':'wrong'},key='same')
    assert a.json()==b.json() and b.json()['attempts_left']==1
    assert tool(session,'verify_identity',{'answer':'1988'},key='same').status_code==409
    verify(session)

@pytest.mark.parametrize('offset,expected',[(0,False),(-1,False),(1,True),(7,True),(8,False)])
def test_schedule_boundaries(session,offset,expected):
    verify(session)
    assert tool(session,'schedule_retry',{'date':(today()+timedelta(days=offset)).isoformat(),'consent':True}).json()['scheduled']==expected

@pytest.mark.parametrize('date',['2026-2-03','not-a-date','2026-99-99',''])
def test_invalid_schedule_date(session,date):
    verify(session)
    assert tool(session,'schedule_retry',{'date':date,'consent':True}).json()['scheduled'] is False


def test_invalid_and_unearned_outcomes(session):
    assert tool(session,'log_outcome',{'outcome':'MADE_UP'}).status_code==422
    assert tool(session,'log_outcome',{'outcome':'RECOVERED'}).status_code==409
    assert tool(session,'log_outcome',{'outcome':'LINK_SENT'}).status_code==409
    assert tool(session,'log_outcome',{'outcome':'DNC'}).status_code==409


def test_expired_card_skips_retry(env):
    client,s=env
    call=client.post('/api/simulate/C001',headers={'Authorization':'Bearer '+s.admin_token}).json()['call_id']
    session=(client,s,call)
    assert tool(session,'verify_identity',{'answer':'1990'},cid='C001').json()['verified']
    assert tool(session,'retry_payment',{'consent':True},cid='C001').json()['reason']=='payment_method_update_required'
    assert tool(session,'schedule_retry',{'consent':True,'date':(today()+timedelta(days=1)).isoformat()},cid='C001').json()['scheduled'] is False


def test_unverified_support_and_dnc(session):
    assert tool(session,'request_callback',{'time_window':'tomorrow afternoon'}).status_code==200
    assert tool(session,'escalate_to_human',{'reason':'Customer asks for human'}).json()['ticket_id']
    assert tool(session,'mark_dnc').json()['dnc']
    assert tool(session,'verify_identity',{'answer':'1988'}).status_code==409
    assert tool(session,'log_outcome',{'outcome':'NO_CONTACT'}).json()['outcome']=='DNC'


def test_unknown_customer_and_missing_context(env):
    client,s=env
    assert client.post('/api/simulate/C999',headers={'Authorization':'Bearer '+s.admin_token}).status_code==404
    assert client.post('/tools/get_payment_details',json={'customer_id':'C002'},headers={'X-Webhook-Secret':s.webhook_secret}).status_code==400


def test_only_one_active_call(session):
    client,s,_=session
    assert client.post('/api/simulate/C001',headers={'Authorization':'Bearer '+s.admin_token}).status_code==409
