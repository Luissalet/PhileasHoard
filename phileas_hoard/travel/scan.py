"""Shared reading of mail text for the sender rules: dates, times, airport codes, flight numbers, labels and places, in reading order."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Optional

from . import airports
from .airlines import FLIGHT_NUMBER_PREFIXES, fold

MONTHS = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1, "janvier": 1, "feb": 2, "febrero": 2, "february": 2, "fevrier": 2, "mar": 3, "marzo": 3,
    "march": 3, "mars": 3, "abr": 4, "abril": 4, "apr": 4, "april": 4, "avril": 4, "may": 5, "mayo": 5, "mai": 5, "jun": 6, "junio": 6,
    "june": 6, "juin": 6, "jul": 7, "julio": 7, "july": 7, "juillet": 7, "ago": 8, "agosto": 8, "aug": 8, "august": 8, "aout": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9, "september": 9, "septembre": 9, "oct": 10, "octubre": 10, "october": 10,
    "octobre": 10, "nov": 11, "noviembre": 11, "november": 11, "novembre": 11, "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
    "decembre": 12,
}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
RE_DMY = re.compile(r"(?<![\d/.:\-])(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?![\d:])")
RE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
RE_DAYMONTH = re.compile(rf"(?<![\d/.:\-])(\d{{1,2}})\s*(?:de\s+|th\s+|st\s+|nd\s+|rd\s+)?({_MONTH_RX})\b\.?(?:\s*(?:de\s+|,\s*)?(\d{{4}})\b)?")
RE_COMPACT = re.compile(rf"(?<![\d/.:\-])(\d{{1,2}})({_MONTH_RX})(\d{{2}})?(?![a-z0-9])")
RE_MONTHDAY = re.compile(rf"\b({_MONTH_RX})\b\.?\s+(\d{{1,2}})(?![\d:])(?:\s*,?\s*(\d{{4}})\b)?")
RE_TIME = re.compile(r"(?<![\d:.])([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)(?::[0-5]\d)?\s*(am|pm|a\.m\.|p\.m\.)?(?![\d])", re.I)
RE_PAREN_AIR = re.compile(r"\(([A-Z]{3})\)")
RE_ROUTE = re.compile(r"(?<![A-Za-z])([A-Z]{3})\s*(?:→|->|—>|–>|-->|➔|➝|✈|>|—|–|-|\bto\b|\ba\b)\s*([A-Z]{3})(?![A-Za-z])")
RE_ROUTE_WS = re.compile(r"(?<![A-Za-z])([A-Z]{3})\s+([A-Z]{3})(?![A-Za-z])")
RE_FLIGHT = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]|[0-9][A-Z])\s?-?(\d{2,4})(?![0-9A-Za-z])")
RE_FLIGHT_LABEL = re.compile(r"(?:vuelo|flight|flug|volo|vol)\s*(?:n[º°]|n\.|nro\.?|number|no\.|#)?\s*:?\s*([A-Z][A-Z0-9]|[0-9][A-Z])\s?-?(\d{2,4})(?![0-9A-Za-z])", re.I)
RE_TERMINAL = re.compile(r"terminal\s*:?\s*((?-i:[A-Z]?\d[A-Z]?|[A-Z]))(?![A-Za-z0-9])", re.I)
RE_GATE = re.compile(r"(?:puerta|gate)\s*:?\s*((?-i:[A-Z]?\d{1,3}[A-Z]?))(?![A-Za-z0-9])", re.I)
RE_SEAT_TK = re.compile(r"(?:asiento|seat|plaza|place|sitz)\s*:?\s*(\d{1,3}[A-Za-z]?)(?![A-Za-z0-9])", re.I)
RE_COACH_TK = re.compile(r"(?:coche|coach|car|vag[oó]n|wagon|voiture)\s*:?\s*(\d{1,2}[A-Za-z]?)(?![A-Za-z0-9])", re.I)
RE_TRAIN_NO = re.compile(r"\b(AVE|AVLO|ALVIA|ALTARIA|EUROMED|INTERCITY|MD|REGIONAL EXPRESS|REG\.?EXP\.?|CERCAN[IÍ]AS|RODALIES|IRYO|OUIGO|TGV|ICE|FRECCIAROSSA|ITALO|"
                         r"AR|AP|SUDEXPRESO|LUSITANIA|TRENHOTEL|AVANT)\b\.?\s*[:\-]?\s*(\d{3,5})\b", re.I)
RE_CLASS_TK = re.compile(r"\b(turista plus|turista|preferente|est[aá]ndar|standard|business|club|premium|primera|first class|second class|"
                         r"economy|econ[oó]mica|basic|b[aá]sico|confort|comfort)\b", re.I)
RE_ARROW = re.compile(r"\s*(?:→|->|—>|–>|-->|➔|➝|\s[–—]\s|\sa\s|\sto\s)\s*")

# Stoplist of three-letter words that are also airport codes: never read as an airport unless in brackets or on a route.
STOP_AIR = {"THE", "AND", "FOR", "VER", "CON", "SIN", "POR", "DEL", "LOS", "LAS", "UNA", "TAX", "IVA", "NIF", "DNI", "PDF", "WEB", "APP",
            "EUR", "USD", "GBP", "MAS", "MAY", "SAT", "SUN", "MON", "TUE", "WED", "THU", "FRI", "AIR", "ONE", "TWO", "NEW", "OLD"}

# Labels (folded, lower case). Ambiguous words only count when followed by a colon.
LABELS = [
    ("in", re.compile(r"\b(?:check[- ]?in|fecha de entrada|entrada|check in date)\b(?!\s*(?:online|abre|opens|web))")),
    ("out", re.compile(r"\b(?:check[- ]?out|fecha de salida del alojamiento|check out date)\b")),
    ("pick", re.compile(r"\b(?:recogida|pick[- ]?up|retirada|recoger)\b")),
    ("drop", re.compile(r"\b(?:devolucion|drop[- ]?off|devolver|return location)\b")),
    ("dep", re.compile(r"\b(?:salida|sale|departure|departs?|despegue|abflug|origen|origin|hora de salida|fecha de salida)\b|\b(?:from|desde)\s*:")),
    ("arr", re.compile(r"\b(?:llegada|llega|arrival|arrives?|ankunft|destino|destination|hora de llegada|fecha de llegada)\b|\b(?:to|hasta)\s*:")),
]
LEG_HEADER = re.compile(r"^\s*(?:vuelo de |trayecto de |tramo de |viaje de |flight |trip )?(?:ida|vuelta|regreso|outbound|inbound|return|retour|hinflug|r[uü]ckflug)\b", re.I)
IGNORE_TIME = re.compile(r"\b(?:embarque|boarding|puerta|gate|cierre|check-?in (?:opens|abre)|abre el check|presentaci[oó]n|antelaci[oó]n|"
                         r"se cierra|closes|hasta las|until|desde las|from \d)\b", re.I)


RE_TRAIL_AIR = re.compile(r"^(?:[\wÀ-ÿ'.\- ]{2,40}?)\s([A-Z]{3})$")
RE_PLACE_LABEL = re.compile(r"(?:^|\b)(?:origen|destino|origin|destination|from|to|desde|hasta|salida|llegada|departure|arrival)\b")


def clean_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").replace("\r", "").split("\n"):
        line = re.sub(r"[ \t ]+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _year(y: Optional[str], d: int, m: int, ref: date) -> Optional[date]:
    try:
        if y:
            yy = int(y)
            yy = yy + 2000 if yy < 100 else yy
            return date(yy, m, d)
        out = date(ref.year, m, d)
    except ValueError:
        return None
    if out < ref - timedelta(days=45):
        try:
            out = date(ref.year + 1, m, d)
        except ValueError:
            return None
    return out


def find_dates(line: str, ref: date) -> list[tuple[int, int, date]]:
    """(start, end, date) of every date written in ``line`` (folded copy is searched; positions are in the folded string)."""
    f = fold(line)
    found: list[tuple[int, int, date]] = []
    taken: list[tuple[int, int]] = []

    def free(span: tuple[int, int]) -> bool:
        return all(span[1] <= a or span[0] >= b for a, b in taken)

    def add(m: re.Match, dt: Optional[date]) -> None:
        if dt is not None and free(m.span()):
            taken.append(m.span())
            found.append((m.start(), m.end(), dt))

    for m in RE_ISO.finditer(f):
        try:
            add(m, date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in RE_DMY.finditer(f):
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            add(m, _year(m.group(3), d, mo, ref))
    for m in RE_DAYMONTH.finditer(f):
        add(m, _year(m.group(3), int(m.group(1)), MONTHS[m.group(2)], ref))
    for m in RE_COMPACT.finditer(f):
        add(m, _year(m.group(3), int(m.group(1)), MONTHS[m.group(2)], ref))
    for m in RE_MONTHDAY.finditer(f):
        if m.group(1) == "mar" and not m.group(3) and f[m.end():m.end() + 6].strip()[:3] in MONTHS:
            continue
        add(m, _year(m.group(3), int(m.group(2)), MONTHS[m.group(1)], ref))
    return sorted(found)


def find_times(line: str) -> list[tuple[int, int, str]]:
    out = []
    for m in RE_TIME.finditer(line):
        hh, mm, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower().replace(".", "")
        if ap == "pm" and hh < 12:
            hh += 12
        elif ap == "am" and hh == 12:
            hh = 0
        out.append((m.start(), m.end(), f"{hh:02d}:{mm:02d}"))
    return out


# "Origen: Madrid-Puerta de Atocha  Destino: Barcelona-Sants": label words that delimit values inside a line (folded text).
KV_WORDS = (r"origen|origin|from|desde|destino|destination|to|hasta|fecha|date|hora|time|salida|llegada|departure|arrival|tren|train|coche|coach|"
            r"plaza|asiento|seat|clase|class|pasajeros?|passengers?|viajeros?|localizador|reserva|booking|precio|price|total|autobus|bus|"
            r"ferry|barco|trayecto|route|ruta|vuelo|flight|check-?in|check-?out|entrada|recogida|devolucion|pick-?up|drop-?off")
RE_KV = re.compile(rf"(?<![a-z0-9])({KV_WORDS})(?![a-z0-9])\s*(?:[:\-]|\s)\s*", re.I)
PLACE_ROLE = {"origen": "from", "origin": "from", "from": "from", "desde": "from", "destino": "to", "destination": "to", "to": "to", "hasta": "to",
              "salida": "dep", "departure": "dep", "llegada": "arr", "arrival": "arr"}


def _strip_when(value: str, ref: date) -> str:
    """The text of a value without its dates and times."""
    out = value
    if len(fold(value)) == len(value):
        for a, b, _dt in sorted(find_dates(value, ref), reverse=True):
            out = out[:a] + " " + out[b:]
    out = RE_TIME.sub(" ", out)
    out = re.sub(r"\b(?:desde las|hasta las|a las|at|on|hrs?)\b", " ", out, flags=re.I)
    return re.sub(r"\s+", " ", re.sub(r"^[\s:|·,;\-–—]+|[\s:|·,;\-–—]+$", "", out)).strip()


def place_tokens(line: str, ref: date) -> list[tuple[int, dict[str, Any]]]:
    """Places written after a label ("Origen: X", "Salida: X 08:30") or as ``X → Y`` (names, not airport codes)."""
    out: list[tuple[int, dict[str, Any]]] = []
    f = fold(line)
    marks = list(RE_KV.finditer(f))
    for i, m in enumerate(marks):
        role = PLACE_ROLE.get(m.group(1).lower())
        if not role:
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
        value = _strip_when(line[m.end():end], ref)
        if len(re.findall(r"[A-Za-zÀ-ÿ]", value)) >= 3 and not re.fullmatch(r"[A-Z]{3}", value) and len(value) <= 70:
            out.append((m.start(), {"t": "place", "role": role, "text": value}))
    if not out:
        parts = RE_ARROW.split(line)
        if len(parts) == 2:
            a, b = (_strip_when(p, ref) for p in parts)
            if all(len(re.findall(r"[A-Za-zÀ-ÿ]", x)) >= 3 and len(x) <= 70 for x in (a, b)) and not (RE_ROUTE.search(line)):
                out.append((0, {"t": "place", "role": "route", "text": a, "to": b}))
    return out


def tokenize(lines: list[str], ref: date, *, ignore_times: bool = True, places: bool = False) -> list[dict[str, Any]]:
    """Reading-order tokens. Label tokens (dep, arr, in, out, pick, drop) set the context the next date/time tokens carry."""
    tokens: list[dict[str, Any]] = []
    for n, line in enumerate(lines):
        f = fold(line)
        events: list[tuple[int, dict[str, Any]]] = []
        if LEG_HEADER.match(line):
            events.append((-1, {"t": "leg"}))
        for name, rx in LABELS:
            for m in rx.finditer(f):
                events.append((m.start(), {"t": "label", "name": name}))
        ignore = ignore_times and bool(IGNORE_TIME.search(line))
        for a, b, dt in find_dates(line, ref):
            events.append((a, {"t": "date", "date": dt.isoformat()}))
        for a, b, hhmm in find_times(line):
            if ignore and not re.search(r"salida|sale|llegada|departure|arrival|llega", f):
                continue
            events.append((a, {"t": "time", "time": hhmm}))
        routed: set[str] = set()
        for m in RE_ROUTE.finditer(line):
            a, b = m.group(1), m.group(2)
            if airports.known(a) and airports.known(b) and a != b:
                events.append((m.start(), {"t": "route", "from": a, "to": b}))
                routed.update((a, b))
        for m in RE_ROUTE_WS.finditer(line):
            a, b = m.group(1), m.group(2)
            if airports.known(a) and airports.known(b) and a != b and a not in STOP_AIR and b not in STOP_AIR and a not in routed:
                events.append((m.start(), {"t": "route", "from": a, "to": b}))
                routed.update((a, b))
        for m in RE_PAREN_AIR.finditer(line):
            if m.group(1) not in routed and airports.known(m.group(1)):
                events.append((m.start(), {"t": "air", "code": m.group(1)}))
        if re.fullmatch(r"[A-Z]{3}", line) and airports.known(line) and line not in STOP_AIR:
            events.append((0, {"t": "air", "code": line}))
        else:
            trail = RE_TRAIL_AIR.match(line)
            prev = fold(lines[n - 1]) if n else ""
            if trail and airports.known(trail.group(1)) and trail.group(1) not in STOP_AIR and (RE_PLACE_LABEL.search(prev) or RE_PLACE_LABEL.search(f)):
                events.append((trail.start(1), {"t": "air", "code": trail.group(1)}))
        for rx, kind in ((RE_TERMINAL, "terminal"), (RE_GATE, "gate"), (RE_SEAT_TK, "seat"), (RE_COACH_TK, "coach")):
            for m in rx.finditer(line):
                events.append((m.start(), {"t": "extra", "field": kind, "value": m.group(1).upper()}))
        for m in RE_TRAIN_NO.finditer(line):
            events.append((m.start(), {"t": "extra", "field": "train", "value": (m.group(1) + m.group(2)).upper().replace(" ", ""), "carrier": m.group(1).title()}))
        for m in RE_CLASS_TK.finditer(line):
            events.append((m.start(), {"t": "extra", "field": "class", "value": m.group(1).capitalize()}))
        nums = list(RE_FLIGHT_LABEL.finditer(line))
        for m in nums:
            events.append((m.start(), {"t": "num", "code": m.group(1).upper(), "digits": m.group(2).lstrip("0") or "0"}))
        for m in RE_FLIGHT.finditer(line):
            code = m.group(1)
            if code in FLIGHT_NUMBER_PREFIXES and not any(x.start() <= m.start() < x.end() for x in nums):
                events.append((m.start(), {"t": "num", "code": code, "digits": m.group(2).lstrip("0") or "0"}))
        if places:
            events.extend(place_tokens(line, ref))
        events.append((10_000, {"t": "nl"}))
        for pos, ev in sorted(events, key=lambda e: e[0]):
            tokens.append({**ev, "line": n, "pos": pos})
    return tokens
