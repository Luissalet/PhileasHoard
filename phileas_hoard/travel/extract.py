"""schema.org reservations embedded in a mail's HTML (JSON-LD and microdata) -> segment drafts.

Handles FlightReservation, TrainReservation, BusReservation, BoatReservation, LodgingReservation, RentalCarReservation and
EventReservation, ``reservationFor`` nesting and ReservationPackage (``subReservation``). Document and ticket numbers are never read.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Iterable, Optional

from .airlines import AIRLINES, split_flight_number
from .draft import SegmentDraft
from .model import BUS, CANCELLED, CAR, CONFIRMED, EVENT, FERRY, FLIGHT, LODGING, TRAIN

LD_BLOCK = re.compile(r"<script\b[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script\s*>", re.I | re.S)
RESERVATION_KIND = {
    "FlightReservation": FLIGHT, "TrainReservation": TRAIN, "BusReservation": BUS, "BoatReservation": FERRY,
    "LodgingReservation": LODGING, "RentalCarReservation": CAR, "EventReservation": EVENT,
}
VOID = {"meta", "link", "br", "img", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


def has_markup(html: str) -> bool:
    return bool(html) and "schema.org" in html and bool(re.search(r"Reservation|ld\+json", html))


# ------------------------------------------------------------------ readers
def _json_blocks(html: str) -> list[Any]:
    out = []
    for raw in LD_BLOCK.findall(html or ""):
        raw = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", raw.strip())
        raw = re.sub(r"<!--|-->", "", raw)
        try:
            out.append(json.loads(raw))
        except ValueError:
            try:
                out.append(json.loads(re.sub(r",\s*([}\]])", r"\1", raw)))      # trailing commas are common in templates
            except ValueError:
                continue
    return out


class _Micro(HTMLParser):
    """Microdata -> the same nested dicts JSON-LD gives (``@type`` plus properties)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []        # open elements: {tag, scope, prop, text}
        self.roots: list[dict[str, Any]] = []

    def _scope(self) -> Optional[dict[str, Any]]:
        for el in reversed(self.stack):
            if el.get("scope") is not None:
                return el["scope"]
        return None

    @staticmethod
    def _put(scope: dict[str, Any], prop: str, value: Any) -> None:
        if prop in scope:
            old = scope[prop]
            scope[prop] = [*old, value] if isinstance(old, list) else [old, value]
        else:
            scope[prop] = value

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: (v if v is not None else "") for k, v in attrs}
        scope_new: Optional[dict[str, Any]] = None
        if "itemscope" in a:
            scope_new = {}
            kind = (a.get("itemtype") or "").rsplit("/", 1)[-1]
            if kind:
                scope_new["@type"] = kind
        prop = (a.get("itemprop") or "").split()
        parent = self._scope()
        value: Optional[str] = None
        if scope_new is None and prop:
            if "content" in a:
                value = a["content"]
            elif tag in ("a", "link", "area") and a.get("href"):
                value = a["href"]
            elif tag in ("img", "source") and a.get("src"):
                value = a["src"]
            elif tag == "time" and a.get("datetime"):
                value = a["datetime"]
        if scope_new is not None and parent is None:
            self.roots.append(scope_new)
        if scope_new is not None and prop and parent is not None:
            for name in prop:
                self._put(parent, name, scope_new)
        if value is not None and parent is not None:
            for name in prop:
                self._put(parent, name, value)
        if tag in VOID:
            return
        self.stack.append({"tag": tag, "scope": scope_new, "prop": prop if (scope_new is None and prop and value is None) else [], "text": [],
                           "parent": parent})

    def handle_data(self, data: str) -> None:
        for el in self.stack:
            if el["prop"]:
                el["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                el = self.stack[i]
                del self.stack[i:]
                if el["prop"] and el["parent"] is not None:
                    text = re.sub(r"\s+", " ", "".join(el["text"])).strip()
                    if text:
                        for name in el["prop"]:
                            self._put(el["parent"], name, text)
                break


def _microdata(html: str) -> list[dict[str, Any]]:
    if "itemscope" not in (html or ""):
        return []
    parser = _Micro()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 — broken markup must not stop the rules from running
        return parser.roots
    return parser.roots


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    """Every dict with a reservation ``@type`` below ``node`` (the outermost ones; ``visit`` handles their sub-reservations)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if any(t in RESERVATION_KIND for t in types if isinstance(t, str)):
            yield node
        else:
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from _walk(value)


# ------------------------------------------------------------------ values
def _s(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "text", "url", "iataCode"):
            if value.get(key):
                return _s(value[key])
        return ""
    if isinstance(value, list):
        return _s(value[0]) if value else ""
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def _time(value: Any) -> tuple[str, Optional[int]]:
    """ISO 8601 -> (``YYYY-MM-DDTHH:MM`` as written, offset minutes or None). A bare date stays a bare date."""
    text = _s(value)
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?", text)
    if not m:
        return "", None
    if m.group(2) is None:
        return m.group(1), None
    off = None
    zone = m.group(4)
    if zone:
        off = 0 if zone == "Z" else (1 if zone[0] == "+" else -1) * (int(zone[1:3]) * 60 + int(zone[-2:]))
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}", off


def _price(res: dict[str, Any]) -> tuple[Optional[float], str]:
    total = res.get("totalPrice")
    cur = _s(res.get("priceCurrency"))
    if total is None and isinstance(res.get("price"), (int, float, str)):
        total = res.get("price")
    if isinstance(total, dict):
        cur = cur or _s(total.get("priceCurrency"))
        total = total.get("value") or total.get("price")
    m = re.search(r"\d+(?:[.,]\d+)?", str(total or "").replace(" ", ""))
    if not m:
        return None, cur
    raw = m.group(0)
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw), cur
    except ValueError:
        return None, cur


def _links(res: dict[str, Any], parent: Optional[dict[str, Any]] = None) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for node in (res, parent or {}):
        for key, kind in (("checkinUrl", "checkin"), ("modifyReservationUrl", "manage"), ("url", "other"), ("cancelReservationUrl", "manage"),
                          ("ticketDownloadUrl", "ticket"), ("ticketPrintUrl", "ticket")):
            url = _s(node.get(key))
            if url.lower().startswith(("http://", "https://")) and not any(o["url"] == url for o in out):
                out.append({"kind": kind, "url": url[:1500], "label": ""})
    return out


def _passengers(res: dict[str, Any]) -> list[str]:
    under = res.get("underName")
    names = [_s(u) for u in (under if isinstance(under, list) else [under]) if u]
    return [n for n in names if n]


def _seat(res: dict[str, Any]) -> tuple[str, str, str]:
    """(seat, coach, class) from reservedTicket; the ticket number is deliberately not read."""
    ticket = res.get("reservedTicket")
    ticket = ticket[0] if isinstance(ticket, list) and ticket else ticket
    seat = coach = cls = ""
    if isinstance(ticket, dict):
        placed = ticket.get("ticketedSeat")
        placed = placed[0] if isinstance(placed, list) and placed else placed
        if isinstance(placed, dict):
            seat = _s(placed.get("seatNumber"))
            coach = _s(placed.get("seatSection"))
            cls = _s(placed.get("seatingType"))
    return seat, coach, cls


def _address(node: Any) -> str:
    if isinstance(node, dict):
        adr = node.get("address", node)
        if isinstance(adr, dict):
            parts = [_s(adr.get(k)) for k in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")]
            return ", ".join(p for p in parts if p)[:200]
        return _s(adr)[:200]
    return _s(node)[:200]


def _status(res: dict[str, Any]) -> str:
    text = _s(res.get("reservationStatus")).lower()
    return CANCELLED if "cancel" in text else CONFIRMED


def _place(node: Any) -> tuple[str, str]:
    """(IATA code or '', name) of an airport, station, stop or location node."""
    if isinstance(node, dict):
        return _s(node.get("iataCode")).upper()[:3], _s(node.get("name"))
    return "", _s(node)


# ------------------------------------------------------------------ one reservation -> draft
def _draft(res: dict[str, Any], parent: Optional[dict[str, Any]], ref_hint: str) -> Optional[SegmentDraft]:
    types = res.get("@type")
    types = types if isinstance(types, list) else [types]
    kind = next((RESERVATION_KIND[t] for t in types if t in RESERVATION_KIND), "")
    if not kind:
        return None
    thing = res.get("reservationFor")
    thing = thing[0] if isinstance(thing, list) and thing else (thing if isinstance(thing, dict) else {})
    d = SegmentDraft(kind=kind, source="schema", confidence=95)
    d.booking_ref = _s(res.get("reservationNumber") or res.get("reservationId") or (parent or {}).get("reservationNumber") or ref_hint)[:20]
    d.status = _status(res)
    d.price, d.currency = _price(res)
    if d.price is None and parent:
        d.price, d.currency = _price(parent)
    d.links = _links(res, parent)
    d.passengers = _passengers(res)
    d.seat, d.coach, d.travel_class = _seat(res)
    if kind == FLIGHT:
        airline = thing.get("airline") if isinstance(thing.get("airline"), dict) else {}
        d.carrier_code = _s(airline.get("iataCode")).upper()
        d.carrier = _s(airline.get("name")) or AIRLINES.get(d.carrier_code, "")
        raw_number = _s(thing.get("flightNumber"))
        code, num = split_flight_number(raw_number)
        if code:
            d.carrier_code = d.carrier_code or code
            d.number = code + num
        else:
            digits = re.sub(r"^0+", "", raw_number)
            d.number = (d.carrier_code + digits) if d.carrier_code and digits.isdigit() else raw_number.upper().replace(" ", "")
        d.from_code, d.from_name = _place(thing.get("departureAirport"))
        d.to_code, d.to_name = _place(thing.get("arrivalAirport"))
        d.dep_local, d.dep_offset = _time(thing.get("departureTime"))
        d.arr_local, d.arr_offset = _time(thing.get("arrivalTime"))
        d.terminal = _s(thing.get("departureTerminal"))
        d.gate = _s(thing.get("departureGate"))
    elif kind in (TRAIN, BUS, FERRY):
        provider = thing.get("provider") or {}
        d.carrier = _s(provider) or _s(thing.get("trainName") or thing.get("busName") or thing.get("boatName"))
        d.number = _s(thing.get("trainNumber") or thing.get("busNumber") or thing.get("boatNumber")).replace(" ", "").upper()
        keys = {TRAIN: ("departureStation", "arrivalStation"), BUS: ("departureBusStop", "arrivalBusStop"),
                FERRY: ("departureBoatTerminal", "arrivalBoatTerminal")}[kind]
        d.from_code, d.from_name = "", _place(thing.get(keys[0]))[1]
        d.to_code, d.to_name = "", _place(thing.get(keys[1]))[1]
        d.dep_local, d.dep_offset = _time(thing.get("departureTime"))
        d.arr_local, d.arr_offset = _time(thing.get("arrivalTime"))
        d.terminal = _s(thing.get("departurePlatform"))
    elif kind == LODGING:
        d.provider = _s(thing.get("name"))
        d.address = _address(thing)
        d.dep_local, _ = _time(res.get("checkinTime") or res.get("checkinDate"))
        d.arr_local, _ = _time(res.get("checkoutTime") or res.get("checkoutDate"))
        d.from_name = d.provider
        d.from_city = _s((thing.get("address") or {}).get("addressLocality")) if isinstance(thing.get("address"), dict) else ""
        d.from_country = _s((thing.get("address") or {}).get("addressCountry")).upper()[:2] if isinstance(thing.get("address"), dict) else ""
    elif kind == CAR:
        d.carrier = _s(res.get("provider") or thing.get("provider") or thing.get("brand"))
        d.provider = d.carrier or _s(thing.get("name"))
        d.notes = _s(thing.get("model") or thing.get("name"))
        d.from_name = _s(res.get("pickupLocation"))
        d.to_name = _s(res.get("dropoffLocation")) or d.from_name
        d.address = _address(res.get("pickupLocation"))
        d.dep_local, d.dep_offset = _time(res.get("pickupTime"))
        d.arr_local, d.arr_offset = _time(res.get("dropoffTime"))
    else:  # EVENT
        d.provider = _s(thing.get("name"))
        d.notes = d.provider
        d.from_name = _s(thing.get("location"))
        d.address = _address(thing.get("location"))
        d.dep_local, d.dep_offset = _time(thing.get("startDate"))
        d.arr_local, d.arr_offset = _time(thing.get("endDate"))
    d.evidence = [f"schema.org {kind} reservation" + (f" {d.booking_ref}" if d.booking_ref else "")]
    return d


def drafts_from_html(html: str, default_tz: str = "Europe/Madrid") -> list[SegmentDraft]:
    """Segment drafts from the reservations in a mail's HTML; empty when there is no usable markup."""
    if not has_markup(html):
        return []
    nodes: list[Any] = _json_blocks(html) + _microdata(html)
    out: list[SegmentDraft] = []
    seen: set[tuple] = set()

    def visit(res: dict[str, Any], parent: Optional[dict[str, Any]], ref_hint: str) -> None:
        d = _draft(res, parent, ref_hint)
        subs = res.get("subReservation")
        if d is not None and d.usable_fields():
            key = (d.kind, d.booking_ref, d.number, d.from_code or d.from_name, d.dep_local)
            if key not in seen:
                seen.add(key)
                out.append(d.enrich(default_tz))
        for sub in (subs if isinstance(subs, list) else [subs] if isinstance(subs, dict) else []):
            if isinstance(sub, dict):
                visit(sub, res, d.booking_ref if d else ref_hint)

    for res in _walk(nodes):
        visit(res, None, "")
    return out
