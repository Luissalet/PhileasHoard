"""SQLite connection (WAL) and ordered schema migrations."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: settings, shipments, events, mails, notifications, runs
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE shipments (
      id TEXT PRIMARY KEY,
      label TEXT NOT NULL DEFAULT '',
      item TEXT NOT NULL DEFAULT '',
      merchant TEXT NOT NULL DEFAULT '',
      merchant_domain TEXT NOT NULL DEFAULT '',
      order_ref TEXT NOT NULL DEFAULT '',
      sub_ref TEXT NOT NULL DEFAULT '',
      carrier TEXT NOT NULL DEFAULT '',
      tracking_number TEXT NOT NULL DEFAULT '',
      tracking_url TEXT NOT NULL DEFAULT '',
      merchant_url TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'unknown',
      status_text TEXT NOT NULL DEFAULT '',
      status_ts REAL,
      status_source TEXT NOT NULL DEFAULT '',
      origin_country TEXT NOT NULL DEFAULT '',
      origin_city TEXT NOT NULL DEFAULT '',
      dest_country TEXT NOT NULL DEFAULT '',
      last_location TEXT NOT NULL DEFAULT '',
      service TEXT NOT NULL DEFAULT '',
      ordered_ts REAL,
      shipped_ts REAL,
      first_scan_ts REAL,
      out_for_delivery_ts REAL,
      delivered_ts REAL,
      delivered_assumed INTEGER NOT NULL DEFAULT 0,
      carrier_eta_from TEXT NOT NULL DEFAULT '',
      carrier_eta_to TEXT NOT NULL DEFAULT '',
      carrier_eta_first TEXT NOT NULL DEFAULT '',
      merchant_eta_from TEXT NOT NULL DEFAULT '',
      merchant_eta_to TEXT NOT NULL DEFAULT '',
      merchant_eta_text TEXT NOT NULL DEFAULT '',
      merchant_eta_first TEXT NOT NULL DEFAULT '',
      promise_min_days REAL,
      promise_max_days REAL,
      promise_business INTEGER NOT NULL DEFAULT 0,
      promise_base_ts REAL,
      promise_stage TEXT NOT NULL DEFAULT '',
      eta_from TEXT NOT NULL DEFAULT '',
      eta_to TEXT NOT NULL DEFAULT '',
      eta_likely TEXT NOT NULL DEFAULT '',
      eta_confidence INTEGER NOT NULL DEFAULT 0,
      eta_basis TEXT NOT NULL DEFAULT '[]',
      pickup_code TEXT NOT NULL DEFAULT '',
      pickup_place TEXT NOT NULL DEFAULT '',
      pickup_deadline TEXT NOT NULL DEFAULT '',
      price REAL,
      currency TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT 'mail',
      history_only INTEGER NOT NULL DEFAULT 0,
      archived INTEGER NOT NULL DEFAULT 0,
      muted INTEGER NOT NULL DEFAULT 0,
      notes TEXT NOT NULL DEFAULT '',
      created_ts REAL NOT NULL,
      updated_ts REAL NOT NULL,
      last_check_ts REAL,
      next_check_ts REAL,
      check_count INTEGER NOT NULL DEFAULT 0,
      fail_count INTEGER NOT NULL DEFAULT 0,
      last_error TEXT NOT NULL DEFAULT '',
      last_change_ts REAL,
      seen_ts REAL,
      extra TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX shipments_number ON shipments(tracking_number);
    CREATE INDEX shipments_order ON shipments(merchant, order_ref);
    CREATE INDEX shipments_due ON shipments(archived, next_check_ts);
    CREATE TABLE events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      shipment_id TEXT NOT NULL REFERENCES shipments(id) ON DELETE CASCADE,
      ts REAL NOT NULL,
      status TEXT NOT NULL DEFAULT '',
      description TEXT NOT NULL DEFAULT '',
      location TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT 'carrier',
      key TEXT NOT NULL,
      created_ts REAL NOT NULL,
      UNIQUE(shipment_id, key)
    );
    CREATE INDEX events_shipment ON events(shipment_id, ts);
    CREATE TABLE mails (
      message_id TEXT PRIMARY KEY,
      ts REAL,
      from_address TEXT NOT NULL DEFAULT '',
      from_name TEXT NOT NULL DEFAULT '',
      subject TEXT NOT NULL DEFAULT '',
      account TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL DEFAULT 'noise',
      score INTEGER NOT NULL DEFAULT 0,
      facts TEXT NOT NULL DEFAULT '{}',
      shipment_id TEXT REFERENCES shipments(id) ON DELETE SET NULL,
      state TEXT NOT NULL DEFAULT 'new',
      snippet TEXT NOT NULL DEFAULT '',
      created_ts REAL NOT NULL
    );
    CREATE INDEX mails_kind ON mails(kind, state, ts);
    CREATE INDEX mails_shipment ON mails(shipment_id);
    CREATE TABLE notifications (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      shipment_id TEXT REFERENCES shipments(id) ON DELETE CASCADE,
      type TEXT NOT NULL,
      severity TEXT NOT NULL DEFAULT 'medium',
      title TEXT NOT NULL DEFAULT '',
      body TEXT NOT NULL DEFAULT '',
      results TEXT NOT NULL DEFAULT '[]',
      dedupe TEXT NOT NULL DEFAULT '',
      seen INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX notifications_ts ON notifications(ts);
    CREATE INDEX notifications_dedupe ON notifications(dedupe);
    CREATE TABLE runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts REAL NOT NULL,
      kind TEXT NOT NULL,
      ref TEXT NOT NULL DEFAULT '',
      ok INTEGER NOT NULL DEFAULT 1,
      duration_ms INTEGER NOT NULL DEFAULT 0,
      detail TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX runs_ts ON runs(ts);
    """,
]


class Database:
    """One connection shared by every thread, guarded by a re-entrant lock.

    The app is the only writer; the MCP bridge never opens this file.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    def migrate(self) -> None:
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for index, sql in enumerate(MIGRATIONS, start=1):
                if index <= current:
                    continue
                script = f"BEGIN;\n{sql}\nINSERT INTO schema_version(version) VALUES ({index});\nCOMMIT;"
                try:
                    self.conn.executescript(script)
                except Exception:
                    if self.conn.in_transaction:
                        self.conn.execute("ROLLBACK")
                    raise

    def version(self) -> int:
        row = self.one("SELECT MAX(version) AS v FROM schema_version")
        return int(row["v"] or 0)

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def transaction(self):
        """`with db.transaction():` — BEGIN IMMEDIATE / COMMIT (ROLLBACK on error) under the lock."""
        return _Transaction(self)

    def close(self) -> None:
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self.conn.close()


class _Transaction:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.db.conn.execute("COMMIT")
            else:
                self.db.conn.execute("ROLLBACK")
        finally:
            self.db.lock.release()
        return False
