"""Local airport table: IATA code -> name, city, country, time zone (vendored JSON, see docs/ARCHITECTURE.md for the licence)."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .airlines import fold

DATA = Path(__file__).with_name("tables") / "airports.json"

# Schengen area (ISO country codes): Vueling's online check-in closes later outside it.
SCHENGEN = frozenset("AT BE BG CH CZ DE DK EE ES FI FR GR HR HU IS IT LI LT LU LV MT NL NO PL PT RO SE SI SK".split())

# City names in Spanish for the trip titles (the table has them in English). Only the ones that differ.
CITY_ES = {
    "Lisbon": "Lisboa", "London": "Londres", "Rome": "Roma", "Milan": "Milán", "Brussels": "Bruselas", "Vienna": "Viena", "Prague": "Praga",
    "Warsaw": "Varsovia", "Athens": "Atenas", "Copenhagen": "Copenhague", "Geneva": "Ginebra", "Seville": "Sevilla", "Cologne": "Colonia",
    "Venice": "Venecia", "Florence": "Florencia", "Naples": "Nápoles", "Turin": "Turín", "Munich": "Múnich", "Zurich": "Zúrich",
    "Moscow": "Moscú", "Cairo": "El Cairo", "Marrakesh": "Marrakech", "Edinburgh": "Edimburgo", "Bucharest": "Bucarest", "Cracow": "Cracovia",
    "Krakow": "Cracovia", "Gothenburg": "Gotemburgo", "Luxembourg": "Luxemburgo", "Mexico City": "Ciudad de México", "Porto": "Oporto",
    "Palma de Mallorca": "Palma", "Genoa": "Génova", "Nuremberg": "Núremberg", "Dublin": "Dublín",
    "Belgrade": "Belgrado", "Tangier": "Tánger", "Algiers": "Argel", "Tunis": "Túnez", "Alexandria": "Alejandría",
    "Basel": "Basilea", "Bern": "Berna",
}


# Airports that serve one metropolitan area (or a city and its overflow airport): arriving at one and leaving from another is still
# "the same place" when trips are grouped. Keyed by the first code of each group.
METRO_GROUPS = [
    "MAD TOJ", "BCN GRO REU", "LHR LGW STN LTN LCY SEN", "CDG ORY BVA", "MXP LIN BGY", "FCO CIA", "JFK LGA EWR", "BER SXF TXL",
    "ARN BMA NYO", "SVO DME VKO", "HND NRT", "ORD MDW", "IAD DCA BWI", "BRU CRL", "OSL TRF", "LAX BUR SNA", "SFO OAK SJC", "YYZ YTZ",
]
METRO: dict[str, str] = {code: group.split()[0] for group in METRO_GROUPS for code in group.split()}


def metro_of(code: str) -> str:
    """The metropolitan-area key of an airport code ("" when it is not in a group)."""
    return METRO.get((code or "").strip().upper(), "")


def metro_of_city(city: str) -> str:
    """The metro key of a city name, when one of its airports is in a group ("Madrid" -> "MAD")."""
    want = fold(city or "")
    if not want:
        return ""
    for code, key in METRO.items():
        row = table().get(code)
        if row and fold(row[1]) == want:
            return key
    return ""


@lru_cache(maxsize=1)
def table() -> dict[str, tuple[str, str, str, str]]:
    try:
        raw = json.loads(DATA.read_text(encoding="utf-8"))
        return {code: tuple(row) for code, row in raw["airports"].items()}  # type: ignore[misc]
    except (OSError, ValueError, KeyError):
        return {}


def lookup(code: str) -> Optional[dict[str, str]]:
    row = table().get((code or "").strip().upper())
    if not row:
        return None
    return {"code": code.strip().upper(), "name": row[0], "city": row[1], "country": row[2], "tz": row[3]}


def known(code: str) -> bool:
    return (code or "").strip().upper() in table()


@lru_cache(maxsize=1)
def _country_tz() -> dict[str, str]:
    by: dict[str, Counter] = {}
    for _name, _city, country, tz in table().values():
        by.setdefault(country, Counter())[tz] += 1
    return {cc: counts.most_common(1)[0][0] for cc, counts in by.items()}


def country_tz(country: str) -> str:
    return _country_tz().get((country or "").upper(), "")


def city_name(city: str, lang: str = "es") -> str:
    return CITY_ES.get(city, city) if lang == "es" else city


def valid_tz(name: str) -> bool:
    if not name:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?")


def parse_local(value: str) -> Optional[datetime]:
    """Naive datetime from ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM``; date-only values come back at 00:00."""
    m = _ISO.match(value or "")
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
        return datetime(y, mo, d, hh, mm)
    except ValueError:
        return None


def has_time(value: str) -> bool:
    return bool(_ISO.match(value or "") and (_ISO.match(value).group(4) is not None))  # type: ignore[union-attr]


def to_ts(local: str, tz: str = "", offset_min: Optional[int] = None, default_tz: str = "Europe/Madrid") -> Optional[float]:
    """UTC epoch seconds of a local wall-clock time. A real zone wins; else a fixed offset from the mail; else ``default_tz``."""
    dt = parse_local(local)
    if dt is None:
        return None
    if valid_tz(tz):
        return dt.replace(tzinfo=ZoneInfo(tz)).timestamp()
    if offset_min is not None:
        return dt.replace(tzinfo=timezone(timedelta(minutes=int(offset_min)))).timestamp()
    zone = default_tz if valid_tz(default_tz) else "UTC"
    return dt.replace(tzinfo=ZoneInfo(zone)).timestamp()


def local_from_ts(ts: float, tz: str) -> str:
    zone = ZoneInfo(tz) if valid_tz(tz) else timezone.utc
    return datetime.fromtimestamp(ts, zone).strftime("%Y-%m-%dT%H:%M")


def utc_offset_min(local: str, tz: str) -> Optional[int]:
    dt = parse_local(local)
    if dt is None or not valid_tz(tz):
        return None
    off = dt.replace(tzinfo=ZoneInfo(tz)).utcoffset()
    return int(off.total_seconds() // 60) if off is not None else None


# ------------------------------------------------------------------ cities (for stations and stays that have no airport code)
@lru_cache(maxsize=1)
def _city_index() -> dict[str, tuple[str, str]]:
    """folded city name (English and Spanish) -> (English city, most common country)."""
    from .airlines import fold
    by: dict[str, Counter] = {}
    names: dict[str, str] = {}
    for _name, city, country, _tz in table().values():
        key = fold(city)
        if len(key) < 3:
            continue
        by.setdefault(key, Counter())[country] += 1
        names.setdefault(key, city)
    index = {key: (names[key], counts.most_common(1)[0][0]) for key, counts in by.items()}
    for english, spanish in CITY_ES.items():
        key = fold(spanish)
        if fold(english) in index and key not in index:
            index[key] = index[fold(english)]
        elif key in index and fold(english) not in index:
            index[fold(english)] = index[key]
    return index


def city_of(place: str, prefer: tuple[str, ...] = ("ES", "PT", "FR", "IT", "DE", "GB")) -> tuple[str, str]:
    """``(city, country)`` read from a station, stop or hotel name: the longest known city at the start of the text
    ("Madrid Puerta de Atocha" -> Madrid, "Sevilla-Santa Justa" -> Seville). Unknown places give ``("", "")``."""
    from .airlines import fold
    tokens = re.findall(r"[a-z0-9ñ]+", fold(place))
    index = _city_index()
    for n in range(min(4, len(tokens)), 0, -1):
        hit = index.get(" ".join(tokens[:n]))
        if hit:
            city, country = hit
            return city, country
    return "", ""
