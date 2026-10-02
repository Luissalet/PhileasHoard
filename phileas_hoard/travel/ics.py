"""iCalendar export: one event per segment, times in UTC (so every client shows the right moment), local times in the description,
and an absolute alarm at the moment online check-in opens. The file itself (escaping, folding, UIDs, alarms) is written by
``hoard_link.ics.build_ics``; this module only turns segments into events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ..hoard_link.ics import build_ics
from . import airports, checkin
from .model import CANCELLED, FLIGHT, LODGING, kind_label

PRODID = "-//Phileas Hoard//Travel//EN"


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def _place(seg: dict[str, Any], side: str, lang: str) -> str:
    city = airports.city_name(seg.get(f"{side}_city") or "", lang)
    code = seg.get(f"{side}_code") or ""
    name = seg.get(f"{side}_name") or ""
    if code:
        return f"{city} ({code})" if city else code
    return name or city


def summary(seg: dict[str, Any], lang: str) -> str:
    kind = seg.get("kind")
    if kind == LODGING:
        return (seg.get("provider") or kind_label(LODGING, lang))[:80]
    if kind == "car":
        return f"{kind_label('car', lang)} {seg.get('provider') or ''}".strip()
    route = f"{_place(seg, 'from', lang)} → {_place(seg, 'to', lang)}"
    head = seg.get("number") or seg.get("carrier") or kind_label(kind, lang)
    return f"{head} {route}".strip()


def description(seg: dict[str, Any], lang: str) -> str:
    es = lang == "es"
    lines = []
    if seg.get("booking_ref"):
        lines.append(f"{'Localizador' if es else 'Booking reference'}: {seg['booking_ref']}")
    if seg.get("dep_local"):
        lines.append(f"{'Salida' if es else 'Departure'}: {seg['dep_local'].replace('T', ' ')} ({seg.get('dep_tz') or ''})")
    if seg.get("arr_local"):
        lines.append(f"{'Llegada' if es else 'Arrival'}: {seg['arr_local'].replace('T', ' ')} ({seg.get('arr_tz') or ''})")
    for key, es_l, en_l in (("terminal", "Terminal", "Terminal"), ("gate", "Puerta", "Gate"), ("coach", "Coche", "Coach"), ("seat", "Asiento", "Seat"),
                            ("travel_class", "Clase", "Class")):
        if seg.get(key):
            lines.append(f"{es_l if es else en_l}: {seg[key]}")
    if seg.get("address"):
        lines.append(f"{'Dirección' if es else 'Address'}: {seg['address']}")
    for link in seg.get("links") or []:
        lines.append(f"{link.get('label') or link.get('kind')}: {link.get('url')}")
    return "\n".join(lines)


def event(seg: dict[str, Any], now: float, lang: str, alarms: bool = True) -> dict[str, Any]:
    """The segment as a ``build_ics`` event (a booking made of dates only is an all-day event)."""
    ev: dict[str, Any] = {"uid": f"{seg['id']}@phileas-hoard", "title": summary(seg, lang), "description": description(seg, lang),
                          "status": "cancelled" if seg.get("status") == CANCELLED else "confirmed"}
    if seg.get("kind") == LODGING:
        # a stay runs until the check-out day: the end is exclusive, like DTEND of an all-day event
        ev.update(start=seg["start_date"], end=seg.get("end_date") or seg["start_date"], end_exclusive=True, all_day=True)
    else:
        start = seg.get("dep_ts")
        if start is None:
            ev.update(start=seg["start_date"], all_day=True)
        else:
            end = seg.get("arr_ts") if seg.get("arr_ts") and seg["arr_ts"] > start else start + 3600
            ev.update(start=_utc(start), end=_utc(end))
    loc = seg.get("address") or _place(seg, "from", lang)
    if loc:
        ev["location"] = loc
    if alarms and seg.get("kind") == FLIGHT and seg.get("status") != CANCELLED:
        w = checkin.window(seg)
        if w.get("opens_ts") and w["opens_ts"] > now:
            text = ("Abre el check-in online: " if lang == "es" else "Online check-in opens: ") + summary(seg, lang)
            ev["alarms"] = [{"at": _utc(w["opens_ts"]).strftime("%Y-%m-%dT%H:%M:%SZ"), "text": text}]
    return ev


def build(items: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]], *, now: float, lang: str = "es", name: str = "Viajes",
          include_cancelled: bool = False) -> str:
    events = []
    for trip, segs in items:
        for seg in segs:
            if seg.get("status") == CANCELLED and not include_cancelled:
                continue
            if not seg.get("start_date"):
                continue
            ev = event(seg, now, lang)
            if trip.get("title"):
                ev["categories"] = [trip["title"]]
            events.append(ev)
    return build_ics(events, name=name, prodid=PRODID, now=_utc(now))
