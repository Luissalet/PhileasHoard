"""Airline online check-in windows.

The table is what the airlines publish, as checked on 2026-10-02 (see ``SOURCES``). It is a reminder aid, not a promise: airlines
change these rules, so the user-facing text always says where it comes from. An airline that is not in the table is "unknown":
the reminder is 24 h before the flight and says to check with the airline when check-in opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from . import airports
from .model import FLIGHT

CHECKED = "2026-10-02"
SCHENGEN = airports.SCHENGEN
UNKNOWN_OPENS_H = 24


@dataclass(frozen=True)
class Rule:
    airline: str
    opens_h: float                         # hours before departure
    closes_min: Optional[int]              # minutes before departure (None = not published for that case)
    source: str
    note_es: str
    note_en: str


RULES: dict[str, Rule] = {
    "FR": Rule("Ryanair", 24, 120, "airhelp.com (Ryanair)",
               "Abre 24 h antes (hasta 60 días antes con asiento de pago); cierra 2 h antes.",
               "Opens 24 h before (up to 60 days before with a paid seat); closes 2 h before."),
    "U2": Rule("easyJet", 30 * 24, 120, "airhelp.es (easyJet)",
               "Abre 30 días antes; cierra 2 h antes.", "Opens 30 days before; closes 2 h before."),
    "VY": Rule("Vueling", 24, 50, "help.vueling.com (Check-in online)",
               "Abre 24 h antes en todas las tarifas (antes en algunas: de inmediato con Fly, Fly Grande y Fly Pro, 7 días para socios Club, "
               "15 días con Fly Light y asiento); cierra 50 min antes en vuelos Schengen y antes en el resto.",
               "Opens 24 h before on every fare (earlier on some: at once with Fly, Fly Grande and Fly Pro, 7 days for Club members, 15 days with "
               "Fly Light and a seat); closes 50 min before on Schengen flights and earlier on the rest."),
    "IB": Rule("Iberia", 24, 60, "airhelp.es (Iberia)",
               "Abre 24 h antes sin asiento (desde la compra con asiento reservado); cierra 1 h antes.",
               "Opens 24 h before without a seat (from purchase with a reserved seat); closes 1 h before."),
    "UX": Rule("Air Europa", 48, 60, "airhelp.es (Air Europa)",
               "Abre 48 h antes (24 h en vuelos a EE. UU.); cierra entre 45 y 60 min antes.",
               "Opens 48 h before (24 h on flights to the US); closes 45 to 60 min before."),
}
SOURCES = {code: r.source for code, r in RULES.items()}
UNKNOWN_NOTE = {"es": "Comprueba en la aerolínea cuándo abre el check-in.", "en": "Check with the airline when check-in opens."}


def table() -> list[dict[str, Any]]:
    return [{"code": code, "airline": r.airline, "opens_h": r.opens_h, "closes_min": r.closes_min, "source": r.source, "checked": CHECKED,
             "note_es": r.note_es, "note_en": r.note_en} for code, r in RULES.items()]


def window(seg: dict[str, Any]) -> dict[str, Any]:
    """Check-in window of one flight segment: ``{known, opens_ts, closes_ts, ...}``; non-flights give ``{"applies": False}``."""
    if seg.get("kind") != FLIGHT:
        return {"applies": False}
    dep = seg.get("dep_ts")
    if dep is None or not airports.has_time(seg.get("dep_local") or ""):
        return {"applies": True, "known": False, "opens_ts": None, "closes_ts": None, "airline": seg.get("carrier") or "", "note_es": "Sin hora de salida.",
                "note_en": "No departure time.", "source": "", "checked": CHECKED}
    code = (seg.get("carrier_code") or (seg.get("number") or "")[:2]).upper()
    rule = RULES.get(code)
    if rule is None:
        return {"applies": True, "known": False, "airline": seg.get("carrier") or code, "opens_ts": dep - UNKNOWN_OPENS_H * 3600, "closes_ts": None,
                "opens_h": UNKNOWN_OPENS_H, "closes_min": None, "source": "", "checked": CHECKED, "note_es": UNKNOWN_NOTE["es"], "note_en": UNKNOWN_NOTE["en"]}
    opens_h = rule.opens_h
    closes_min = rule.closes_min
    if code == "UX" and (seg.get("to_country") or "").upper() == "US":
        opens_h = 24
    if code == "VY":
        both = (seg.get("from_country") or "").upper() in SCHENGEN and (seg.get("to_country") or "").upper() in SCHENGEN
        if not both:
            closes_min = None          # Vueling closes earlier outside Schengen and does not publish a single figure
    return {"applies": True, "known": True, "airline": rule.airline, "opens_ts": dep - opens_h * 3600,
            "closes_ts": dep - closes_min * 60 if closes_min else None, "opens_h": opens_h, "closes_min": closes_min, "source": rule.source,
            "checked": CHECKED, "note_es": rule.note_es, "note_en": rule.note_en}


def state(seg: dict[str, Any], now: float) -> dict[str, Any]:
    """``window`` plus where "now" stands: ``done``, ``not_open``, ``open``, ``closed`` or ``unknown``."""
    w = window(seg)
    if not w.get("applies"):
        return w
    dep = seg.get("dep_ts")
    if seg.get("checkin_done"):
        w["state"] = "done"
    elif seg.get("status") == "cancelled" or dep is None or now >= dep:
        w["state"] = "closed"
    elif w.get("closes_ts") and now >= w["closes_ts"]:
        w["state"] = "closed"
    elif w.get("opens_ts") is not None and now >= w["opens_ts"]:
        w["state"] = "open" if w.get("known") else "unknown_open"
    else:
        w["state"] = "not_open"
    return w
