"""Sender rules for the common travel mail in Spain and Europe: airlines, trains, buses, ferries, hotels, rentals and agencies.

The mail text is read in reading order (``scan.tokenize``): dates, times, airport codes, flight numbers and labels such as
"Salida", "Llegada", "Check-in", "Recogida". A leg is closed when a field that is already filled shows up again, so layouts
that list one leg after another (lines, cards, one-line rows) all work. Rules are best effort: what they cannot read goes to
the model pass or to the review list, never to the trips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .. import numbers as _numbers
from ..hoard_link.money import currency_of, parse_amount
from . import airports
from .airlines import AIRLINES, code_for_name, fold
from .draft import SegmentDraft
from .model import BUS, CANCELLED, CAR, CONFIRMED, EVENT, FERRY, FLIGHT, LODGING, TRAIN
from .scan import clean_lines, find_dates, find_times, tokenize

# domain suffix -> (display name, airline code or '', default kind or '' for "decide from the content")
SENDERS: list[tuple[str, str, str, str]] = [
    ("iberia.com", "Iberia", "IB", FLIGHT), ("iberiaexpress.com", "Iberia Express", "I2", FLIGHT), ("vueling.com", "Vueling", "VY", FLIGHT),
    ("aireuropa.com", "Air Europa", "UX", FLIGHT), ("ryanair.com", "Ryanair", "FR", FLIGHT), ("easyjet.com", "easyJet", "U2", FLIGHT),
    ("volotea.com", "Volotea", "V7", FLIGHT), ("bintercanarias.com", "Binter Canarias", "NT", FLIGHT), ("flybinter.com", "Binter Canarias", "NT", FLIGHT),
    ("flytap.com", "TAP Air Portugal", "TP", FLIGHT), ("tap.pt", "TAP Air Portugal", "TP", FLIGHT), ("lufthansa.com", "Lufthansa", "LH", FLIGHT),
    ("britishairways.com", "British Airways", "BA", FLIGHT), ("ba.com", "British Airways", "BA", FLIGHT), ("airfrance.com", "Air France", "AF", FLIGHT),
    ("airfrance.fr", "Air France", "AF", FLIGHT), ("airfrance.es", "Air France", "AF", FLIGHT), ("klm.com", "KLM", "KL", FLIGHT),
    ("wizzair.com", "Wizz Air", "W6", FLIGHT), ("transavia.com", "Transavia", "HV", FLIGHT), ("norwegian.com", "Norwegian", "DY", FLIGHT),
    ("renfe.com", "Renfe", "", TRAIN), ("iryo.eu", "Iryo", "", TRAIN), ("ouigo.com", "Ouigo", "", TRAIN), ("ouigo.es", "Ouigo", "", TRAIN),
    ("sncf-connect.com", "SNCF", "", TRAIN), ("sncf.com", "SNCF", "", TRAIN), ("trenitalia.com", "Trenitalia", "", TRAIN),
    ("italotreno.it", "Italo", "", TRAIN), ("cp.pt", "CP Comboios de Portugal", "", TRAIN), ("alsa.es", "Alsa", "", BUS), ("alsa.com", "Alsa", "", BUS),
    ("flixbus.com", "FlixBus", "", BUS), ("flixbus.es", "FlixBus", "", BUS), ("avanzabus.com", "Avanza", "", BUS), ("socibus.es", "Socibus", "", BUS),
    ("balearia.com", "Baleària", "", FERRY), ("trasmediterranea.es", "Trasmed", "", FERRY), ("navieraarmas.com", "Naviera Armas", "", FERRY),
    ("fredolsen.es", "Fred. Olsen Express", "", FERRY), ("grimaldi-lines.com", "Grimaldi Lines", "", FERRY),
    ("brittany-ferries.com", "Brittany Ferries", "", FERRY), ("directferries.com", "Direct Ferries", "", FERRY),
    ("booking.com", "Booking.com", "", LODGING), ("airbnb.com", "Airbnb", "", LODGING), ("airbnb.es", "Airbnb", "", LODGING),
    ("vrbo.com", "Vrbo", "", LODGING), ("hrs.com", "HRS", "", LODGING), ("hotels.com", "Hotels.com", "", LODGING),
    ("homeaway.com", "HomeAway", "", LODGING), ("hostelworld.com", "Hostelworld", "", LODGING), ("niumba.com", "Niumba", "", LODGING),
    ("hertz.com", "Hertz", "", CAR), ("avis.com", "Avis", "", CAR), ("avis.es", "Avis", "", CAR), ("europcar.com", "Europcar", "", CAR),
    ("europcar.es", "Europcar", "", CAR), ("sixt.com", "Sixt", "", CAR), ("sixt.es", "Sixt", "", CAR), ("enterprise.com", "Enterprise", "", CAR),
    ("goldcar.es", "Goldcar", "", CAR), ("centauro.net", "Centauro", "", CAR), ("rentalcars.com", "Rentalcars", "", CAR),
    ("edreams.com", "eDreams", "", ""), ("edreams.es", "eDreams", "", ""), ("opodo.com", "Opodo", "", ""), ("opodo.es", "Opodo", "", ""),
    ("kayak.com", "Kayak", "", ""), ("kayak.es", "Kayak", "", ""), ("atrapalo.com", "Atrápalo", "", ""), ("logitravel.com", "Logitravel", "", ""),
    ("expedia.com", "Expedia", "", ""), ("expedia.es", "Expedia", "", ""), ("trip.com", "Trip.com", "", ""), ("trainline.com", "Trainline", "", ""),
    ("destinia.com", "Destinia", "", ""), ("rumbo.es", "Rumbo", "", ""), ("viajeselcorteingles.es", "Viajes El Corte Inglés", "", ""),
    ("despegar.com", "Despegar", "", ""), ("skyscanner.net", "Skyscanner", "", ""), ("kiwi.com", "Kiwi.com", "", ""),
]
# sender names without a known domain (forwarded or white-label mail): matched in the From name
NAME_HINTS = {"vueling": FLIGHT, "iberia": FLIGHT, "air europa": FLIGHT, "ryanair": FLIGHT, "easyjet": FLIGHT, "volotea": FLIGHT, "renfe": TRAIN,
              "iryo": TRAIN, "ouigo": TRAIN, "alsa": BUS, "flixbus": BUS, "booking.com": LODGING, "airbnb": LODGING}

OTA_KINDS = ""      # agencies and unknown senders: the kind comes from the content


def sender_of(address: str, name: str = "") -> Optional[tuple[str, str, str]]:
    domain = (address or "").rpartition("@")[2].lower()
    for suffix, display, code, kind in SENDERS:
        if domain == suffix or domain.endswith("." + suffix):
            return display, code, kind
    folded = fold(name)
    for hint, kind in NAME_HINTS.items():
        if hint in folded:
            code = code_for_name(hint)
            return hint.title(), code, kind
    return None


# ------------------------------------------------------------------ changes and cancellations
CANCEL_RX = re.compile(r"cancelad[oa]s?|cancelaci[oó]n|cancell?ation|cancell?ed|anulad[oa]s?|anulaci[oó]n|\bannul|storniert", re.I)
CHANGE_RX = re.compile(r"modificad[oa]|modificaci[oó]n|cambio de (?:horario|vuelo|hora|puerta|itinerario)|schedule change|time change|"
                       r"has been (?:changed|modified|rescheduled|updated)|reprogramad|actualizaci[oó]n de (?:tu |su )?(?:reserva|vuelo|viaje)|"
                       r"flight (?:change|update)|itinerary (?:change|update)|cambios? en (?:tu|su) (?:reserva|vuelo|viaje)|nuevo horario|new departure time|"
                       r"horario (?:ha cambiado|actualizado)|your booking (?:has been )?(?:changed|amended)", re.I)
POLICY_RX = re.compile(r"pol[ií]tica|policy|gratuit|free cancell|puedes cancelar|can cancel|puede cancelar|condiciones|terms|hasta \d+ horas|sin coste", re.I)


def change_of(subject: str, text: str) -> str:
    head = subject + "\n" + "\n".join(clean_lines(text)[:6])
    head = POLICY_RX.sub(" ", head)
    if CANCEL_RX.search(head):
        return "cancel"
    if CHANGE_RX.search(head):
        return "change"
    return "new"


# ------------------------------------------------------------------ common fields
REF_LABEL = (r"(?i:localizador(?: de (?:la )?reserva)?|c[oó]digo de reserva|referencia(?: de (?:la )?reserva)?|n[uú]mero de reserva|n[ºo°] de reserva|"
             r"n[uú]mero de confirmaci[oó]n|c[oó]digo de confirmaci[oó]n|booking (?:reference|ref\.?|code|number|no\.?|id)|reservation (?:code|number|no\.?|id)|"
             r"confirmation (?:code|number|no\.?)|record locator|\bPNR\b|c[oó]digo del billete|reserva(?: n[ºo°.]+)?|booking)")
RE_REF = re.compile(REF_LABEL + r"\s*(?:[:#\-]|es\b|is\b)?\s*\n?\s*([A-Z0-9]{5,12})(?![A-Za-z0-9])")
REF_STOP = {"RESERVA", "BILLETE", "CODIGO", "CLIENT", "NUMERO", "ONLINE", "BOOKING", "VUELOS", "TICKET", "CHECKIN", "FLIGHT", "TRENES", "HOTELS"}


def find_ref(text: str, subject: str = "") -> str:
    for source in (subject, text):
        for m in RE_REF.finditer(source or ""):
            code = m.group(1)
            if code in REF_STOP or not re.search(r"\d", code) and not re.fullmatch(r"[A-Z]{6}", code):
                continue
            if code.isdigit() and len(code) < 6:
                continue
            return code
    return ""


RE_PAX = re.compile(r"(?:pasajeros?|passengers?|viajeros?|titular|hu[eé]sped(?:es)?|guests?|nombre del pasajero|travell?ers?)\s*(?:\(\d+\))?\s*[:\-]\s*(.+)", re.I)


def find_passengers(text: str) -> list[str]:
    out: list[str] = []
    for m in RE_PAX.finditer(text or ""):
        value = m.group(1)
        value = re.split(r"\b(?:localizador|booking|reserva|vuelo|flight|fecha|tel[eé]fono)\b", value, maxsplit=1, flags=re.I)[0]
        for part in re.split(r"[;,]| y | and |\s{2,}|\|", value):
            part = part.strip()
            if 2 <= len(part) <= 40 and not re.search(r"\d|@", part):
                out.append(part)
    return out[:9]


AMT = r"(\d{1,3}(?:[.  ]\d{3})+[.,]\d{2}|\d{1,6}[.,]\d{2})"
RE_PRICE_TOTAL = re.compile(r"(?:precio total|importe total|total a pagar|total pagado|total del (?:pedido|viaje|billete)|total price|total amount|amount paid|"
                            r"grand total|\btotal\b)[^\n\d€£$]{0,24}(?:(€|£|\$|EUR|GBP|USD)\s*)?" + AMT + r"\s*(€|£|\$|EUR|GBP|USD)?", re.I)


def _amount(raw: str) -> Optional[float]:
    """An amount written with two decimals as a float, through the shared money parser."""
    value = parse_amount(raw, currency_hint="EUR")
    return float(value) if value is not None else None


def find_price(text: str) -> tuple[Optional[float], str]:
    m = RE_PRICE_TOTAL.search(text or "")
    if not m:
        return None, ""
    value = _amount(m.group(2))
    cur = currency_of(m.group(1) or m.group(3) or "")
    return (value, cur or "EUR") if value is not None else (None, "")


LINK_KINDS = [("checkin", re.compile(r"check-?in|facturar|facturaci|embarque online|online-checkin|boarding", re.I)),
              ("ticket", re.compile(r"billete|ticket|tarjeta de embarque|boarding pass|descarga|download|\.pdf|eticket|e-ticket", re.I)),
              ("manage", re.compile(r"gestion|manage|mi reserva|mis viajes|my ?trips?|my booking|modific|mmb|view booking|ver reserva|mytrip|booking/", re.I))]
LINK_SKIP = re.compile(r"unsubscribe|darse de baja|baja\b|privacy|privacidad|facebook|twitter|instagram|linkedin|youtube|play\.google|apps\.apple|mailto:|"
                       r"\.(?:png|jpe?g|gif)(?:\?|$)|cookies|aviso legal|terms|condiciones", re.I)


def find_links(links: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for link in links or []:
        url = _numbers.unwrap(str(link.get("url") or ""))
        label = str(link.get("label") or "")
        if not url.lower().startswith(("http://", "https://")) or LINK_SKIP.search(url + " " + label):
            continue
        kind = next((k for k, rx in LINK_KINDS if rx.search(label + " " + url)), "")
        if kind and not any(x["url"] == url for x in out):
            out.append({"kind": kind, "url": url[:1500], "label": label[:80]})
    order = {"checkin": 0, "manage": 1, "ticket": 2}
    return sorted(out, key=lambda x: order.get(x["kind"], 9))[:6]


COUNTRIES = {"espana": "ES", "spain": "ES", "portugal": "PT", "francia": "FR", "france": "FR", "italia": "IT", "italy": "IT", "alemania": "DE",
             "germany": "DE", "deutschland": "DE", "reino unido": "GB", "united kingdom": "GB", "inglaterra": "GB", "paises bajos": "NL",
             "netherlands": "NL", "holanda": "NL", "belgica": "BE", "belgium": "BE", "irlanda": "IE", "ireland": "IE", "grecia": "GR", "greece": "GR",
             "marruecos": "MA", "morocco": "MA", "suiza": "CH", "switzerland": "CH", "austria": "AT", "estados unidos": "US", "usa": "US",
             "croacia": "HR", "croatia": "HR", "polonia": "PL", "poland": "PL", "republica checa": "CZ", "chequia": "CZ", "dinamarca": "DK"}


def country_in(text: str) -> str:
    f = fold(text)
    for name in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", f):
            return COUNTRIES[name]
    return ""


def city_in(text: str) -> tuple[str, str]:
    """A known city named in an address or hotel line (last comma-separated part first)."""
    parts = [p.strip() for p in re.split(r"[,\n]", text or "") if p.strip()]
    for part in reversed(parts):
        part = re.sub(r"^\d{4,5}(?:-\d{3})?\s+", "", part)
        city, country = airports.city_of(part)
        if city:
            return city, country
    return "", ""


# ------------------------------------------------------------------ legs
@dataclass
class Leg:
    number_code: str = ""
    number: str = ""
    from_code: str = ""
    to_code: str = ""
    from_name: str = ""
    to_name: str = ""
    dep_date: str = ""
    dep_time: str = ""
    arr_date: str = ""
    arr_time: str = ""
    extra: dict[str, str] = field(default_factory=dict)

    def started(self) -> bool:
        return bool(self.from_code or self.from_name or self.number or self.dep_date or self.dep_time)

    def routed(self) -> bool:
        return bool((self.from_code and self.to_code) or (self.from_name and self.to_name))


def _walk_legs(tokens: list[dict[str, Any]], *, ground: bool) -> list[Leg]:
    legs: list[Leg] = []
    leg, label = Leg(), ""
    last_date = ""

    def flush(reset_label: bool = True) -> None:
        nonlocal leg, label, last_date
        if (leg.routed() or leg.number) and (leg.dep_date or last_date) and (leg.routed() or leg.dep_time):
            if not leg.dep_date:
                leg.dep_date = last_date
            legs.append(leg)
            last_date = leg.dep_date
        leg = Leg()
        if reset_label:
            label = ""

    for tk in tokens:
        t = tk["t"]
        if t == "label":
            if tk["name"] in ("dep", "arr"):
                label = tk["name"]
        elif t == "leg":
            flush()
        elif t == "route":
            if leg.from_code or leg.to_code:
                flush()
            leg.from_code, leg.to_code = tk["from"], tk["to"]
        elif t == "air" and not ground:
            if label == "arr" and leg.from_code and not leg.to_code:
                leg.to_code = tk["code"]
            elif not leg.from_code:
                leg.from_code = tk["code"]
            elif not leg.to_code and tk["code"] != leg.from_code:
                leg.to_code = tk["code"]
            elif tk["code"] != leg.to_code and tk["code"] != leg.from_code:
                flush()
                leg.from_code = tk["code"]
        elif t == "num":
            number = (tk["code"], tk["digits"])
            if leg.number and (leg.number_code, leg.number) != number:
                flush()
            leg.number_code, leg.number = number
        elif t == "place":
            role = tk["role"]
            if role == "route":
                if leg.from_name or leg.to_name:
                    flush()
                leg.from_name, leg.to_name = tk["text"], tk["to"]
            elif role == "from" or (role == "dep" and ground and not leg.from_name):
                if leg.from_name and role == "from":
                    flush()
                leg.from_name = tk["text"]
            elif role == "to" or (role == "arr" and ground and not leg.to_name and leg.from_name):
                leg.to_name = tk["text"]
        elif t == "extra":
            key = {"train": "number_ground", "class": "travel_class"}.get(tk["field"], tk["field"])
            if key in ("number_ground",) and leg.extra.get(key) and leg.extra[key] != tk["value"]:
                flush()
            if key == "number_ground":
                leg.extra["carrier"] = tk.get("carrier", "")
            if not leg.extra.get(key):
                leg.extra[key] = tk["value"]
        elif t == "date":
            if label == "arr" and (leg.dep_date or leg.dep_time):
                if leg.arr_date and leg.arr_date != tk["date"]:
                    flush()
                    leg.dep_date = tk["date"]
                else:
                    leg.arr_date = tk["date"]
            elif not leg.dep_date:
                leg.dep_date = tk["date"]
            elif leg.dep_time and (leg.arr_time or leg.to_code or leg.to_name) and not leg.arr_date and tk["date"] != leg.dep_date:
                leg.arr_date = tk["date"]
            elif tk["date"] != leg.dep_date and leg.dep_time and leg.arr_time:
                flush()
                leg.dep_date = tk["date"]
        elif t == "time":
            if label == "arr":
                if leg.arr_time and leg.arr_time != tk["time"]:
                    flush(False)
                leg.arr_time = tk["time"]
            elif label == "dep":
                if leg.dep_time and leg.dep_time != tk["time"]:
                    flush(False)
                leg.dep_time = tk["time"]
            elif not leg.dep_time:
                leg.dep_time = tk["time"]
            elif not leg.arr_time and tk["time"] != leg.dep_time:
                leg.arr_time = tk["time"]
            elif leg.arr_time and tk["time"] not in (leg.dep_time, leg.arr_time):
                flush()
                leg.dep_time = tk["time"]
    flush()
    return legs


def _local(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}" if day and hhmm else day


def _fix_overnight(d: SegmentDraft, arr_date_given: bool) -> None:
    """An arrival time earlier than the departure with no arrival date written means the next day (compared in UTC)."""
    if arr_date_given or not airports.has_time(d.arr_local) or not airports.has_time(d.dep_local):
        return
    dep = airports.to_ts(d.dep_local, d.dep_tz)
    for _ in range(3):
        arr = airports.to_ts(d.arr_local, d.arr_tz or d.dep_tz)
        if dep is None or arr is None or arr >= dep:
            return
        nxt = airports.parse_local(d.arr_local)
        if nxt is None:
            return
        d.arr_local = (nxt + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


def parse_flights(lines: list[str], ref: date, default_code: str) -> list[SegmentDraft]:
    out = []
    for leg in _walk_legs(tokenize(lines, ref), ground=False):
        if not leg.from_code or not leg.to_code or not leg.dep_date:
            continue
        code = leg.number_code or default_code
        d = SegmentDraft(kind=FLIGHT, source="rules", confidence=75, carrier_code=code, carrier=AIRLINES.get(code, ""),
                         number=(code + leg.number) if leg.number else "", from_code=leg.from_code, to_code=leg.to_code,
                         dep_local=_local(leg.dep_date, leg.dep_time), arr_local=_local(leg.arr_date or leg.dep_date, leg.arr_time))
        d.terminal, d.gate, d.seat = leg.extra.get("terminal", ""), leg.extra.get("gate", ""), leg.extra.get("seat", "")
        d.travel_class = leg.extra.get("travel_class", "")
        d.enrich()
        _fix_overnight(d, bool(leg.arr_date))
        d.evidence = [f"{d.number or 'flight'} {d.from_code}-{d.to_code} {d.dep_local}"]
        if not leg.dep_time:
            d.confidence -= 15
        out.append(d)
    return out


def parse_ground(lines: list[str], ref: date, kind: str, carrier: str) -> list[SegmentDraft]:
    out = []
    text = "\n".join(lines)
    for leg in _walk_legs(tokenize(lines, ref, places=True), ground=True):
        if not (leg.from_name and leg.to_name and leg.dep_date):
            continue
        d = SegmentDraft(kind=kind, source="rules", confidence=75, carrier=carrier, from_name=leg.from_name, to_name=leg.to_name,
                         dep_local=_local(leg.dep_date, leg.dep_time), arr_local=_local(leg.arr_date or leg.dep_date, leg.arr_time),
                         coach=leg.extra.get("coach", ""), seat=leg.extra.get("seat", ""), travel_class=leg.extra.get("travel_class", ""),
                         number=leg.extra.get("number_ground", "") if kind == TRAIN else "")
        if kind == TRAIN and leg.extra.get("carrier") and not carrier:
            d.carrier = leg.extra["carrier"]
        d.enrich()
        _fix_overnight(d, bool(leg.arr_date))
        out.append(d)
    for d in out:
        d.evidence = [f"{d.from_name} → {d.to_name} {d.dep_local}"]
    return out


NAME_LABEL = re.compile(r"(?:alojamiento|hotel|propiedad|property|apartamento|establecimiento|accommodation|nombre del hotel)\s*[:\-]\s*(.+)", re.I)
NAME_SUBJECT = [re.compile(p, re.I) for p in (r"reserva(?: confirmada)? en (.+?)(?:\s[-–|]|,|\.|!|$)", r"(?:booking|reservation) (?:is )?(?:confirmed )?(?:at|for|in) (.+?)(?:\s[-–|]|,|\.|!|$)",
                                                   r"estancia en (.+?)(?:\s[-–|]|,|\.|!|$)", r"your stay at (.+?)(?:\s[-–|]|,|\.|!|$)", r"tu reserva (?:en|de) (.+?)(?:\s[-–|]|,|\.|!|$)")]
NAME_WORDS = re.compile(r"\b(hotel|hostal|hostel|apartamentos?|apartments?|resort|villa|pensi[oó]n|parador|b&b|aparthotel|casa rural|residence|suites?|inn|lodge)\b", re.I)
ADDR_LABEL = re.compile(r"(?:direcci[oó]n|address|ubicaci[oó]n)\s*[:\-]\s*(.+)", re.I)


def parse_stay(lines: list[str], ref: date, subject: str, provider_default: str) -> list[SegmentDraft]:
    tokens = tokenize(lines, ref, ignore_times=False)
    check_in = check_out = ""
    in_time = out_time = ""
    label = ""
    dates_free: list[str] = []
    for tk in tokens:
        t = tk["t"]
        if t == "label":
            label = {"in": "in", "arr": "in", "out": "out", "dep": "out"}.get(tk["name"], label)
        elif t == "date":
            if label == "in" and not check_in:
                check_in = tk["date"]
            elif label == "out" and not check_out:
                check_out = tk["date"]
            else:
                dates_free.append(tk["date"])
        elif t == "time":
            if label == "in" and not in_time:
                in_time = tk["time"]
            elif label == "out" and not out_time:
                out_time = tk["time"]
    free = iter(dates_free)
    if not check_in:
        check_in = next(free, "")
    if not check_out:
        check_out = next(free, "")
    if not check_in:
        return []
    name = ""
    for line in lines:
        m = NAME_LABEL.match(line)
        if m:
            name = m.group(1).strip()
            break
    if not name:
        for rx in NAME_SUBJECT:
            m = rx.search(subject or "")
            if m and not re.fullmatch(r"(?:tu|su|your)? ?(?:reserva|booking|viaje|estancia)", m.group(1).strip(), re.I):
                name = m.group(1).strip()
                break
    if not name:
        name = next((ln for ln in lines[:40] if NAME_WORDS.search(ln) and 4 <= len(ln) <= 70 and not re.search(r"[:@]|http", ln)), "")
    address = ""
    for line in lines:
        m = ADDR_LABEL.match(line)
        if m:
            address = m.group(1).strip()[:200]
            break
    name = re.sub(r"\s+", " ", name).strip(" .,-–:")[:90] or provider_default
    d = SegmentDraft(kind=LODGING, source="rules", confidence=75, provider=name, address=address, from_name=name,
                     dep_local=_local(check_in, in_time), arr_local=_local(check_out, out_time))
    city, country = city_in(address) if address else ("", "")
    if not city:
        city, country = city_in(name)
    d.from_city, d.from_country = city, country or country_in(address) or country_in("\n".join(lines[:60]))
    d.enrich()
    d.evidence = [f"{d.provider} {check_in}→{check_out}"]
    return [d]


def parse_car(lines: list[str], ref: date, provider: str) -> list[SegmentDraft]:
    tokens = tokenize(lines, ref, ignore_times=False, places=True)
    pick_d = pick_t = drop_d = drop_t = ""
    pick_place = drop_place = ""
    label = ""
    for tk in tokens:
        t = tk["t"]
        if t == "label" and tk["name"] in ("pick", "drop", "dep", "arr", "in", "out"):
            label = {"pick": "pick", "dep": "pick", "in": "pick", "drop": "drop", "arr": "drop", "out": "drop"}[tk["name"]]
        elif t == "date":
            if label == "drop":
                drop_d = drop_d or tk["date"]
            else:
                pick_d = pick_d or tk["date"]
        elif t == "time":
            if label == "drop":
                drop_t = drop_t or tk["time"]
            else:
                pick_t = pick_t or tk["time"]
    for line in lines:
        f = fold(line)
        m = re.match(r"(?:lugar de |oficina de |sucursal de )?(?:recogida|pick-?up|retirada)[^:]*:\s*(.+)", f)
        if m and not pick_place:
            pick_place = _clean_place(line[len(line) - len(m.group(1)):], ref)
        m = re.match(r"(?:lugar de |oficina de |sucursal de )?(?:devoluci[oó]n|devolucion|drop-?off|return)[^:]*:\s*(.+)", f)
        if m and not drop_place:
            drop_place = _clean_place(line[len(line) - len(m.group(1)):], ref)
    if not pick_d:
        return []
    model = ""
    for line in lines:
        m = re.match(r"(?:veh[ií]culo|vehicle|coche|car|modelo|model)\s*:\s*(.+)", line, re.I)
        if m:
            model = m.group(1).strip()[:60]
            break
    d = SegmentDraft(kind=CAR, source="rules", confidence=70, provider=provider, carrier=provider, from_name=pick_place, to_name=drop_place or pick_place,
                     dep_local=_local(pick_d, pick_t), arr_local=_local(drop_d or pick_d, drop_t), notes=model, address=pick_place)
    d.enrich()
    d.evidence = [f"{provider} {pick_place} {pick_d}→{drop_d}"]
    return [d]


def _clean_place(value: str, ref: date) -> str:
    from .scan import _strip_when
    return _strip_when(value, ref)[:80]


# ------------------------------------------------------------------ one mail
KIND_CUES = [
    (LODGING, re.compile(r"check-?in|check-?out|alojamiento|habitaci[oó]n|hotel|noches?|nights?|apartamento|accommodation|room\b", re.I)),
    (CAR, re.compile(r"alquiler de (?:coche|veh[ií]culo)|rental car|car rental|recogida del veh|pick-?up location|devoluci[oó]n del veh", re.I)),
    (TRAIN, re.compile(r"\b(?:tren|train|ave|avlo|alvia|renfe|iryo|ouigo|cercan[ií]as|estaci[oó]n)\b", re.I)),
    (BUS, re.compile(r"\b(?:autob[uú]s|bus|flixbus|alsa|parada)\b", re.I)),
    (FERRY, re.compile(r"\b(?:ferry|ferri|barco|naviera|embarcaci[oó]n|puerto|port of)\b", re.I)),
]
FLIGHT_CUE = re.compile(r"\b(?:vuelo|flight|flug|aerol[ií]nea|airline|aeropuerto|airport|terminal|tarjeta de embarque|boarding pass)\b", re.I)


@dataclass
class RulesResult:
    drafts: list[SegmentDraft] = field(default_factory=list)
    ref: str = ""
    change: str = "new"
    kinds: list[str] = field(default_factory=list)
    sender: str = ""


def kinds_for(sender: Optional[tuple[str, str, str]], subject: str, text: str, lines: list[str], ref: date) -> list[str]:
    if sender and sender[2]:
        return [sender[2]]
    kinds: list[str] = []
    probe = subject + "\n" + text
    if FLIGHT_CUE.search(probe) or any(t["t"] in ("route", "num") for t in tokenize(lines, ref)):
        kinds.append(FLIGHT)
    for kind, rx in KIND_CUES:
        if rx.search(probe) and kind not in kinds:
            kinds.append(kind)
    # a flight mail rarely is a hotel mail too: keep stays/cars only with their own strong cues
    if FLIGHT in kinds and LODGING in kinds and not re.search(r"check-?in\s*:|check-?out\s*:|alojamiento|hotel:", probe, re.I):
        kinds.remove(LODGING)
    return kinds


def read(message: dict[str, Any], ref: date) -> RulesResult:
    subject = str(message.get("subject") or "")
    text = str(message.get("text") or "")
    lines = clean_lines(text)
    sender = sender_of(str(message.get("from_address") or ""), str(message.get("from_name") or ""))
    res = RulesResult(sender=sender[0] if sender else "")
    res.change = change_of(subject, text)
    res.ref = find_ref(text, subject)
    res.kinds = kinds_for(sender, subject, text, lines, ref)
    code = sender[1] if sender else ""
    name = sender[0] if sender else ""
    drafts: list[SegmentDraft] = []
    for kind in res.kinds:
        if kind == FLIGHT:
            drafts += parse_flights(lines, ref, code)
        elif kind in (TRAIN, BUS, FERRY):
            drafts += parse_ground(lines, ref, kind, name)
        elif kind == LODGING:
            drafts += parse_stay(lines, ref, subject, "")
        elif kind == CAR:
            drafts += parse_car(lines, ref, name)
    pax = find_passengers(text)
    price, cur = find_price(text)
    links = find_links(message.get("links") or [])
    for d in drafts:
        d.booking_ref = d.booking_ref or res.ref
        d.passengers = d.passengers or pax
        d.links = links
        d.change = res.change
        d.status = CANCELLED if res.change == "cancel" else CONFIRMED
        if d is drafts[0] and price is not None:     # the booking total goes on the first segment only
            d.price, d.currency = price, cur
        d.enrich()
        if d.kind == FLIGHT and not d.carrier and d.carrier_code:
            d.carrier = AIRLINES.get(d.carrier_code, "")
    res.drafts = [d for d in drafts if d.usable()]
    return res
