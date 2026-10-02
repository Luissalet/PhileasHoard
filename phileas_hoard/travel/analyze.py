"""Decide whether a mail is a travel booking and read it: schema.org first, then the sender rules.

``analyze_travel`` never calls the model: it tells the engine whether the mail is a travel candidate and what could be read
deterministically (``source`` = ``schema`` or ``rules``). A candidate with no usable segment is what the model pass is for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from . import extract, rules
from .scan import clean_lines, find_dates, find_times, tokenize
from .draft import SegmentDraft
from .model import CANCELLED, CONFIRMED

BOOKING_CUE = re.compile(r"reserva|booking|billete|ticket|confirmaci[oó]n|confirmation|confirmed|confirmad|itinerar|localizador|check-?in|boarding|e-?ticket|"
                         r"tarjeta de embarque|cancelaci[oó]n|cancell?ed|cancelad|cambio de (?:horario|vuelo)|schedule change|your (?:trip|flight|stay)|tu (?:viaje|vuelo|estancia)", re.I)
PROMO_CUE = re.compile(r"oferta|descuento|chollo|newsletter|bolet[ií]n|suscr[ií]b|promo|rebajas|black friday|ahorra|desde \d+\s*(?:€|euros?)|"
                       r"\bsale\b|deals?\b|encuesta|valora tu|opini[oó]n|survey|rate your|puntos|millas|miles|loyalty|club\b|"
                       r"premio|[uú]ltima oportunidad|finaliza hoy|no te lo pierdas|no esperes|reembolso|ventajas|desbloqueado|"
                       r"preferencias de comunicaci[oó]n|communication preferences|tell us|cu[eé]ntanos|d[eé]janos tu|hace tiempo desde|"
                       r"vive m[aá]s|d[eé]jate llevar|vuela a\b|escapad|genius|recompensa|sorteo|gana\b|cup[oó]n|voucher", re.I)
# a notice for every passenger of an airline, not about one booking
NOTICE_CUE = re.compile(r"para todos los (?:pasajeros|viajeros|clientes)|todos los pasajeros|all passengers|important (?:update|notice|information)|"
                        r"actualizaci[oó]n importante|aviso importante|informaci[oó]n importante", re.I)
# tickets for a show, a film or a match: travel only when they come with a place away from home (schema.org) or the user adds them to a trip
EVENT_CUE = re.compile(r"\b(?:entradas?|cines?|cinesa|yelmo|sesi[oó]n|butacas?|concierto|teatro|espect[aá]culo|festival|partido|ticketmaster|eventbrite|"
                       r"productos de bar|tickets? (?:for|to) (?:the )?(?:show|concert|match|film|movie))\b", re.I)
FLIGHT_NO = re.compile(r"\b[A-Z0-9]{2}\s?\d{2,4}\b")


def _has_date_and_time(text: str, ref: date) -> bool:
    lines = rules.clean_lines(text)
    return any(find_dates(line, ref) for line in lines) and any(find_times(line) for line in lines)


@dataclass
class TravelFacts:
    score: int = 0
    candidate: bool = False
    source: str = "none"                       # schema | rules | none
    sender: str = ""
    change: str = "new"
    ref: str = ""
    kinds: list[str] = field(default_factory=list)
    drafts: list[SegmentDraft] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def readable(self) -> bool:
        return bool(self.drafts)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "candidate": self.candidate, "source": self.source, "sender": self.sender, "change": self.change, "ref": self.ref,
                "kinds": self.kinds, "reasons": self.reasons, "drafts": [d.to_dict() for d in self.drafts]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TravelFacts":
        out = cls(**{k: v for k, v in data.items() if k in ("score", "candidate", "source", "sender", "change", "ref", "kinds", "reasons")})
        out.drafts = [SegmentDraft.from_dict(d) for d in data.get("drafts") or []]
        return out


def itinerary(r: rules.RulesResult, subject: str, text: str, ref: date) -> bool:
    """Something concrete to travel: a leg the rules read, a dated departure or check-in with a time, or a route between two places."""
    if r.drafts or _has_date_and_time(text, ref):
        return True
    return any(tok["t"] in ("route", "place") for tok in tokenize(clean_lines(subject + "\n" + text), ref, places=True))


def _ref_date(message: dict[str, Any]) -> date:
    ts = message.get("ts")
    try:
        return datetime.fromtimestamp(float(ts)).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return date.today()


def analyze_travel(message: dict[str, Any], *, default_tz: str = "Europe/Madrid", ref: Optional[date] = None) -> TravelFacts:
    subject = str(message.get("subject") or "")
    text = str(message.get("text") or "")
    html = str(message.get("html") or "")
    ref = ref or _ref_date(message)
    facts = TravelFacts()
    r = rules.read(message, ref)
    facts.sender, facts.change = r.sender, r.change
    facts.ref = r.ref
    facts.kinds = list(r.kinds)
    schema = extract.drafts_from_html(html, default_tz) if extract.has_markup(html) else []
    schema = [d for d in schema if d.usable()]

    score = 0
    if schema:
        score += 80
        facts.reasons.append("schema.org reservation")
    sender = rules.sender_of(str(message.get("from_address") or ""), str(message.get("from_name") or ""))
    if sender:
        score += 45
        facts.reasons.append(f"sender {sender[0]}")
    head = subject + "\n" + "\n".join(rules.clean_lines(text)[:12])
    if BOOKING_CUE.search(head):
        score += 25
        facts.reasons.append("booking words")
    if r.ref:
        score += 15
        facts.reasons.append("booking reference")
    if r.drafts:
        score += 20
        facts.reasons.append("route and date")
    elif r.kinds and _has_date_and_time(text, ref):
        score += 25                                             # travel words with a date and a time, but no route the rules could read
        facts.reasons.append("travel words, date and time")
    promo = bool(PROMO_CUE.search(subject) or PROMO_CUE.search("\n".join(rules.clean_lines(text)[:6])))
    if promo and not r.ref and not schema:
        score -= 50
        facts.reasons.append("looks promotional")
    facts.score = max(0, min(score, 100))
    # Only real booking evidence makes a mail travel: reservation markup, or a booking reference together with something concrete to
    # travel. A sender, booking words or promotions never decide on their own, so marketing from travel companies stays noise.
    if schema:
        facts.candidate = True
    elif r.ref and (itinerary(r, subject, text, ref) or r.change in ("cancel", "change")):
        facts.candidate = True
        facts.reasons.append("reference and itinerary")
    elif sender and r.drafts and not promo and BOOKING_CUE.search(head):
        facts.candidate = True                                  # a travel company's mail whose legs were read with dates and times
        facts.reasons.append("sender and dated legs")
    else:
        facts.candidate = False
        facts.reasons.append("no booking evidence")
    if facts.candidate and not schema and not sender and not (set(r.kinds) & {"flight", "train", "bus", "ferry", "car"}):
        if EVENT_CUE.search(head + "\n" + "\n".join(rules.clean_lines(text)[:25])):
            facts.candidate = False
            facts.reasons.append("event ticket without a trip")

    if schema:
        for d in schema:
            if not d.booking_ref:
                d.booking_ref = r.ref
            if not d.links:
                d.links = rules.find_links(message.get("links") or [])
            if r.change == "cancel":
                d.status = CANCELLED
            d.change = "cancel" if d.status == CANCELLED else r.change
        facts.drafts, facts.source = schema, "schema"
    elif r.drafts and facts.candidate:
        facts.drafts, facts.source = r.drafts, "rules"
    if facts.drafts:
        facts.kinds = sorted({d.kind for d in facts.drafts})
    return facts
