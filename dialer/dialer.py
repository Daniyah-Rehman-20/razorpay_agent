"""Run from repository root: python -m dialer.dialer --dry-run"""
import argparse
import time
from fastapi import HTTPException
from app.config import Settings
from app.db import connect, init_db
from app.calls import start, skip_reason


def main():
    parser=argparse.ArgumentParser(description='Sequential, allowlisted demo dialer')
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--all',action='store_true')
    group.add_argument('--customer')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--override-hours',action='store_true',help='Own-phone demo recording only')
    args=parser.parse_args()
    if not(args.all or args.customer or args.dry_run):
        parser.error('Choose --all, --customer C001 or --dry-run')
    s=Settings(); s.validate(); init_db(s)
    with connect(s) as db:
        rows=db.execute('SELECT * FROM customers'+(' WHERE customer_id=?' if args.customer else '')+' ORDER BY customer_id', (args.customer,) if args.customer else ()).fetchall()
    if not rows:
        parser.error('Unknown customer')
    for c in rows:
        reason=skip_reason(c,s,args.override_hours)
        print(c['customer_id'], 'SKIP: '+reason if reason else 'ELIGIBLE', '(dry run)' if args.dry_run else '')
        if args.dry_run or reason:
            continue
        try:
            result=start(s,c['customer_id'],override_hours=args.override_hours)
            print(result)
        except HTTPException as exc:
            print('BLOCKED:',exc.detail)
            break
        if s.provider=='mock':
            print('No telephone call was placed. Complete/end this mock call in the dashboard before dialing again.')
            break
        # Wait for the end webhook; never assume a 30-second pause means the last call ended.
        deadline=time.monotonic()+360
        while time.monotonic()<deadline:
            with connect(s) as db:
                state=db.execute('SELECT state FROM calls WHERE id=?',(result['call_id'],)).fetchone()[0]
            if state=='ended':
                break
            time.sleep(2)
        else:
            print('End webhook missing; stopping. Reconcile the call before continuing.')
            break
        time.sleep(30)

if __name__=='__main__':
    main()
