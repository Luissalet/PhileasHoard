"""One travel segment as read from a mail (before it is filed): shared by the schema reader, the sender rules and the model pass."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import airports
from .airlines import fold
from .model import BUS, CAR, CONFIRMED, EVENT, FERRY, FLIGHT, KINDS, LODGING, TRAIN


@dataclass
class SegmentDraft:
    kind: str = ""
    status: str = CONFIRMED                      # confirmed | cancelled
    change: str = "new"                          # what the mail says: new | change | cancel
    booking_ref: str = ""
    carrier: str = ""
    carrier_code: str = ""
    number: str = ""
    provider: str = ""
    from_code: str = ""
    from_name: str = ""
    from_city: str = ""
    from_country: str = ""
    to_code: str = ""
    to_name: str = ""
    to_city: str = ""
    to_country: str = ""
    dep_local: str = ""                          # YYYY-MM-DDTHH:MM (or a bare date when the mail gives no time)
    dep_tz: str = ""
    dep_offset: Optional[int] = None
    arr_local: str = ""
    arr_tz: str = ""
    arr_offset: Optional[int] = None
    terminal: str = ""
    gate: str = ""
    seat: str = ""
    coach: str = ""
    travel_class: str = ""
    passengers: list[str] = field(default_factory=list)   # first names only
    price: Optional[float] = None
    currency: str = ""
    links: list[dict[str, str]] = field(default_factory=list)   # {kind: manage|checkin|ticket|other, url, label}
    address: str = ""
    notes: str = ""
    confidence: int = 70
    source: str = "rules"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SegmentDraft":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    # ------------------------------------------------------------------ completeness
    def start_date(self) -> str:
        return self.dep_local[:10]

    def usable(self) -> bool:
        """Enough to be filed as a segment: a known kind, a date, and a route (transport), a name (stay) or a title (activity)."""
        if self.kind not in KINDS or not re.match(r"\d{4}-\d{2}-\d{2}", self.dep_local or ""):
            return False
        if self.kind in (FLIGHT, TRAIN, BUS, FERRY):
            return bool((self.from_code or self.from_name) and (self.to_code or self.to_name))
        if self.kind == LODGING:
            return bool(self.provider or self.address)
        if self.kind == CAR:
            return bool(self.provider or self.from_name)
        return bool(self.provider or self.notes)

    def usable_fields(self) -> bool:
        return self.usable()

    # ------------------------------------------------------------------ enrichment from the local tables
    def enrich(self, default_tz: str = "Europe/Madrid") -> "SegmentDraft":
        """Fill airport names, cities, countries and time zones; convert explicit offsets to the airport's wall-clock time."""
        self.booking_ref = (self.booking_ref or "").strip().upper()[:20]
        self.number = re.sub(r"\s+", "", (self.number or "").upper())[:12]
        self.passengers = [p for p in dict.fromkeys(_first_name(p) for p in self.passengers) if p][:9]
        for side in ("from", "to"):
            code = getattr(self, f"{side}_code").strip().upper()
            setattr(self, f"{side}_code", code)
            info = airports.lookup(code) if code else None
            if info and self.kind in (FLIGHT, ""):
                if not getattr(self, f"{side}_name"):
                    setattr(self, f"{side}_name", info["name"])
                setattr(self, f"{side}_city", info["city"])
                setattr(self, f"{side}_country", info["country"])
                if not getattr(self, f"{'dep' if side == 'from' else 'arr'}_tz"):
                    setattr(self, f"{'dep' if side == 'from' else 'arr'}_tz", info["tz"])
            elif getattr(self, f"{side}_name") and not getattr(self, f"{side}_city"):
                city, country = airports.city_of(getattr(self, f"{side}_name"))
                if city:
                    setattr(self, f"{side}_city", city)
                    if not getattr(self, f"{side}_country"):
                        setattr(self, f"{side}_country", country)
                else:
                    setattr(self, f"{side}_city", _city_guess(getattr(self, f"{side}_name")))
        for side in ("from", "to"):                  # one spelling per city (English, as the airport table has it); views translate it
            city = getattr(self, f"{side}_city")
            if city:
                canon, country = airports.city_of(city)
                if canon and fold(canon) == fold(airports.city_name(canon, "en")):
                    setattr(self, f"{side}_city", canon)
                    if not getattr(self, f"{side}_country"):
                        setattr(self, f"{side}_country", country)
        for side, country in (("dep", self.from_country), ("arr", self.to_country)):
            if not getattr(self, f"{side}_tz") and country and airports.country_tz(country):
                setattr(self, f"{side}_tz", airports.country_tz(country))
        if self.kind in (LODGING, CAR, EVENT) and not self.dep_tz:
            self.dep_tz = default_tz
            if self.from_country and airports.country_tz(self.from_country):
                self.dep_tz = airports.country_tz(self.from_country)
        if self.kind == LODGING:
            self.to_name, self.to_city, self.to_country = self.to_name or self.from_name, self.to_city or self.from_city, self.to_country or self.from_country
            self.arr_tz = self.arr_tz or self.dep_tz
        if not self.dep_tz and self.kind in (TRAIN, BUS, FERRY):
            self.dep_tz = default_tz
        if not self.arr_tz:
            self.arr_tz = self.dep_tz or ("" if self.kind == FLIGHT else default_tz)
        for side in ("dep", "arr"):
            local, tz, off = getattr(self, f"{side}_local"), getattr(self, f"{side}_tz"), getattr(self, f"{side}_offset")
            if off is not None and airports.valid_tz(tz) and airports.has_time(local):
                ts = airports.to_ts(local, "", off)
                if ts is not None:
                    setattr(self, f"{side}_local", airports.local_from_ts(ts, tz))
                    setattr(self, f"{side}_offset", None)
        return self


def _first_name(full: str) -> str:
    """Passenger names come as "ANA PEREZ GARCIA" or "Pérez/Ana Ms": keep a capitalised first name only."""
    text = re.sub(r"\b(mr|mrs|ms|miss|mstr|sr|sra|srta|dr|don|doña)\b\.?", "", full or "", flags=re.I).strip()
    if "/" in text:
        text = text.split("/", 1)[1].strip()
    text = re.sub(r"[^A-Za-zÀ-ÿ' \-]", " ", text).split()
    return text[0].capitalize() if text else ""


def _city_guess(name: str) -> str:
    text = re.split(r"[-–,(/]", name or "", maxsplit=1)[0].strip()
    text = re.sub(r"^(estaci[oó]n( de)?|station|gare( de)?|bahnhof|esta[cç][aã]o( de)?)\s+", "", text, flags=re.I)
    return text[:40].strip()
