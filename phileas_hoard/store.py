"""Typed access to the database: shipments, their events, the mails they came from, notifications and runs."""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable, Optional

from .db import Database
from .errors import PhileasError
from .hoard_link.ids import new_id
from .model import ACTIVE, FINAL

JSON_FIELDS = ("eta_basis", "extra")
SHIPMENT_FIELDS = (
    "label", "item", "merchant", "merchant_domain", "order_ref", "sub_ref", "carrier", "tracking_number", "tracking_url", "merchant_url",
    "status", "status_text", "status_ts", "status_source", "origin_country", "origin_city", "dest_country", "last_location", "service",
    "ordered_ts", "shipped_ts", "first_scan_ts", "out_for_delivery_ts", "delivered_ts", "delivered_assumed", "carrier_eta_from",
    "carrier_eta_to", "carrier_eta_first", "merchant_eta_from", "merchant_eta_to", "merchant_eta_text", "merchant_eta_first",
    "promise_min_days", "promise_max_days", "promise_business", "promise_base_ts", "promise_stage", "eta_from", "eta_to", "eta_likely",
    "eta_confidence", "eta_basis", "pickup_code", "pickup_place", "pickup_deadline", "price", "currency", "source", "history_only",
    "archived", "muted", "notes", "last_check_ts", "next_check_ts", "check_count", "fail_count", "last_error", "last_change_ts",
    "seen_ts", "extra")


def _row(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for key in JSON_FIELDS:
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key] or ("[]" if key == "eta_basis" else "{}"))
            except ValueError:
                data[key] = [] if key == "eta_basis" else {}
    for key in ("delivered_assumed", "promise_business", "history_only", "archived", "muted"):
        if key in data:
            data[key] = bool(data[key])
    return data


class Store:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock

    # ------------------------------------------------------------------ shipments
    def create_shipment(self, **fields: Any) -> dict[str, Any]:
        now = self.clock()
        sid = fields.pop("id", None) or new_id("s")
        data = {k: v for k, v in fields.items() if k in SHIPMENT_FIELDS}
        for key in JSON_FIELDS:
            if key in data and not isinstance(data[key], str):
                data[key] = json.dumps(data[key], ensure_ascii=False)
        cols = ["id", "created_ts", "updated_ts", *data.keys()]
        vals = [sid, now, now, *data.values()]
        self.db.execute(f"INSERT INTO shipments({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", vals)
        return self.shipment(sid)

    def update_shipment(self, sid: str, **fields: Any) -> dict[str, Any]:
        data = {k: v for k, v in fields.items() if k in SHIPMENT_FIELDS}
        if data:
            for key in JSON_FIELDS:
                if key in data and not isinstance(data[key], str):
                    data[key] = json.dumps(data[key], ensure_ascii=False)
            for key in ("delivered_assumed", "promise_business", "history_only", "archived", "muted"):
                if key in data and isinstance(data[key], bool):
                    data[key] = int(data[key])
            sets = ", ".join(f"{k} = ?" for k in data)
            self.db.execute(f"UPDATE shipments SET {sets}, updated_ts = ? WHERE id = ?", [*data.values(), self.clock(), sid])
        return self.shipment(sid)

    def shipment(self, sid: str) -> dict[str, Any]:
        row = _row(self.db.one("SELECT * FROM shipments WHERE id = ?", (sid,)))
        if row is None:
            raise PhileasError("not_found", f"No shipment {sid}.", "List shipments with shipments_list.")
        return row

    def find_shipment(self, sid_or_number: str) -> dict[str, Any]:
        key = (sid_or_number or "").strip()
        row = self.db.one("SELECT * FROM shipments WHERE id = ? OR tracking_number = ? OR order_ref = ? ORDER BY created_ts DESC LIMIT 1",
                          (key, key.upper().replace(" ", ""), key))
        if row is None:
            raise PhileasError("not_found", f"No shipment matches {key!r}.", "Use the id, the tracking number or the order number.")
        return _row(row)

    def shipments(self, *, archived: Optional[bool] = False, active: Optional[bool] = None, history_only: Optional[bool] = False,
                  carrier: str = "", merchant: str = "", text: str = "", limit: int = 200) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM shipments WHERE 1=1", []
        if archived is not None:
            sql += " AND archived = ?"
            params.append(int(archived))
        if history_only is not None:
            sql += " AND history_only = ?"
            params.append(int(history_only))
        if active is True:
            sql += f" AND status NOT IN ({', '.join('?' for _ in FINAL)})"
            params.extend(FINAL)
        elif active is False:
            sql += f" AND status IN ({', '.join('?' for _ in FINAL)})"
            params.extend(FINAL)
        if carrier:
            sql += " AND carrier = ?"
            params.append(carrier)
        if merchant:
            sql += " AND merchant = ?"
            params.append(merchant)
        if text:
            sql += " AND (label LIKE ? OR item LIKE ? OR merchant LIKE ? OR tracking_number LIKE ? OR order_ref LIKE ?)"
            params.extend([f"%{text}%"] * 5)
        sql += " ORDER BY COALESCE(last_change_ts, created_ts) DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        return [_row(r) for r in self.db.query(sql, params)]

    def by_number(self, number: str) -> Optional[dict[str, Any]]:
        return _row(self.db.one("SELECT * FROM shipments WHERE tracking_number = ? ORDER BY created_ts DESC LIMIT 1", (number,)))

    def by_sub_ref(self, merchant: str, sub_ref: str) -> Optional[dict[str, Any]]:
        return _row(self.db.one("SELECT * FROM shipments WHERE merchant = ? AND sub_ref = ? ORDER BY created_ts DESC LIMIT 1",
                                (merchant, sub_ref)))

    def by_order(self, merchant: str, order_ref: str) -> list[dict[str, Any]]:
        return [_row(r) for r in self.db.query("SELECT * FROM shipments WHERE merchant = ? AND order_ref = ? ORDER BY created_ts",
                                               (merchant, order_ref))]

    def recent_for(self, *, merchant: str = "", carrier: str = "", since_ts: float = 0) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM shipments WHERE COALESCE(last_change_ts, created_ts) >= ?", [since_ts]
        if merchant:
            sql += " AND merchant = ?"
            params.append(merchant)
        if carrier:
            sql += " AND carrier = ?"
            params.append(carrier)
        sql += " ORDER BY created_ts DESC LIMIT 50"
        return [_row(r) for r in self.db.query(sql, params)]

    def due(self, now: float, limit: int = 20) -> list[dict[str, Any]]:
        placeholders = ", ".join("?" for _ in ACTIVE)
        rows = self.db.query(
            f"SELECT * FROM shipments WHERE archived = 0 AND history_only = 0 AND tracking_number != '' AND status IN ({placeholders}) "
            "AND (next_check_ts IS NULL OR next_check_ts <= ?) ORDER BY COALESCE(next_check_ts, 0) LIMIT ?", [*ACTIVE, now, limit])
        return [_row(r) for r in rows]

    def delete_shipment(self, sid: str) -> None:
        self.shipment(sid)
        self.db.execute("DELETE FROM shipments WHERE id = ?", (sid,))

    def merge_into(self, keep: str, drop: str) -> dict[str, Any]:
        """Move events and mails of ``drop`` onto ``keep`` and delete ``drop``."""
        with self.db.transaction() as conn:
            conn.execute("UPDATE OR IGNORE events SET shipment_id = ? WHERE shipment_id = ?", (keep, drop))
            conn.execute("DELETE FROM events WHERE shipment_id = ?", (drop,))
            conn.execute("UPDATE mails SET shipment_id = ? WHERE shipment_id = ?", (keep, drop))
            conn.execute("UPDATE notifications SET shipment_id = ? WHERE shipment_id = ?", (keep, drop))
            conn.execute("DELETE FROM shipments WHERE id = ?", (drop,))
        return self.shipment(keep)

    # ------------------------------------------------------------------ events
    def add_event(self, sid: str, *, ts: float, status: str, description: str, location: str = "", source: str = "carrier",
                  key: str = "") -> bool:
        key = key or f"{source}|{int(ts)}|{status}|{description[:80]}|{location[:40]}"
        cur = self.db.execute("INSERT OR IGNORE INTO events(shipment_id, ts, status, description, location, source, key, created_ts) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (sid, ts, status, description[:400], location[:160], source, key[:300],
                                                                  self.clock()))
        return cur.rowcount > 0

    def events(self, sid: str, limit: int = 300) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM events WHERE shipment_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
                                               (sid, max(1, min(limit, 2000))))]

    # ------------------------------------------------------------------ mails
    def known_message_ids(self, limit: int = 5000) -> list[str]:
        return [r["message_id"] for r in self.db.query("SELECT message_id FROM mails ORDER BY ts DESC LIMIT ?", (limit,))]

    def mail(self, message_id: str) -> Optional[dict[str, Any]]:
        row = self.db.one("SELECT * FROM mails WHERE message_id = ?", (message_id,))
        if row is None:
            return None
        data = dict(row)
        try:
            data["facts"] = json.loads(data["facts"] or "{}")
        except ValueError:
            data["facts"] = {}
        return data

    def save_mail(self, message: dict[str, Any], *, kind: str, score: int, facts: dict[str, Any], shipment_id: Optional[str],
                  state: str) -> None:
        snippet = " ".join(str(message.get("text") or "").split())[:280]
        self.db.execute(
            "INSERT INTO mails(message_id, ts, from_address, from_name, subject, account, kind, score, facts, shipment_id, state, snippet, created_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(message_id) DO UPDATE SET kind = excluded.kind, score = excluded.score, "
            "facts = excluded.facts, shipment_id = excluded.shipment_id, state = excluded.state",
            (message.get("message_id"), message.get("ts"), message.get("from_address") or "", message.get("from_name") or "",
             message.get("subject") or "", message.get("account") or "", kind, score, json.dumps(facts, ensure_ascii=False, default=str),
             shipment_id, state, snippet, self.clock()))

    def set_mail_state(self, message_id: str, state: str, shipment_id: Optional[str] = None) -> None:
        if shipment_id is None:
            self.db.execute("UPDATE mails SET state = ? WHERE message_id = ?", (state, message_id))
        else:
            self.db.execute("UPDATE mails SET state = ?, shipment_id = ? WHERE message_id = ?", (state, shipment_id, message_id))

    def mails(self, *, kind: Optional[Iterable[str]] = None, state: Optional[Iterable[str]] = None, shipment_id: str = "",
              limit: int = 100) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM mails WHERE 1=1", []
        if kind:
            kind = list(kind)
            sql += f" AND kind IN ({', '.join('?' for _ in kind)})"
            params.extend(kind)
        if state:
            state = list(state)
            sql += f" AND state IN ({', '.join('?' for _ in state)})"
            params.extend(state)
        if shipment_id:
            sql += " AND shipment_id = ?"
            params.append(shipment_id)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        out = []
        for r in self.db.query(sql, params):
            data = dict(r)
            try:
                data["facts"] = json.loads(data["facts"] or "{}")
            except ValueError:
                data["facts"] = {}
            out.append(data)
        return out

    # ------------------------------------------------------------------ notifications and runs
    def add_notification(self, *, shipment_id: Optional[str], type_: str, severity: str, title: str, body: str,
                         results: list[dict[str, Any]], dedupe: str, trip_id: Optional[str] = None) -> int:
        cur = self.db.execute("INSERT INTO notifications(ts, shipment_id, trip_id, type, severity, title, body, results, dedupe) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (self.clock(), shipment_id, trip_id, type_, severity, title, body, json.dumps(results), dedupe))
        return int(cur.lastrowid)

    def notified(self, dedupe: str) -> bool:
        return self.db.one("SELECT 1 FROM notifications WHERE dedupe = ? LIMIT 1", (dedupe,)) is not None

    def notifications(self, *, unseen: bool = False, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notifications" + (" WHERE seen = 0" if unseen else "") + " ORDER BY ts DESC LIMIT ?"
        out = []
        for r in self.db.query(sql, (max(1, min(limit, 500)),)):
            data = dict(r)
            try:
                data["results"] = json.loads(data["results"] or "[]")
            except ValueError:
                data["results"] = []
            out.append(data)
        return out

    def mark_notifications_seen(self, before: float) -> int:
        return self.db.execute("UPDATE notifications SET seen = 1 WHERE seen = 0 AND ts <= ?", (before,)).rowcount

    def add_run(self, kind: str, ref: str, ok: bool, duration_ms: int, detail: str) -> None:
        self.db.execute("INSERT INTO runs(ts, kind, ref, ok, duration_ms, detail) VALUES (?, ?, ?, ?, ?, ?)",
                        (self.clock(), kind, ref, int(ok), duration_ms, detail[:500]))
        self.db.execute("DELETE FROM runs WHERE id IN (SELECT id FROM runs ORDER BY id DESC LIMIT -1 OFFSET 2000)")

    def runs(self, kind: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query("SELECT * FROM runs WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit))
        else:
            rows = self.db.query("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        one = lambda sql, p=(): int((self.db.one(sql, p) or [0])[0] or 0)  # noqa: E731
        finals = tuple(FINAL)
        return {
            "active": one(f"SELECT COUNT(*) FROM shipments WHERE archived = 0 AND history_only = 0 AND status NOT IN ({', '.join('?' for _ in finals)})", finals),
            "delivered": one(f"SELECT COUNT(*) FROM shipments WHERE history_only = 0 AND status IN ({', '.join('?' for _ in finals)})", finals),
            "history": one("SELECT COUNT(*) FROM shipments WHERE history_only = 1"),
            "archived": one("SELECT COUNT(*) FROM shipments WHERE archived = 1"),
            "mails": one("SELECT COUNT(*) FROM mails"),
            "mails_review": one("SELECT COUNT(*) FROM mails WHERE kind = 'maybe' AND state = 'new'"),
            "unseen_notifications": one("SELECT COUNT(*) FROM notifications WHERE seen = 0"),
        }
