import csv
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.config import ROOT


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(settings):
    db = sqlite3.connect(settings.db_path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(settings):
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(settings) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS customers (
          customer_id TEXT PRIMARY KEY, name TEXT, phone TEXT, plan TEXT, amount_due REAL,
          currency TEXT, due_date TEXT, failure_reason TEXT, payment_method TEXT,
          instrument_last4 TEXT, attempt_count INTEGER, language TEXT, verification_answer TEXT,
          retry_result TEXT, scenario TEXT, expected_outcome TEXT, status TEXT,
          verified INTEGER DEFAULT 0, verify_attempts INTEGER DEFAULT 0,
          retries_this_call INTEGER DEFAULT 0, dnc INTEGER DEFAULT 0,
          last_outcome TEXT, last_call_id TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS calls (
          id TEXT PRIMARY KEY, customer_id TEXT REFERENCES customers(customer_id),
          provider_id TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'active',
          verified INTEGER DEFAULT 0, verify_attempts INTEGER DEFAULT 0,
          retries INTEGER DEFAULT 0, outcome TEXT, created_at TEXT, ended_at TEXT,
          duration REAL DEFAULT 0, cost REAL DEFAULT 0, transcript_url TEXT, recording_url TEXT,
          mode TEXT NOT NULL DEFAULT 'mock');
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_call ON calls((1))
          WHERE state IN ('active','placing','uncertain');
        CREATE TABLE IF NOT EXISTS call_log (
          id INTEGER PRIMARY KEY, customer_id TEXT, call_id TEXT UNIQUE,
          outcome TEXT, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, customer_id TEXT, call_id TEXT, event_type TEXT,
          payload_json TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS idempotency (
          call_id TEXT, request_id TEXT, fingerprint TEXT, result TEXT,
          PRIMARY KEY(call_id,request_id));
        CREATE TABLE IF NOT EXISTS links (
          token TEXT PRIMARY KEY, customer_id TEXT, call_id TEXT, url TEXT,
          state TEXT, expires_at TEXT, provider_id TEXT UNIQUE, amount_paise INTEGER,
          created_at TEXT, UNIQUE(call_id));
        CREATE TABLE IF NOT EXISTS schedules (
          id TEXT PRIMARY KEY, customer_id TEXT, call_id TEXT UNIQUE, due_date TEXT,
          state TEXT DEFAULT 'pending', created_at TEXT);
        CREATE TABLE IF NOT EXISTS callbacks (
          id TEXT PRIMARY KEY, customer_id TEXT, call_id TEXT, time_window TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS webhook_receipts (id TEXT PRIMARY KEY, created_at TEXT);
        ''')
        if db.execute('SELECT COUNT(*) FROM customers').fetchone()[0] == 0:
            with (ROOT / 'data/customers.csv').open(newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    row['updated_at'] = now()
                    db.execute(f"INSERT INTO customers ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", list(row.values()))


def event(db, cid, call_id, kind, payload):
    db.execute('INSERT INTO events(customer_id,call_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)',
               (cid, call_id, kind, json.dumps(payload), now()))
