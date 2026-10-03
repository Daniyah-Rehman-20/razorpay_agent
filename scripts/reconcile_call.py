"""Resolve a missing/ambiguous provider response after inspecting Vapi manually."""
import argparse
from app.config import Settings
from app.db import connect, event
from app.calls import finish
p=argparse.ArgumentParser()
p.add_argument('--call-id',required=True)
p.add_argument('--provider-id',help='Attach a confirmed provider call ID; does not end the call')
p.add_argument('--confirmed-ended',action='store_true',help='Only after confirming no call remains active at the provider')
a=p.parse_args();s=Settings();s.validate()
if bool(a.provider_id)==bool(a.confirmed_ended):
    p.error('Choose --provider-id or --confirmed-ended')
if a.confirmed_ended:
    print(finish(s,a.call_id,{'outcome':'TECH_ERROR'}))
else:
    with connect(s) as db:
        row=db.execute("SELECT * FROM calls WHERE id=? AND state IN ('placing','uncertain')",(a.call_id,)).fetchone()
        if not row:
            p.error('Call does not require reconciliation')
        db.execute("UPDATE calls SET provider_id=?,state='active' WHERE id=?",(a.provider_id,a.call_id))
        event(db,row['customer_id'],a.call_id,'provider_id_reconciled',{})
    print('Provider call linked. Wait for its end webhook before further calls.')
