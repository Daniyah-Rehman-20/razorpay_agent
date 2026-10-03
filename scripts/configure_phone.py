"""Explicitly assign an approved test phone to one fictional customer."""
import argparse
import re
from app.config import Settings
from app.db import connect, init_db, now
p=argparse.ArgumentParser()
p.add_argument('--customer',required=True)
p.add_argument('--phone',required=True)
a=p.parse_args()
s=Settings();s.validate();init_db(s)
if not re.fullmatch(r'\+[1-9]\d{7,14}',a.phone) or a.phone not in s.allowed_numbers:
    p.error('Phone must be valid E.164 and already in ALLOWED_TEST_NUMBERS.')
with connect(s) as db:
    db.execute('BEGIN IMMEDIATE')
    if db.execute("SELECT 1 FROM calls WHERE state!='ended'").fetchone():
        p.error('Finish or reconcile the active call first.')
    if db.execute('SELECT 1 FROM customers WHERE phone=? AND dnc=1',(a.phone,)).fetchone():
        p.error('This number is opted out. Opt-out cannot be removed by this utility.')
    c=db.execute('SELECT dnc FROM customers WHERE customer_id=?',(a.customer,)).fetchone()
    if not c or c['dnc']:
        p.error('Customer is missing or opted out.')
    db.execute('UPDATE customers SET phone=?,updated_at=? WHERE customer_id=?',(a.phone,now(),a.customer))
print('Approved test phone assigned. No call was placed.')
