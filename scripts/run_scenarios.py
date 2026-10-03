"""All ten scenarios in an isolated TEMP database. Never contacts an external provider."""
import tempfile
from pathlib import Path
from datetime import timedelta
from uuid import uuid4
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.tools import today
from app.db import connect


def main():
    with tempfile.TemporaryDirectory(prefix='autopay-demo-') as directory:
        s=Settings(db_path=str(Path(directory)/'demo.db'),admin_token='demo-admin-'+uuid4().hex,
                   webhook_secret='demo-hook-'+uuid4().hex,provider='mock',razorpay_key_id='',razorpay_key_secret='',razorpay_webhook_secret='')
        with TestClient(create_app(s,run_worker=False)) as client:
            h={'Authorization':'Bearer '+s.admin_token}
            def action(call,cid,name,**fields):
                r=client.post(f'/api/simulate/{call}/tools/{name}',json={'customer_id':cid,**fields},headers={**h,'Idempotency-Key':uuid4().hex})
                assert r.status_code==200,(name,r.text)
                return r.json()
            answers={'C001':'1990','C002':'1988','C003':'1993','C004':'1985','C005':'1992','C009':'1989'}
            for i in range(1,11):
                cid=f'C{i:03d}'
                call=client.post('/api/simulate/'+cid,headers=h).json()['call_id']
                if cid in answers:
                    action(call,cid,'verify_identity',answer=answers[cid])
                    action(call,cid,'get_payment_details')
                if cid in {'C001','C003','C009'}:
                    action(call,cid,'send_payment_link',consent=True)
                    outcome='LINK_SENT'
                elif cid=='C002':
                    action(call,cid,'schedule_retry',consent=True,date=(today()+timedelta(days=1)).isoformat());outcome='PROMISE_TO_PAY'
                elif cid in {'C004','C005'}:
                    action(call,cid,'escalate_to_human',reason='dispute' if cid=='C004' else 'cancelled already')
                    outcome='DISPUTE' if cid=='C004' else 'CANCELLED_CLAIM'
                elif cid=='C006':outcome='WRONG_NUMBER'
                elif cid=='C007':
                    action(call,cid,'verify_identity',answer='wrong');action(call,cid,'verify_identity',answer='wrong');outcome='VERIFICATION_FAILED'
                elif cid=='C008':action(call,cid,'mark_dnc');outcome='DNC'
                else:outcome='VOICEMAIL'
                action(call,cid,'log_outcome',outcome=outcome)
                assert client.post(f'/api/simulate/{call}/end',headers=h).status_code==200
                if cid in {'C001','C009'}:
                    with connect(s) as db:
                        token=db.execute('SELECT token FROM links WHERE call_id=?',(call,)).fetchone()[0]
                    assert client.post('/pay/'+token).status_code==200
                    outcome='RECOVERED'
                print(cid,outcome)
            result=client.get('/api/dashboard',headers=h).json()['metrics']
            assert result['calls']==10 and result['recovered']==2 and result['recovery_rate']==20 and result['dnc']==1
            print(result)

if __name__=='__main__':
    main()
