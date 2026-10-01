"""When will it arrive? An explained estimate built from every clue at hand.

Sources, strongest first (each gives a window ``from..to`` and a most likely day):

1. **Status** — delivered (done), out for delivery (today), waiting at a pickup point (now).
2. **Carrier** — the carrier's own scheduled date, corrected by how that carrier's dates turned out on your past
   parcels (if UPS was a day late on average, the window moves a day).
3. **Shop** — the date in the shop's mail ("Llega el domingo", "Se entrega: 21 ago - 24 ago").
4. **Your history** — how many delivery days similar past parcels took (same carrier and origin, else same shop,
   else same carrier), counted from when this one shipped.
5. **The shop's promise** — "al menos 48 horas … hasta 6 días laborables" from the shipping mail.
6. **Typical times** — a small table per carrier and origin, used only when nothing else is known.

Delivery days skip weekends and Spanish holidays (Amazon delivers every day; Correos and InPost on Saturday too).
The result says which sources agreed, which one decided, and whether the parcel is running late.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from . import numbers
from .bizdays import Calendar
from .model import AVAILABLE_FOR_PICKUP, DELIVERED, FINAL, LABEL_CREATED, NOT_FOUND, ORDERED, OUT_FOR_DELIVERY, RETURNED, UNKNOWN

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
      "RO", "SK", "SI", "SE"}
# Typical delivery days after shipping (min, max), by carrier and by origin zone. Deliberately wide.
TYPICAL = {
    ("amazon", "ES"): (1, 2), ("amazon", "EU"): (2, 5),
    ("correos", "ES"): (2, 4), ("correos", "EU"): (5, 10), ("correos", "WORLD"): (10, 25),
    ("ups", "ES"): (1, 3), ("ups", "EU"): (2, 4), ("ups", "GB"): (3, 6), ("ups", "WORLD"): (3, 7),
    ("dhl", "ES"): (1, 3), ("dhl", "EU"): (2, 5), ("dhl", "WORLD"): (3, 8),
    ("seur", "ES"): (1, 2), ("gls", "ES"): (1, 3), ("gls", "EU"): (2, 5), ("mrw", "ES"): (1, 2), ("nacex", "ES"): (1, 2),
    ("ctt", "ES"): (1, 3), ("inpost", "ES"): (2, 4), ("correos_express", "ES"): (1, 3), ("paack", "ES"): (1, 2),
    ("yunexpress", "WORLD"): (7, 15), ("cainiao", "WORLD"): (7, 20), ("chinapost", "WORLD"): (12, 30),
    ("fedex", "EU"): (2, 5), ("fedex", "WORLD"): (3, 7), ("tnt", "EU"): (2, 5),
    ("", "ES"): (2, 5), ("", "EU"): (3, 8), ("", "WORLD"): (7, 20),
}
MERCHANT_ORIGIN = {"Amazon": "ES", "PCSpecialist": "EU", "Google Store": "EU", "Wallapop": "ES", "Temu": "WORLD", "AliExpress": "WORLD",
                   "SHEIN": "WORLD", "Miravia": "ES", "PcComponentes": "ES", "El Corte Inglés": "ES", "MediaMarkt": "ES", "Fnac": "ES"}


def zone(country: str) -> str:
    c = (country or "").upper()
    if not c or c == "ES":
        return "ES" if c else ""
    if c in EU:
        return "EU"
    if c in ("GB", "UK"):
        return "GB"
    return "WORLD"


@dataclass
class Basis:
    source: str                 # status | carrier | shop | history | promise | typical | late
    text: str
    eta_from: str = ""
    eta_to: str = ""
    weight: int = 0             # 0-100: how much this source is trusted here
    used: bool = False


@dataclass
class Estimate:
    eta_from: str = ""
    eta_to: str = ""
    eta_likely: str = ""
    confidence: int = 0
    late: bool = False
    days_left: Optional[int] = None       # delivery days from today to the likely day
    basis: list[Basis] = field(default_factory=list)
    similar: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _d(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


MONTHS_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _h(d: Optional[date], es: bool = True) -> str:
    """A short human date for the explanations: "5 oct" / "Oct 5"."""
    if not d:
        return ""
    return f"{d.day} {MONTHS_ES[d.month - 1]}" if es else f"{MONTHS_EN[d.month - 1]} {d.day}"


def _span(a: Optional[date], b: Optional[date], es: bool = True) -> str:
    if not a:
        return ""
    if not b or b == a:
        return _h(a, es)
    if a.month == b.month:
        return f"{a.day}–{_h(b, es)}" if es else f"{MONTHS_EN[a.month - 1]} {a.day}–{b.day}"
    return f"{_h(a, es)} – {_h(b, es)}"


def start_of(shipment: dict[str, Any]) -> Optional[date]:
    """The day the parcel left: shipped, else first carrier scan, else (later) nothing."""
    return _d(shipment.get("shipped_ts")) or _d(shipment.get("first_scan_ts"))


def delivered_day(shipment: dict[str, Any]) -> Optional[date]:
    return _d(shipment.get("delivered_ts")) or (_d(shipment.get("out_for_delivery_ts")) if shipment.get("delivered_assumed") else None)


def transit_days(shipment: dict[str, Any], cal: Calendar) -> Optional[int]:
    start, end = start_of(shipment), delivered_day(shipment)
    if not start or not end or end < start:
        return None
    return cal.count(start, end, shipment.get("carrier") or "")


def similar_shipments(shipment: dict[str, Any], history: list[dict[str, Any]], cal: Calendar) -> tuple[str, list[dict[str, Any]]]:
    """Past delivered parcels most like this one, with their delivery days. Returns ``(how they were matched, rows)``."""
    rows = []
    for h in history:
        if h.get("id") == shipment.get("id"):
            continue
        days = transit_days(h, cal)
        if days is None or days > 60:
            continue
        rows.append({**{k: h.get(k) for k in ("id", "label", "item", "merchant", "carrier", "origin_country", "tracking_number")},
                     "days": days, "shipped": _iso(start_of(h)), "delivered": _iso(delivered_day(h)),
                     "carrier_eta_first": h.get("carrier_eta_first") or "", "merchant_eta_first": h.get("merchant_eta_first") or ""})
    carrier = shipment.get("carrier") or ""
    origin = zone(shipment.get("origin_country") or "")
    merchant = shipment.get("merchant") or ""
    tiers = [
        ("carrier and origin", [r for r in rows if carrier and r["carrier"] == carrier and origin and zone(r["origin_country"] or "") == origin]),
        ("same shop and carrier", [r for r in rows if merchant and r["merchant"] == merchant and r["carrier"] == carrier]),
        ("same shop", [r for r in rows if merchant and r["merchant"] == merchant]),
        ("same carrier", [r for r in rows if carrier and r["carrier"] == carrier]),
    ]
    for how, chosen in tiers:
        if len(chosen) >= 2:
            chosen.sort(key=lambda r: r["delivered"], reverse=True)
            return how, chosen[:12]
    return "", []


def _pct(values: list[int], q: float) -> int:
    values = sorted(values)
    if not values:
        return 0
    k = (len(values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return int(round(values[lo] + (values[hi] - values[lo]) * (k - lo)))


def carrier_bias(shipment: dict[str, Any], history: list[dict[str, Any]], cal: Calendar) -> tuple[float, int]:
    """Average delivery-day difference between the carrier's first promised date and the real delivery, on past parcels."""
    carrier = shipment.get("carrier") or ""
    deltas = []
    for h in history:
        if h.get("carrier") != carrier or h.get("id") == shipment.get("id"):
            continue
        promised, real = _d(h.get("carrier_eta_first")), delivered_day(h)
        if not promised or not real:
            continue
        deltas.append(cal.count(promised, real, carrier) if real > promised else -cal.count(real, promised, carrier))
    if len(deltas) < 2:
        return 0.0, len(deltas)
    return statistics.mean(deltas), len(deltas)


def estimate(shipment: dict[str, Any], history: list[dict[str, Any]], cal: Calendar, today: date, lang: str = "es") -> Estimate:
    es = lang != "en"
    est = Estimate()
    status = shipment.get("status") or UNKNOWN
    carrier = shipment.get("carrier") or ""
    how, similar = similar_shipments(shipment, history, cal)
    est.similar = similar[:6]

    if status in FINAL:
        day = _d(shipment.get("delivered_ts")) or _d(shipment.get("status_ts"))
        est.eta_from = est.eta_to = est.eta_likely = _iso(day)
        est.confidence = 100
        word = ("Entregado" if status == DELIVERED else "Devuelto") if es else ("Delivered" if status == DELIVERED else "Returned")
        est.basis.append(Basis("status", f"{word} el {_h(day, es)}".strip() if es else f"{word} {_h(day, es)}", _iso(day), _iso(day), 100, True))
        return est
    if status == OUT_FOR_DELIVERY and _d(shipment.get("out_for_delivery_ts") or shipment.get("status_ts")) == today:
        est.eta_from = est.eta_to = est.eta_likely = today.isoformat()
        est.confidence = 92
        est.days_left = 0
        est.basis.append(Basis("status", "En reparto hoy" if es else "Out for delivery today", est.eta_from, est.eta_to, 92, True))
        return est
    if status == AVAILABLE_FOR_PICKUP:
        day = _d(shipment.get("status_ts")) or today
        est.eta_from = est.eta_to = est.eta_likely = day.isoformat()
        est.confidence = 95
        est.days_left = 0
        deadline = shipment.get("pickup_deadline") or ""
        text = ("Esperándote en el punto de recogida" if es else "Waiting at the pickup point") + (
            f" (hasta el {_h(_d(deadline), es)})" if deadline and es else f" (until {_h(_d(deadline), es)})" if deadline else "")
        est.basis.append(Basis("status", text, est.eta_from, est.eta_to, 95, True))
        return est

    candidates: list[Basis] = []
    start = start_of(shipment)

    # carrier date, corrected by its track record
    c_from, c_to = _d(shipment.get("carrier_eta_from")), _d(shipment.get("carrier_eta_to")) or _d(shipment.get("carrier_eta_from"))
    if c_from:
        bias, n = carrier_bias(shipment, history, cal)
        shift = int(round(bias)) if abs(bias) >= 0.5 else 0
        f, t = (cal.add(c_from, shift, carrier), cal.add(c_to, shift, carrier)) if shift > 0 else (c_from, c_to)
        note = ""
        if shift > 0:
            note = (f"; en tus {n} envíos anteriores con este transportista llegó {bias:.1f} días más tarde de lo que dijo" if es else
                    f"; on your last {n} parcels with this carrier it came {bias:.1f} days later than it said")
        elif n >= 2:
            note = f"; suele cumplir (±{abs(bias):.1f} días en {n} envíos)" if es else f"; usually on time (±{abs(bias):.1f} days over {n} parcels)"
        cname = numbers.carrier_name(carrier) or ("el transportista" if es else "the carrier")
        text = (f"{cname} lo da para el {_span(c_from, c_to, es)}" if es else f"{cname} says {_span(c_from, c_to, es)}") + note
        candidates.append(Basis("carrier", text, _iso(f), _iso(max(t, f)), 82 if n < 2 or abs(bias) < 1.5 else 72))

    # shop date
    m_from, m_to = _d(shipment.get("merchant_eta_from")), _d(shipment.get("merchant_eta_to")) or _d(shipment.get("merchant_eta_from"))
    if m_from:
        weight = 85 if carrier == "amazon" else 68
        quote = shipment.get("merchant_eta_text") or ""
        shop = shipment.get("merchant") or ("la tienda" if es else "the shop")
        text = (f"{shop} dice {_span(m_from, m_to, es)}" + (f" («{quote}»)" if quote else "")
                if es else f"{shop} says {_span(m_from, m_to, es)}" + (f" (“{quote}”)" if quote else ""))
        candidates.append(Basis("shop", text, _iso(m_from), _iso(m_to or m_from), weight))

    # history of similar parcels
    if similar and (start or status in (ORDERED, LABEL_CREATED, NOT_FOUND)):
        days = [r["days"] for r in similar]
        base = start or cal.next_delivery_day(today, carrier)
        lo, mid, hi = _pct(days, 0.2), _pct(days, 0.5), _pct(days, 0.85)
        f, l, t = cal.add(base, max(lo, 0), carrier), cal.add(base, max(mid, 0), carrier), cal.add(base, max(hi, 0), carrier)
        weight = min(75, 35 + 8 * len(days))
        if not start:
            weight -= 15
        what = {"carrier and origin": ("mismo transportista y origen", "same carrier and origin"),
                "same shop and carrier": ("misma tienda y transportista", "same shop and carrier"),
                "same shop": ("misma tienda", "same shop"), "same carrier": ("mismo transportista", "same carrier")}[how]
        text = (f"{len(days)} envíos parecidos ({what[0]}) tardaron {lo}–{hi} días de reparto (mediana {mid})" if es else
                f"{len(days)} similar parcels ({what[1]}) took {lo}–{hi} delivery days (median {mid})")
        b = Basis("history", text, _iso(f), _iso(t), weight)
        b.likely = _iso(l)  # type: ignore[attr-defined]
        candidates.append(b)

    # the shop's promise
    pmin, pmax = shipment.get("promise_min_days"), shipment.get("promise_max_days")
    if pmin is not None or pmax is not None:
        base = _d(shipment.get("promise_base_ts")) or start or today
        business = bool(shipment.get("promise_business"))
        lo = max(1, math.ceil(float(pmin))) if pmin is not None else 1
        hi = max(lo, math.ceil(float(pmax))) if pmax is not None else lo + 2
        if business:
            f, t = cal.add(base, lo, carrier), cal.add(base, hi, carrier)
        else:
            f, t = cal.next_delivery_day(base + timedelta(days=lo), carrier), cal.next_delivery_day(base + timedelta(days=hi), carrier)
        unit = ("días laborables" if business else "días") if es else ("working days" if business else "days")
        shop = shipment.get("merchant") or ("La tienda" if es else "The shop")
        text = (f"{shop} promete {pmin:g}–{pmax:g} {unit} desde el {_h(base, es)}" if pmin is not None and pmax is not None else
                f"{shop} promete hasta {hi} {unit} desde el {_h(base, es)}") if es else (
                f"{shop} promises {pmin:g}–{pmax:g} {unit} from {_h(base, es)}" if pmin is not None and pmax is not None else
                f"{shop} promises up to {hi} {unit} from {_h(base, es)}")
        candidates.append(Basis("promise", text, _iso(f), _iso(t), 45))

    # typical times
    origin = zone(shipment.get("origin_country") or "") or MERCHANT_ORIGIN.get(shipment.get("merchant") or "", "")
    typical = TYPICAL.get((carrier, origin)) or TYPICAL.get(("", origin or "ES"))
    if typical:
        base = start or cal.next_delivery_day(today + timedelta(days=1), carrier)
        f, t = cal.add(base, typical[0], carrier), cal.add(base, typical[1], carrier)
        zones_es = {"ES": "España", "EU": "la UE", "GB": "Reino Unido", "WORLD": "fuera de Europa", "": "España"}
        zones_en = {"ES": "Spain", "EU": "the EU", "GB": "the UK", "WORLD": "outside Europe", "": "Spain"}
        cname = numbers.carrier_name(carrier) if carrier else ""
        text = (f"Lo habitual {('con ' + cname) if cname else ''} desde {zones_es.get(origin, origin)}: {typical[0]}–{typical[1]} días de reparto"
                if es else f"Typical {('with ' + cname) if cname else ''} from {zones_en.get(origin, origin)}: {typical[0]}–{typical[1]} delivery days")
        candidates.append(Basis("typical", text, _iso(f), _iso(t), 25 if start else 15))

    if not candidates:
        est.basis.append(Basis("status", "Sin datos para estimar todavía" if es else "Nothing to estimate from yet"))
        return est

    # a source whose whole window is in the past is stale unless nothing else exists
    fresh = [c for c in candidates if _d(c.eta_to) and _d(c.eta_to) >= today]
    authoritative = [c for c in candidates if c.source in ("carrier", "shop")]
    promised_passed = bool(authoritative) and all(_d(c.eta_to) and _d(c.eta_to) < today for c in authoritative)
    pool = fresh or candidates
    primary = max(pool, key=lambda c: c.weight)
    primary.used = True
    f, t = _d(primary.eta_from), _d(primary.eta_to)
    likely = _d(getattr(primary, "likely", "")) or f
    confidence = primary.weight
    # agreement: another fresh source overlapping the primary window raises confidence and may narrow it
    for c in pool:
        if c is primary:
            continue
        cf, ct = _d(c.eta_from), _d(c.eta_to)
        if cf and ct and f and t and cf <= t and ct >= f:
            c.used = True
            confidence = min(97, confidence + max(3, c.weight // 8))
            if c.source in ("carrier", "shop") and primary.source in ("history", "promise", "typical"):
                f, t, likely = max(f, cf), min(t, ct), max(f, cf)
    # running late: every window is behind us
    if (t and t < today) or promised_passed:
        est.late = True
        remaining = [r["days"] for r in similar] if similar else [1, 2]
        f = cal.next_delivery_day(today, carrier)
        t = max(t if t and t >= f else f, cal.add(f, max(1, _pct(remaining, 0.5)), carrier))
        likely = f
        confidence = max(20, confidence - 30)
        est.basis.insert(0, Basis("late", ("Va con retraso: la fecha prevista ya pasó" if es else "Running late: the expected date has passed"),
                                  _iso(f), _iso(t), confidence, True))
    if likely and f and likely < f:
        likely = f
    if likely and t and likely > t:
        likely = t
    if likely and likely < today:
        likely = cal.next_delivery_day(today, carrier)
    est.eta_from, est.eta_to, est.eta_likely = _iso(f), _iso(t), _iso(likely)
    est.confidence = int(confidence)
    est.days_left = cal.count(today, likely, carrier) if likely and likely > today else 0 if likely else None
    est.basis.extend(sorted(candidates, key=lambda c: (-int(c.used), -c.weight)))
    for b in est.basis:
        if hasattr(b, "likely"):
            delattr(b, "likely")
    return est
