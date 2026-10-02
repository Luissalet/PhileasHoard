"""Texts of the travel notifications (Spanish and English) and small formatters shared with the views."""

from __future__ import annotations

from typing import Any

from . import airports
from .model import (FLIGHT, LODGING, N_CHECKIN_CLOSING, N_CHECKIN_OPEN, N_DEPARTURE, N_DOC_PROBLEM, N_LODGING_DAY, N_SEGMENT_CANCELLED,
                    N_SEGMENT_CHANGED, N_TRIP_NEW, N_TRIP_TOMORROW, kind_label)
from .trips import date_range

SEVERITY = {N_TRIP_NEW: "low", N_TRIP_TOMORROW: "medium", N_CHECKIN_OPEN: "high", N_CHECKIN_CLOSING: "high", N_LODGING_DAY: "medium",
            N_DEPARTURE: "high", N_SEGMENT_CHANGED: "high", N_SEGMENT_CANCELLED: "high", N_DOC_PROBLEM: "high"}
TAGS = {N_TRIP_NEW: "airplane", N_TRIP_TOMORROW: "luggage", N_CHECKIN_OPEN: "ticket", N_CHECKIN_CLOSING: "alarm_clock", N_LODGING_DAY: "hotel",
        N_DEPARTURE: "airplane_departure", N_SEGMENT_CHANGED: "warning", N_SEGMENT_CANCELLED: "x", N_DOC_PROBLEM: "passport_control"}


def hhmm(local: str) -> str:
    return local[11:16] if airports.has_time(local or "") else ""


def place(seg: dict[str, Any], side: str, lang: str = "es") -> str:
    code = seg.get(f"{side}_code") or ""
    city = airports.city_name(seg.get(f"{side}_city") or "", lang)
    name = seg.get(f"{side}_name") or ""
    if code:
        return code
    return name or city


def label(seg: dict[str, Any], lang: str = "es") -> str:
    """"IB3166 MAD → LIS", "Tren AVE3071 Madrid → Barcelona", "Hotel Alfama Vista"."""
    if seg.get("kind") == LODGING:
        return seg.get("provider") or kind_label(LODGING, lang)
    if seg.get("kind") == "car":
        return f"{kind_label('car', lang)} {seg.get('provider') or ''}".strip()
    if seg.get("kind") == "event":
        return seg.get("provider") or (seg.get("notes") or "").split("\n")[0][:60] or kind_label("event", lang)
    head = seg.get("number") or seg.get("carrier") or kind_label(seg.get("kind") or "", lang)
    return f"{head} {place(seg, 'from', lang)} → {place(seg, 'to', lang)}".strip()


def day_text(local: str, lang: str = "es") -> str:
    d = (local or "")[:10]
    return date_range(d, d, lang)[:-5] if d else ""      # "12 nov" (no year)


def when(seg: dict[str, Any], lang: str = "es") -> str:
    t = hhmm(seg.get("dep_local") or "")
    day = day_text(seg.get("dep_local") or "", lang)
    if not t:
        return day
    return f"{day} {'a las' if lang == 'es' else 'at'} {t}"


def hours_text(seconds: float, lang: str = "es") -> str:
    minutes = max(0, int(round(seconds / 60)))
    if minutes < 90:
        return f"{minutes} min"
    hours = round(minutes / 60)
    return f"{hours} h"


def compose(kind: str, lang: str, *, trip: dict[str, Any] | None = None, seg: dict[str, Any] | None = None, **kw: Any) -> tuple[str, str]:
    es = lang == "es"
    trip = trip or {}
    seg = seg or {}
    name = label(seg, lang) if seg else ""
    title_trip = trip.get("title") or ""
    if kind == N_TRIP_NEW:
        n = kw.get("count", 1)
        return ((f"Nuevo viaje: {title_trip}" if es else f"New trip: {title_trip}"),
                (f"{n} {'segmento' if n == 1 else 'segmentos'}: {kw.get('first', '')}" if es else f"{n} segment{'s' if n != 1 else ''}: {kw.get('first', '')}"))
    if kind == N_TRIP_TOMORROW:
        return ((f"Mañana empieza tu viaje: {title_trip}" if es else f"Your trip starts tomorrow: {title_trip}"),
                (f"{name} · {when(seg, lang)}" if name else ""))
    if kind == N_CHECKIN_OPEN:
        if kw.get("known", True):
            return ((f"Ya puedes hacer el check-in: {name}" if es else f"Check-in is open: {name}"),
                    (f"Sale el {when(seg, lang)}. " if es else f"Departs {when(seg, lang)}. ") + str(kw.get("note") or ""))
        return ((f"Comprueba el check-in: {name}" if es else f"Check your check-in: {name}"),
                (f"Sale el {when(seg, lang)}. " if es else f"Departs {when(seg, lang)}. ") + str(kw.get("note") or ""))
    if kind == N_CHECKIN_CLOSING:
        return ((f"El check-in cierra en {kw.get('left', '')}: {name}" if es else f"Check-in closes in {kw.get('left', '')}: {name}"),
                ("Aún no está marcado como hecho." if es else "It is not marked as done yet."))
    if kind == N_LODGING_DAY:
        t = hhmm(seg.get("dep_local") or "")
        return ((f"Hoy es el check-in en {name}" if es else f"Check-in today at {name}"),
                " · ".join(x for x in ((f"desde las {t}" if es else f"from {t}") if t else "", seg.get("address") or "") if x))
    if kind == N_DEPARTURE:
        extra = " · ".join(x for x in (f"Terminal {seg['terminal']}" if seg.get("terminal") else "", (f"puerta {seg['gate']}" if es else f"gate {seg['gate']}") if seg.get("gate") else "",
                                       (f"coche {seg['coach']}" if es else f"coach {seg['coach']}") if seg.get("coach") else "",
                                       (f"asiento {seg['seat']}" if es else f"seat {seg['seat']}") if seg.get("seat") else "") if x)
        return ((f"Sales en {kw.get('left', '')}: {name}" if es else f"Leaving in {kw.get('left', '')}: {name}"),
                " · ".join(x for x in (hhmm(seg.get("dep_local") or ""), extra) if x))
    if kind == N_SEGMENT_CHANGED:
        parts = []
        names = {"dep_local": ("Salida", "Departure"), "arr_local": ("Llegada", "Arrival"), "number": ("Número", "Number"), "terminal": ("Terminal", "Terminal"),
                 "gate": ("Puerta", "Gate"), "from_code": ("Origen", "From"), "to_code": ("Destino", "To"), "from_name": ("Origen", "From"), "to_name": ("Destino", "To")}
        for diff in kw.get("diffs", [])[:4]:
            label_ = names.get(diff["field"], (diff["field"], diff["field"]))[0 if es else 1]
            old, new = diff["old"], diff["new"]
            if diff["field"] in ("dep_local", "arr_local"):
                old, new = old.replace("T", " "), new.replace("T", " ")
            parts.append(f"{label_}: {old or '—'} → {new}")
        return ((f"Cambio en tu reserva: {name}" if es else f"Your booking changed: {name}"), " · ".join(parts))
    if kind == N_SEGMENT_CANCELLED:
        return ((f"Cancelado: {name}" if es else f"Cancelled: {name}"), (f"{title_trip}" if title_trip else ""))
    if kind == N_DOC_PROBLEM:
        d = kw.get("problem") or {}
        if d.get("type") == "missing_passport":
            return ((f"Falta el pasaporte para: {title_trip}" if es else f"No passport on file for: {title_trip}"),
                    ("El viaje sale de Schengen y no hay pasaporte en Kafka." if es else "The trip leaves Schengen and Kafka has no passport."))
        return ((f"Documento caducado antes de volver: {title_trip}" if es else f"Document expires before you return: {title_trip}"),
                (f"{d.get('document') or ''} caduca el {d.get('expiry')}; vuelves el {kw.get('return_date')}." if es
                 else f"{d.get('document') or ''} expires on {d.get('expiry')}; you return on {kw.get('return_date')}."))
    return (kind, "")
