import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

@pytest.fixture
def env(tmp_path):
    settings=Settings(db_path=str(tmp_path/'test.db'),webhook_secret='w'*32,admin_token='a'*32,provider='mock',razorpay_key_id='',razorpay_key_secret='',razorpay_webhook_secret='',allowed_numbers={'+919999999999'})
    with TestClient(create_app(settings,run_worker=False)) as client:
        yield client,settings

@pytest.fixture
def session(env):
    client,settings=env
    result=client.post('/api/simulate/C002',headers={'Authorization':'Bearer '+settings.admin_token})
    assert result.status_code==200
    call=result.json()['call_id']
    return client,settings,call
