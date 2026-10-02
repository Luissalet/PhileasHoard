"""Segment rows: derived fields (dates, UTC times), the identity of a booking leg and what changed between two reads of it."""

from __future__ import annotations

from typing import Any, Optional

from . import airports
from .airlines import fold
from .draft import SegmentDraft
from .model import CANCELLED, FLIGHT, LODGING, TRANSPORT

# what a change notice talks about
WATCHED = ("dep_local", "arr_local", "from_code", "to_code", "from_name", "to_name", "number", "terminal", "gate", "dep_tz", "arr_tz")


def derive(row: dict[str, Any], default_tz: str = "Europe/Madrid") -> dict[str, Any]:
    """Fill ``start_date``, ``end_date``, ``dep_ts`` and ``arr_ts`` from the local times and zones."""
    row = dict(row)
    dep_tz = row.get("dep_tz") or default_tz
    arr_tz = row.get("arr_tz") or dep_tz
    row["start_date"] = (row.get("dep_local") or "")[:10]
    row["end_date"] = (row.get("arr_local") or row.get("dep_local") or "")[:10]
    row["dep_ts"] = airports.to_ts(row.get("dep_local") or "", dep_tz, row.get("dep_offset"), default_tz) if row.get("dep_local") else None
    row["arr_ts"] = airports.to_ts(row.get("arr_local") or "", arr_tz, row.get("arr_offset"), default_tz) if row.get("arr_local") else None
    return row


def row_from_draft(d: SegmentDraft, default_tz: str = "Europe/Madrid") -> dict[str, Any]:
    data = d.to_dict()
    data.pop("change", None)
    row = {k: v for k, v in data.items() if k not in ("dep_offset", "arr_offset") or v is not None}
    row["needs_review"] = bool(d.kind in TRANSPORT and not airports.has_time(d.dep_local))
    return derive(row, default_tz)


def _place(s: dict[str, Any], side: str) -> str:
    return fold(s.get(f"{side}_code") or s.get(f"{side}_name") or s.get(f"{side}_city") or "")


def same_leg(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    """Is ``incoming`` (a draft row) the same booked leg as ``existing``? A changed time still counts when the reference and the route match."""
    if existing.get("kind") != incoming.get("kind"):
        return False
    ref_e, ref_i = (existing.get("booking_ref") or "").upper(), (incoming.get("booking_ref") or "").upper()
    same_day = abs(_days(existing.get("start_date"), incoming.get("start_date"))) <= 1
    if existing["kind"] == LODGING:
        same_place = fold(existing.get("provider") or "") == fold(incoming.get("provider") or "") or (ref_e and ref_e == ref_i)
        return bool(same_place and (same_day or (ref_e and ref_e == ref_i)))
    same_route = _place(existing, "from") == _place(incoming, "from") and _place(existing, "to") == _place(incoming, "to")
    same_number = bool(existing.get("number")) and existing.get("number") == incoming.get("number")
    if ref_e and ref_i:
        if ref_e != ref_i:
            return False
        return same_number or same_route or same_day and existing["kind"] not in TRANSPORT
    return (same_number or same_route) and same_day


def _days(a: Optional[str], b: Optional[str]) -> int:
    from datetime import date
    try:
        return (date.fromisoformat(a or "") - date.fromisoformat(b or "")).days
    except ValueError:
        return 999


def find_match(existing: list[dict[str, Any]], incoming: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The one existing segment that ``incoming`` updates, or None. Exact matches win; a single same-reference, same-route leg
    with another date is a rescheduling."""
    hits = [s for s in existing if same_leg(s, incoming)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        exact = [s for s in hits if s.get("start_date") == incoming.get("start_date")]
        return exact[0] if exact else hits[0]
    ref = (incoming.get("booking_ref") or "").upper()
    if ref:
        near = [s for s in existing if s.get("kind") == incoming.get("kind") and (s.get("booking_ref") or "").upper() == ref and s.get("status") != CANCELLED
                and (_place(s, "from") == _place(incoming, "from") and _place(s, "to") == _place(incoming, "to"))]
        if len(near) == 1:
            return near[0]
    return None


def differences(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, str]]:
    """Watched fields that differ between a stored segment and a fresh read (only fields the fresh read has)."""
    out = []
    for key in WATCHED:
        a, b = (old.get(key) or ""), (new.get(key) or "")
        if b and a != b:
            out.append({"field": key, "old": str(a), "new": str(b)})
    return out


FILL_FIELDS = ("booking_ref", "carrier", "carrier_code", "number", "provider", "from_code", "from_name", "from_city", "from_country", "to_code", "to_name",
               "to_city", "to_country", "dep_tz", "arr_tz", "terminal", "gate", "seat", "coach", "travel_class", "address", "notes", "currency")
SOURCE_RANK = {"manual": 4, "paste": 3, "schema": 3, "rules": 2, "model": 1}


def merge_fields(old: dict[str, Any], new: dict[str, Any], *, authoritative: bool) -> dict[str, Any]:
    """Updates to apply to ``old`` from a fresh read. ``authoritative`` (a change mail) overrides watched fields; otherwise only
    empty fields are filled, so a hand edit is never overwritten by a repeated confirmation."""
    updates: dict[str, Any] = {}
    for key in FILL_FIELDS:
        value = new.get(key)
        if value and (authoritative and key in WATCHED or not old.get(key)):
            if old.get(key) != value:
                updates[key] = value
    if authoritative:
        for key in ("dep_local", "arr_local", "dep_offset", "arr_offset"):
            if new.get(key) not in (None, "") and new.get(key) != old.get(key):
                updates[key] = new[key]
    else:
        if not old.get("arr_local") and new.get("arr_local"):
            updates["arr_local"] = new["arr_local"]
    if new.get("price") is not None and old.get("price") is None:
        updates["price"] = new["price"]
        updates["currency"] = new.get("currency") or old.get("currency") or ""
    if not old.get("passengers") and new.get("passengers"):
        updates["passengers"] = new["passengers"]
    links = {x["url"]: x for x in (old.get("links") or [])}
    for x in new.get("links") or []:
        links.setdefault(x["url"], x)
    if len(links) != len(old.get("links") or []):
        updates["links"] = list(links.values())[:8]
    return updates
