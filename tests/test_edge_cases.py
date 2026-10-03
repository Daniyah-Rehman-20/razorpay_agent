import json
from datetime import timedelta
from app.db import connect
from app.tools import today
from tests.test_tools import tool,verify


def test_unicode_verification_answer_is_safe(session):
    assert tool(session,'verify_identity',{'answer':'१९८८'}).status_code==200
    assert tool(session,'verify_identity',{'answer':'wrong'}).json()['locked']


def test_current_vapi_tool_shape(session):
    client,s,call=session
    body={'message':{'type':'tool-calls','call':{'id':'mock-'+call},'toolCallList':[{'id':'flat-1','name':'verify_identity','parameters':{'customer_id':'C002','answer':'1988'}}]}}
    r=client.post('/webhooks/vapi',json=body,headers={'X-Webhook-Secret':s.webhook_secret})
    assert json.loads(r.json()['results'][0]['result'])=={'verified':True}


def test_number_level_dnc_and_placeholder_isolation(session):
    client,s,call=session
    with connect(s) as db:
        db.execute("UPDATE customers SET phone='+919999999999' WHERE customer_id IN ('C002','C003')")
    tool(session,'mark_dnc')
    with connect(s) as db:
        assert db.execute('SELECT COUNT(*) FROM customers WHERE dnc=1').fetchone()[0]==2


def test_denied_tools_are_audited(session):
    tool(session,'get_payment_details')
    with connect(session[1]) as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE event_type='tool_rejected'").fetchone()[0]==1


def test_link_creation_is_unique_with_new_request_keys(session):
    verify(session)
    for _ in range(3):
        assert tool(session,'send_payment_link',{'consent':True}).status_code==200
    with connect(session[1]) as db:
        assert db.execute('SELECT COUNT(*) FROM links').fetchone()[0]==1


def test_dashboard_never_returns_birth_year_or_phone(session):
    client,s,_=session
    r=client.get('/api/dashboard',headers={'Authorization':'Bearer '+s.admin_token})
    assert r.status_code==200
    assert 'verification_answer' not in r.text
    assert 'phone' not in r.json()['customers'][0]


def test_successful_retry_second_action_is_blocked(session):
    verify(session)
    with connect(session[1]) as db:
        db.execute("UPDATE customers SET retry_result='success' WHERE customer_id='C002'")
    assert tool(session,'retry_payment',{'consent':True}).json()['status']=='success'
    assert tool(session,'retry_payment',{'consent':True}).json()['reason']=='retry_already_used'


def test_external_link_job_uses_test_credentials_and_paise(session):
    from unittest.mock import patch,MagicMock
    from app.payments import tick
    client,s,call=session
    verify(session)
    s.razorpay_key_id='rzp_test_fake';s.razorpay_key_secret='fake';s.razorpay_webhook_secret='fake'
    assert tool(session,'send_payment_link',{'consent':True}).json()['status']=='pending'
    response=MagicMock();response.json.return_value={'id':'plink_1','short_url':'https://rzp.io/test'}
    with patch('app.payments.httpx.Client') as http:
        http.return_value.__enter__.return_value.post.return_value=response
        tick(s)
        req=http.return_value.__enter__.return_value.post.call_args
        assert req.kwargs['json']['amount']==299900
        assert req.kwargs['json']['notify']['sms'] is False
    assert tool(session,'send_payment_link',{'consent':True}).json()['sent']


def test_external_timeout_not_retried(session):
    from unittest.mock import patch
    from app.payments import tick
    _,s,_=session
    verify(session)
    s.razorpay_key_id='rzp_test_fake'
    tool(session,'send_payment_link',{'consent':True})
    with patch('app.payments.httpx.Client') as http:
        http.return_value.__enter__.return_value.post.side_effect=TimeoutError
        tick(s);tick(s)
        assert http.return_value.__enter__.return_value.post.call_count==1
    with connect(s) as db:
        assert db.execute('SELECT state FROM links').fetchone()[0]=='needs_review'
