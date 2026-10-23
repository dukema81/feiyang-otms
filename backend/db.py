# -*- coding: utf-8 -*-
"""飞洋 OTMS 数据层：建表 + 连接管理（零依赖，SQLite WAL）"""
import os, sqlite3, threading

DB_PATH = os.environ.get("OY_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "feiyang.db"))
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS ports(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, country TEXT,
  status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS vessels(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, imo TEXT UNIQUE,
  vtype TEXT DEFAULT 'container', dwt INTEGER DEFAULT 0, teu INTEGER DEFAULT 0,
  flag TEXT, status TEXT DEFAULT 'active', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS voyages(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, vessel_id INTEGER NOT NULL,
  pol_id INTEGER NOT NULL, pod_id INTEGER NOT NULL,
  etd TEXT, eta TEXT, atd TEXT, ata TEXT, note TEXT,
  status TEXT DEFAULT 'planned', created_by TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, voyage_id INTEGER NOT NULL,
  shipper_id INTEGER NOT NULL, consignee TEXT, cargo_desc TEXT,
  boxes INTEGER DEFAULT 1, ctype TEXT DEFAULT '20GP',
  status TEXT DEFAULT 'booked', created_by TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS containers(
  id INTEGER PRIMARY KEY, container_no TEXT UNIQUE, ctype TEXT DEFAULT '20GP',
  seal_no TEXT, voyage_id INTEGER, booking_id INTEGER,
  status TEXT DEFAULT 'empty', unloaded_at TEXT, returned_at TEXT,
  version INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bls(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, booking_id INTEGER NOT NULL,
  shipper TEXT, consignee TEXT, notify_party TEXT, cargo_desc TEXT,
  boxes INTEGER DEFAULT 1, status TEXT DEFAULT 'draft',
  issued_at TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS rates(
  id INTEGER PRIMARY KEY, pol_id INTEGER NOT NULL, pod_id INTEGER NOT NULL,
  ctype TEXT NOT NULL, base_cents INTEGER DEFAULT 0, surcharge_cents INTEGER DEFAULT 0,
  valid_from TEXT, valid_to TEXT, note TEXT, status TEXT DEFAULT 'active',
  version INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS partners(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL,
  ptype TEXT DEFAULT 'customer', contact TEXT, phone TEXT,
  receivable_cents INTEGER DEFAULT 0, payable_cents INTEGER DEFAULT 0,
  credit_limit_cents INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bills(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, btype TEXT NOT NULL, partner_id INTEGER NOT NULL,
  amount_cents INTEGER DEFAULT 0, settled_cents INTEGER DEFAULT 0, due_date TEXT,
  ref TEXT, version INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bill_settlements(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL, amount_cents INTEGER DEFAULT 0,
  method TEXT, note TEXT,
  settled_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS flows(
  id INTEGER PRIMARY KEY, no TEXT UNIQUE, ftype TEXT NOT NULL, category TEXT,
  amount_cents INTEGER DEFAULT 0, counter_party TEXT, partner_id INTEGER,
  summary TEXT, created_by TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS risks(
  id INTEGER PRIMARY KEY, rtype TEXT, ref_id INTEGER, title TEXT, detail TEXT,
  score INTEGER DEFAULT 0, grade TEXT DEFAULT 'info', status TEXT DEFAULT 'open',
  resolved_by TEXT, note TEXT, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT NOT NULL, name TEXT,
  role TEXT DEFAULT 'reader', phone TEXT, status INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS tokens(token TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS api_keys(
  id INTEGER PRIMARY KEY, name TEXT, key_hash TEXT UNIQUE, prefix TEXT, perms TEXT DEFAULT 'sea.*',
  created_at TEXT DEFAULT (datetime('now','localtime')), last_used TEXT, status INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY, title TEXT, content TEXT, level TEXT DEFAULT 'info', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY, ts TEXT, user_id INTEGER, action TEXT, detail TEXT, ip TEXT);
CREATE TABLE IF NOT EXISTS idem_keys(key TEXT PRIMARY KEY, user_id INTEGER, response TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sync_state(entity TEXT PRIMARY KEY, version INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS oy_rules(id INTEGER PRIMARY KEY, name TEXT, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS seq(name TEXT PRIMARY KEY, val INTEGER DEFAULT 0);

CREATE INDEX IF NOT EXISTS idx_voyages_status ON voyages(status);
CREATE INDEX IF NOT EXISTS idx_voyages_vessel ON voyages(vessel_id);
CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_voyage ON bookings(voyage_id);
CREATE INDEX IF NOT EXISTS idx_containers_status ON containers(status);
CREATE INDEX IF NOT EXISTS idx_bls_booking ON bls(booking_id);
CREATE INDEX IF NOT EXISTS idx_rates_lane ON rates(pol_id, pod_id, ctype);
CREATE INDEX IF NOT EXISTS idx_bills_due ON bills(due_date, btype);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts);
"""

def get_db():
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

def q(sql, params=()):
    return get_db().execute(sql, params).fetchall()

def q1(sql, params=()):
    return get_db().execute(sql, params).fetchone()

def execute(sql, params=()):
    conn = get_db()
    import time as _t
    for attempt in range(30):
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur
        except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
            try:
                conn.rollback()
            except Exception:
                pass
            if "locked" in str(e).lower() and attempt < 29:
                _t.sleep(0.1)
                continue
            raise

def next_seq(name):
    row = q1("SELECT val FROM seq WHERE name=?", (name,))
    if row:
        execute("UPDATE seq SET val=val+1 WHERE name=?", (name,))
        return row["val"] + 1
    execute("INSERT INTO seq(name, val) VALUES(?, 1)", (name,))
    return 1

def make_no(prefix, seq_name):
    from datetime import datetime
    return "%s%s-%03d" % (prefix, datetime.now().strftime("%Y%m%d"), next_seq(seq_name))

def bump_sync(entity, conn=None):
    c = conn or get_db()
    c.execute("INSERT INTO sync_state(entity, version) VALUES(?,1) ON CONFLICT(entity) DO UPDATE SET version=version+1", (entity,))
    c.commit()
    row = c.execute("SELECT version FROM sync_state WHERE entity=?", (entity,)).fetchone()
    return row["version"] if row else 0

def get_sync(entity):
    row = q1("SELECT version FROM sync_state WHERE entity=?", (entity,))
    return row["version"] if row else 0
