from datetime import datetime
from unittest.mock import patch
from app.calls import skip_reason, start
from app.db import connect
from app.tools import IST
from app.provider import Provider, VARIABLE_KEYS
from tests.test_tools import tool


def test_dialer_safeguards(env):
    _,s=env
    c={'dnc':0,'status':'pending','attempt_count':0,'phone':'+919999999999'}
    for hour,eligible in [(8,False),(9,True),(18,True),(19,False)]:
        assert (skip_reason(c,s,current=datetime(2026,10,3,hour,tzinfo=IST)) is None)==eligible
    assert skip_reason({**c,'dnc':1},s)=='do_not_contact'
    assert skip_reason({**c,'status':'RECOVERED'},s)=='already_recovered'
    assert skip_reason({**c,'attempt_count':3},s)=='attempt_cap_reached'
    assert skip_reason({**c,'phone':'+911111111111'},s,True)=='number_not_allowlisted'
    assert skip_reason(c,s,True,current=datetime(2026,10,3,3,tzinfo=IST)) is None


def test_vapi_envelope_and_binding(session):
    client,s,call=session
    body={'message':{'type':'tool-calls','call':{'id':'mock-'+call},'toolCallList':[{'id':'t1','function':{'name':'verify_identity','arguments':'{"customer_id":"C002","answer":"1988"}'}}]}}
    r=client.post('/webhooks/vapi',json=body,headers={'X-Webhook-Secret':s.webhook_secret})
    assert r.json()['results'][0]['toolCallId']=='t1'
    assert 'true' in r.json()['results'][0]['result']
    body['message']['toolCallList'][0]['id']='t2'
    body['message']['toolCallList'][0]['function']['arguments']={'customer_id':'C001','answer':'1990'}
    r=client.post('/webhooks/vapi',json=body,headers={'X-Webhook-Secret':s.webhook_secret})
    assert 'call_customer_mismatch' in r.json()['results'][0]['result']


def test_end_report_fallback_and_duplicate(session):
    client,s,call=session
    body={'message':{'type':'end-of-call-report','call':{'id':'mock-'+call},'endedReason':'voicemail','durationSeconds':12,'cost':0.02,'artifact':{'recordingUrl':'https://example.com/recording','transcriptUrl':'javascript:alert(1)'}}}
    h={'X-Webhook-Secret':s.webhook_secret}
    assert client.post('/webhooks/call_ended',json=body,headers=h).json()['outcome']=='VOICEMAIL'
    assert client.post('/webhooks/call_ended',json=body,headers=h).json()['duplicate']
    with connect(s) as db:
        row=db.execute('SELECT * FROM calls').fetchone()
        assert row['duration']==12 and row['transcript_url'] is None
        assert row['cost']==0.02


def test_end_preserves_logged_outcome(session):
    client,s,call=session
    tool(session,'log_outcome',{'outcome':'WRONG_NUMBER'})
    r=client.post(f'/api/simulate/{call}/end',headers={'Authorization':'Bearer '+s.admin_token})
    assert r.json()['outcome']=='WRONG_NUMBER'


def test_provider_variables_minimal_and_failure_conservative(env):
    _,s=env
    with connect(s) as db:
        db.execute("UPDATE customers SET phone='+919999999999' WHERE customer_id='C001'")
    with patch.object(Provider,'start_call',side_effect=TimeoutError) as mock:
        from fastapi import HTTPException
        import pytest
        with pytest.raises(HTTPException):
            start(s,'C001',override_hours=True)
        variables=mock.call_args.args[2]
        assert set(variables)==VARIABLE_KEYS
    with connect(s) as db:
        assert db.execute('SELECT state FROM calls').fetchone()[0]=='uncertain'
        assert db.execute("SELECT attempt_count FROM customers WHERE customer_id='C001'").fetchone()[0]==1
