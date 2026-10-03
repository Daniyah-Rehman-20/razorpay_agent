import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.config import Settings, ROOT
from app.db import connect, init_db
from app.security import admin_auth, webhook_auth
from app.tools import execute
from app.calls import start, finish, skip_reason
from app.provider import Provider
from app.payments import complete_mock, payment_webhook, tick


def create_app(settings=None, run_worker=True):
    settings=settings or Settings()
    @asynccontextmanager
    async def lifespan(app):
        settings.validate()
        init_db(settings)
        async def worker():
            while True:
                try:
                    await asyncio.to_thread(tick,settings)
                except Exception:
                    import logging
                    logging.exception('Worker cycle failed')
                await asyncio.sleep(2)
        task=asyncio.create_task(worker()) if run_worker else None
        yield
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    app=FastAPI(title='Autopay Recovery Demo',version='1.0.0',lifespan=lifespan)
    app.state.settings=settings
    app.mount('/static',StaticFiles(directory=ROOT/'app/static'),name='static')

    @app.exception_handler(HTTPException)
    async def error(request,exc):
        return JSONResponse({'error':exc.detail},status_code=exc.status_code)

    @app.middleware('http')
    async def secure_headers(request,call_next):
        try:
            length=int(request.headers.get('content-length','0') or 0)
        except ValueError:
            return JSONResponse({'error':'invalid_content_length'},status_code=400)
        if length>1_000_000:
            return JSONResponse({'error':'payload_too_large'},status_code=413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.get('/health')
    def health():
        with connect(settings) as db:
            db.execute('SELECT 1')
        return {'status':'ok','provider':settings.provider,'payments':'test' if settings.razorpay_key_id else 'mock'}

    @app.get('/')
    @app.get('/dashboard')
    def dashboard():
        return FileResponse(ROOT/'app/static/index.html')

    @app.get('/api/dashboard',dependencies=[Depends(admin_auth)])
    def dashboard_data():
        with connect(settings) as db:
            customers=[dict(x) for x in db.execute('''SELECT c.customer_id,c.name,c.plan,c.amount_due,c.currency,c.attempt_count,
                c.language,c.scenario,c.status,c.dnc,c.last_outcome,c.last_call_id,
                a.state AS call_state,a.mode,a.duration,a.cost,a.transcript_url,a.recording_url
                FROM customers c LEFT JOIN calls a ON a.id=c.last_call_id ORDER BY c.customer_id''')]
            calls=[dict(x) for x in db.execute('SELECT * FROM calls ORDER BY created_at DESC')]
            events=[dict(x) for x in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 80')]
            links=[dict(x) for x in db.execute('SELECT customer_id,call_id,url,state,created_at FROM links ORDER BY created_at DESC')]
            schedules=[dict(x) for x in db.execute('SELECT * FROM schedules ORDER BY created_at DESC')]
            called=db.execute('SELECT COUNT(DISTINCT customer_id) FROM calls').fetchone()[0]
            recovered=sum(c['status']=='RECOVERED' for c in customers)
            metrics={'calls':len(calls),'recovered':recovered,'promised':sum(c['last_outcome']=='PROMISE_TO_PAY' for c in customers),
                     'escalated':sum(c['last_outcome'] in ('ESCALATED','DISPUTE','CANCELLED_CLAIM') for c in customers),
                     'dnc':sum(c['dnc'] for c in customers),'no_contact':sum(c['last_outcome'] in ('NO_CONTACT','VOICEMAIL','NO_RESPONSE') for c in customers),
                     'recovery_rate':round(recovered/called*100,1) if called else 0,
                     'recovered_amount':sum(c['amount_due'] for c in customers if c['status']=='RECOVERED')}
            return {'customers':customers,'calls':calls,'events':events,'links':links,'schedules':schedules,'metrics':metrics,'provider':settings.provider}

    @app.post('/tools/{name}',dependencies=[Depends(webhook_auth)])
    def tool(name:str,data:dict,x_call_id:str=Header(default=''),idempotency_key:str=Header(default='')):
        return execute(settings,name,data,x_call_id,idempotency_key)

    @app.post('/api/simulate/{cid}',dependencies=[Depends(admin_auth)])
    def simulate(cid:str):
        return start(settings,cid,simulation=True)

    @app.post('/api/simulate/{call_id}/tools/{name}',dependencies=[Depends(admin_auth)])
    def simulate_tool(call_id:str,name:str,data:dict,idempotency_key:str=Header(default='')):
        with connect(settings) as db:
            call=db.execute('SELECT mode FROM calls WHERE id=?',(call_id,)).fetchone()
            if not call or call['mode']!='mock':
                raise HTTPException(403,'simulation_only')
        return execute(settings,name,data,call_id,idempotency_key)

    @app.post('/api/simulate/{call_id}/end',dependencies=[Depends(admin_auth)])
    def end_simulation(call_id:str):
        with connect(settings) as db:
            call=db.execute('SELECT mode FROM calls WHERE id=?',(call_id,)).fetchone()
            if not call or call['mode']!='mock':
                raise HTTPException(403,'simulation_only')
        return finish(settings,call_id)

    @app.get('/api/dialer/preview',dependencies=[Depends(admin_auth)])
    def preview():
        with connect(settings) as db:
            return [{'customer_id':c['customer_id'],'eligible':skip_reason(c,settings) is None,'reason':skip_reason(c,settings)} for c in db.execute('SELECT * FROM customers')]

    @app.post('/webhooks/vapi',dependencies=[Depends(webhook_auth)])
    @app.post('/webhooks/call_ended',dependencies=[Depends(webhook_auth)])
    def vapi(body:dict):
        message=body.get('message',{})
        kind=message.get('type')
        pid=message.get('call',{}).get('id')
        with connect(settings) as db:
            call=db.execute('SELECT * FROM calls WHERE provider_id=?',(pid,)).fetchone()
        if not call:
            raise HTTPException(404,'unknown_provider_call')
        if kind=='tool-calls':
            try:
                _,items=Provider.parse_tools(body)
            except (ValueError,TypeError,KeyError):
                raise HTTPException(422,'invalid_provider_tools')
            results=[]
            for tool_id,name,args in items:
                try:
                    # Trusted call ID binds customer. An LLM-supplied different customer is rejected.
                    if not isinstance(args,dict) or args.get('customer_id')!=call['customer_id']:
                        raise HTTPException(403,'call_customer_mismatch')
                    result=execute(settings,name,args,call['id'],'vapi-'+tool_id)
                except HTTPException as exc:
                    result={'error':exc.detail}
                results.append({'name':name,'toolCallId':tool_id,'result':json.dumps(result)})
            return {'results':results}
        if kind=='end-of-call-report':
            try:
                info=Provider.parse_end(body)
            except (ValueError,TypeError):
                raise HTTPException(422,'invalid_call_report')
            return finish(settings,call['id'],info)
        return {'ignored':True}

    @app.get('/pay/{token}')
    def payment_page(token:str):
        with connect(settings) as db:
            if not db.execute('SELECT 1 FROM links WHERE token=?',(token,)).fetchone():
                raise HTTPException(404,'link_not_found')
        return FileResponse(ROOT/'app/static/pay.html')

    @app.post('/pay/{token}')
    def pay(token:str):
        return complete_mock(settings,token)

    @app.post('/webhooks/razorpay')
    async def razorpay(request:Request,x_razorpay_signature:str=Header(default='')):
        raw=await request.body()
        return await asyncio.to_thread(payment_webhook,settings,raw,x_razorpay_signature)

    return app

app=create_app()
