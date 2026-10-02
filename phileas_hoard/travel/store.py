"""Typed access to the travel tables: trips, segments, the mails behind them, trip people and shared expenses."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Callable, Iterable, Optional

from ..db import Database
from ..errors import PhileasError

TRIP_FIELDS = ("title", "destination", "destination_country", "start_date", "end_date", "currency", "pinned", "cancelled", "history_only",
               "muted", "notes", "extra")
SEGMENT_FIELDS = (
    "trip_id", "locked", "kind", "status", "booking_ref", "carrier", "carrier_code", "number", "provider", "from_code", "from_name",
    "from_city", "from_country", "to_code", "to_name", "to_city", "to_country", "dep_local", "dep_tz", "dep_offset", "dep_ts", "arr_local",
    "arr_tz", "arr_offset", "arr_ts", "start_date", "end_date", "terminal", "gate", "seat", "coach", "travel_class", "passengers", "price",
    "currency", "links", "address", "notes", "source", "confidence", "evidence", "needs_review", "checkin_done", "checkin_done_ts", "edited",
    "history_only", "last_change_ts", "last_mail_ts", "extra")
EXPENSE_FIELDS = ("description", "amount", "currency", "rate", "payer_id", "split_mode", "split", "date", "category", "segment_id",
                  "ledger_sent_ts", "ledger_amount", "ledger_entry")
SEGMENT_JSON = {"passengers": "[]", "links": "[]", "evidence": "[]", "extra": "{}"}
TRIP_JSON = {"extra": "{}"}
EXPENSE_JSON = {"split": "{}"}
SEGMENT_BOOLS = ("locked", "needs_review", "checkin_done", "edited", "history_only")
TRIP_BOOLS = ("pinned", "cancelled", "history_only", "muted")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def _load(row: Any, json_fields: dict[str, str], bool_fields: Iterable[str] = ()) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for key, empty in json_fields.items():
        if key in data and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key] or empty)
            except ValueError:
                data[key] = json.loads(empty)
    for key in bool_fields:
        if key in data:
            data[key] = bool(data[key])
    return data


def _dump(data: dict[str, Any], json_fields: dict[str, str], bool_fields: Iterable[str]) -> dict[str, Any]:
    out = dict(data)
    for key in json_fields:
        if key in out and not isinstance(out[key], str):
            out[key] = json.dumps(out[key], ensure_ascii=False)
    for key in bool_fields:
        if key in out and isinstance(out[key], bool):
            out[key] = int(out[key])
    return out


class TravelStore:
    def __init__(self, db: Database, clock: Callable[[], float] = time.time):
        self.db = db
        self.clock = clock

    # ------------------------------------------------------------------ trips
    def create_trip(self, **fields: Any) -> dict[str, Any]:
        now = self.clock()
        tid = fields.pop("id", None) or new_id("t")
        data = _dump({k: v for k, v in fields.items() if k in TRIP_FIELDS}, TRIP_JSON, TRIP_BOOLS)
        cols = ["id", "created_ts", "updated_ts", *data]
        self.db.execute(f"INSERT INTO trips({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [tid, now, now, *data.values()])
        return self.trip(tid)

    def update_trip(self, tid: str, **fields: Any) -> dict[str, Any]:
        data = _dump({k: v for k, v in fields.items() if k in TRIP_FIELDS}, TRIP_JSON, TRIP_BOOLS)
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            self.db.execute(f"UPDATE trips SET {sets}, updated_ts = ? WHERE id = ?", [*data.values(), self.clock(), tid])
        return self.trip(tid)

    def trip(self, tid: str) -> dict[str, Any]:
        row = _load(self.db.one("SELECT * FROM trips WHERE id = ?", (tid,)), TRIP_JSON, TRIP_BOOLS)
        if row is None:
            raise PhileasError("not_found", f"No trip {tid}.", "List trips with trips_list.")
        return row

    def find_trip(self, key: str) -> dict[str, Any]:
        key = (key or "").strip()
        row = _load(self.db.one("SELECT * FROM trips WHERE id = ?", (key,)), TRIP_JSON, TRIP_BOOLS)
        if row is None and key:
            row = _load(self.db.one("SELECT * FROM trips WHERE lower(title) = lower(?) ORDER BY start_date DESC LIMIT 1", (key,)), TRIP_JSON, TRIP_BOOLS)
        if row is None:
            raise PhileasError("not_found", f"No trip matches {key!r}.", "Use the trip id (t_…) or its exact title; list them with trips_list.")
        return row

    def trips(self, *, include_history: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM trips" + ("" if include_history else " WHERE history_only = 0") + " ORDER BY start_date, created_ts"
        return [_load(r, TRIP_JSON, TRIP_BOOLS) for r in self.db.query(sql)]  # type: ignore[misc]

    def delete_trip(self, tid: str) -> None:
        self.trip(tid)
        self.db.execute("UPDATE segments SET trip_id = NULL WHERE trip_id = ?", (tid,))
        self.db.execute("UPDATE notifications SET trip_id = NULL WHERE trip_id = ?", (tid,))
        self.db.execute("DELETE FROM trips WHERE id = ?", (tid,))

    # ------------------------------------------------------------------ segments
    def create_segment(self, **fields: Any) -> dict[str, Any]:
        now = self.clock()
        sid = fields.pop("id", None) or new_id("g")
        data = _dump({k: v for k, v in fields.items() if k in SEGMENT_FIELDS}, SEGMENT_JSON, SEGMENT_BOOLS)
        cols = ["id", "created_ts", "updated_ts", *data]
        self.db.execute(f"INSERT INTO segments({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [sid, now, now, *data.values()])
        return self.segment(sid)

    def update_segment(self, sid: str, **fields: Any) -> dict[str, Any]:
        data = _dump({k: v for k, v in fields.items() if k in SEGMENT_FIELDS}, SEGMENT_JSON, SEGMENT_BOOLS)
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            self.db.execute(f"UPDATE segments SET {sets}, updated_ts = ? WHERE id = ?", [*data.values(), self.clock(), sid])
        return self.segment(sid)

    def segment(self, sid: str) -> dict[str, Any]:
        row = _load(self.db.one("SELECT * FROM segments WHERE id = ?", (sid,)), SEGMENT_JSON, SEGMENT_BOOLS)
        if row is None:
            raise PhileasError("not_found", f"No segment {sid}.", "List a trip's segments with trip_get.")
        return row

    def segments(self, *, trip_id: Optional[str] = None, unassigned: bool = False, include_cancelled: bool = True,
                 ref: str = "", kind: str = "", limit: int = 2000) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM segments WHERE 1=1", []
        if trip_id:
            sql += " AND trip_id = ?"
            params.append(trip_id)
        if unassigned:
            sql += " AND trip_id IS NULL"
        if not include_cancelled:
            sql += " AND status != 'cancelled'"
        if ref:
            sql += " AND booking_ref = ?"
            params.append(ref)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY COALESCE(dep_ts, 0), start_date, created_ts LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        return [_load(r, SEGMENT_JSON, SEGMENT_BOOLS) for r in self.db.query(sql, params)]  # type: ignore[misc]

    def delete_segment(self, sid: str) -> None:
        self.segment(sid)
        self.db.execute("DELETE FROM segments WHERE id = ?", (sid,))

    def link_mail(self, segment_id: str, message_id: str, ts: Optional[float], role: str = "confirmation") -> None:
        self.db.execute("INSERT OR REPLACE INTO segment_mails(segment_id, message_id, ts, role) VALUES (?, ?, ?, ?)", (segment_id, message_id, ts, role))

    def mails_of_segment(self, segment_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT sm.message_id, sm.ts, sm.role, m.subject, m.from_address, m.snippet FROM segment_mails sm "
                             "LEFT JOIN mails m ON m.message_id = sm.message_id WHERE sm.segment_id = ? ORDER BY sm.ts", (segment_id,))
        return [dict(r) for r in rows]

    def segments_of_mail(self, message_id: str) -> list[str]:
        return [r["segment_id"] for r in self.db.query("SELECT segment_id FROM segment_mails WHERE message_id = ?", (message_id,))]

    # ------------------------------------------------------------------ people
    def people(self, trip_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trip_people WHERE trip_id = ? ORDER BY position, rowid", (trip_id,))
        return [{**dict(r), "is_me": bool(r["is_me"])} for r in rows]

    def add_person(self, trip_id: str, name: str, *, is_me: bool = False) -> dict[str, Any]:
        pid = new_id("p")
        pos = int((self.db.one("SELECT COALESCE(MAX(position), -1) + 1 AS n FROM trip_people WHERE trip_id = ?", (trip_id,)) or [0])[0])
        self.db.execute("INSERT INTO trip_people(id, trip_id, name, is_me, position) VALUES (?, ?, ?, ?, ?)", (pid, trip_id, name, int(is_me), pos))
        return next(p for p in self.people(trip_id) if p["id"] == pid)

    def update_person(self, pid: str, **fields: Any) -> None:
        for key in ("name", "is_me"):
            if key in fields:
                self.db.execute(f"UPDATE trip_people SET {key} = ? WHERE id = ?", (int(fields[key]) if key == "is_me" else fields[key], pid))

    def delete_person(self, pid: str) -> None:
        self.db.execute("DELETE FROM trip_people WHERE id = ?", (pid,))

    # ------------------------------------------------------------------ expenses
    def create_expense(self, trip_id: str, **fields: Any) -> dict[str, Any]:
        now = self.clock()
        eid = new_id("x")
        data = _dump({k: v for k, v in fields.items() if k in EXPENSE_FIELDS}, EXPENSE_JSON, ())
        cols = ["id", "trip_id", "created_ts", "updated_ts", *data]
        self.db.execute(f"INSERT INTO trip_expenses({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [eid, trip_id, now, now, *data.values()])
        return self.expense(eid)

    def update_expense(self, eid: str, **fields: Any) -> dict[str, Any]:
        data = _dump({k: v for k, v in fields.items() if k in EXPENSE_FIELDS}, EXPENSE_JSON, ())
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            self.db.execute(f"UPDATE trip_expenses SET {sets}, updated_ts = ? WHERE id = ?", [*data.values(), self.clock(), eid])
        return self.expense(eid)

    def expense(self, eid: str) -> dict[str, Any]:
        row = _load(self.db.one("SELECT * FROM trip_expenses WHERE id = ?", (eid,)), EXPENSE_JSON)
        if row is None:
            raise PhileasError("not_found", f"No expense {eid}.", "List a trip's expenses with trip_expenses.")
        return row

    def expenses(self, trip_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM trip_expenses WHERE trip_id = ? ORDER BY date, created_ts", (trip_id,))
        return [_load(r, EXPENSE_JSON) for r in rows]  # type: ignore[misc]

    def delete_expense(self, eid: str) -> None:
        self.expense(eid)
        self.db.execute("DELETE FROM trip_expenses WHERE id = ?", (eid,))

    # ------------------------------------------------------------------ misc
    def counts(self) -> dict[str, int]:
        one = lambda sql, p=(): int((self.db.one(sql, p) or [0])[0] or 0)  # noqa: E731
        return {"trips": one("SELECT COUNT(*) FROM trips WHERE history_only = 0 AND cancelled = 0"),
                "segments": one("SELECT COUNT(*) FROM segments WHERE status != 'cancelled'"),
                "trips_total": one("SELECT COUNT(*) FROM trips")}
