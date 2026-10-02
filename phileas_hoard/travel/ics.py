"""iCalendar export: one VEVENT per segment, times in UTC (so every client shows the right moment), local times in the description,
and an absolute alarm at the moment online check-in opens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from . import airports, checkin
from .model import CANCELLED, FLIGHT, LODGING, kind_label

PRODID = "-//Phileas Hoard//Travel//EN"


def esc(text: Any) -> str:
    return str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def fold_line(line: str) -> list[str]:
    """RFC 5545 folding: lines of at most 75 octets, continuation lines start with one space."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return [line]
    out, current, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(current)
            current, size = ch, n
        else:
            current += ch
            size += n
    out.append(current)
    return [out[0]] + [" " + x for x in out[1:]]


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _date(value: str) -> str:
    return (value or "")[:10].replace("-", "")


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


def event(seg: dict[str, Any], now: float, lang: str, alarms: bool = True) -> list[str]:
    lines = ["BEGIN:VEVENT", f"UID:{seg['id']}@phileas-hoard", f"DTSTAMP:{_utc(now)}"]
    if seg.get("kind") == LODGING:
        end = seg.get("end_date") or seg.get("start_date")
        lines += [f"DTSTART;VALUE=DATE:{_date(seg['start_date'])}", f"DTEND;VALUE=DATE:{_date(end)}"]
    else:
        start = seg.get("dep_ts")
        if start is None:
            lines += [f"DTSTART;VALUE=DATE:{_date(seg['start_date'])}"]
        else:
            end = seg.get("arr_ts") if seg.get("arr_ts") and seg["arr_ts"] > start else start + 3600
            lines += [f"DTSTART:{_utc(start)}", f"DTEND:{_utc(end)}"]
    lines.append(f"SUMMARY:{esc(summary(seg, lang))}")
    loc = seg.get("address") or _place(seg, "from", lang)
    if loc:
        lines.append(f"LOCATION:{esc(loc)}")
    lines.append(f"DESCRIPTION:{esc(description(seg, lang))}")
    lines.append("STATUS:CANCELLED" if seg.get("status") == CANCELLED else "STATUS:CONFIRMED")
    if alarms and seg.get("kind") == FLIGHT and seg.get("status") != CANCELLED:
        w = checkin.window(seg)
        if w.get("opens_ts") and w["opens_ts"] > now:
            text = ("Abre el check-in online: " if lang == "es" else "Online check-in opens: ") + summary(seg, lang)
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(text)}", f"TRIGGER;VALUE=DATE-TIME:{_utc(w['opens_ts'])}", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def build(items: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]], *, now: float, lang: str = "es", name: str = "Viajes",
          include_cancelled: bool = False) -> str:
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(name)}"]
    for trip, segs in items:
        for seg in segs:
            if seg.get("status") == CANCELLED and not include_cancelled:
                continue
            if not seg.get("start_date"):
                continue
            ev = event(seg, now, lang)
            ev.insert(ev.index(next(x for x in ev if x.startswith("SUMMARY"))) + 1, f"CATEGORIES:{esc(trip.get('title') or '')}")
            out += ev
    out.append("END:VCALENDAR")
    folded: list[str] = []
    for line in out:
        folded += fold_line(line)
    return "\r\n".join(folded) + "\r\n"
