"""What every carrier adapter returns, plus the helpers they share."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ..model import (AVAILABLE_FOR_PICKUP, CUSTOMS, DELIVERED, EXCEPTION, FAILED_ATTEMPT, IN_TRANSIT, LABEL_CREATED, NOT_FOUND,
                     OUT_FOR_DELIVERY, RETURNED, UNKNOWN)


@dataclass
class TrackEvent:
    ts: float
    status: str
    description: str
    location: str = ""

    def key(self) -> str:
        return f"{int(self.ts)}|{self.description[:80]}|{self.location[:40]}"


@dataclass
class TrackResult:
    ok: bool                                  # the carrier answered (even "not found")
    source: str                               # adapter id: ups_api, ups_web, correos, dhl_api, track17…
    found: bool = False
    status: str = UNKNOWN
    status_text: str = ""
    events: list[TrackEvent] = field(default_factory=list)
    eta_from: str = ""                        # ISO dates from the carrier
    eta_to: str = ""
    eta_time: str = ""                        # a delivery time window on the day, e.g. "10:45–14:45"
    delivered_ts: Optional[float] = None
    origin_country: str = ""
    origin_city: str = ""
    dest_country: str = ""
    service: str = ""
    carrier: str = ""                         # a more precise carrier if the adapter learnt it (17TRACK)
    error: str = ""
    retry_after_s: Optional[float] = None
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("raw", None)
        return data


def fail(source: str, error: str, retry_after_s: Optional[float] = None) -> TrackResult:
    return TrackResult(ok=False, source=source, error=error[:300], retry_after_s=retry_after_s)


# Free-text status → our status. Used by every adapter whose carrier speaks prose (and as a fallback for codes).
TEXT_STATUS = [
    (RETURNED, r"devuelto|devoluci[oó]n al remitente|return(?:ed)? to (?:sender|shipper)|retour"),
    (DELIVERED, r"\bentregad[oa]\b|delivered|zugestellt|livr[ée]"),
    (AVAILABLE_FOR_PICKUP, r"disposici[oó]n del destinatario|pendiente de recogida|listo para recoger|disponible para (?:su )?recogida|"
                           r"ready for pick ?up|available for pick ?up|access point|punto (?:pack|de recogida)|parcel ?shop|locker"),
    (OUT_FOR_DELIVERY, r"en reparto|out for delivery|con el repartidor|on vehicle for delivery|in zustellung"),
    (FAILED_ATTEMPT, r"ausente|no (?:se ha podido|hemos podido) entregar|intento de entrega|delivery attempt|missed|not delivered"),
    (CUSTOMS, r"aduana|customs|import (?:scan|clearance)|despacho"),
    (EXCEPTION, r"incidencia|excepci[oó]n|exception|retras|delay|address (?:issue|problem)|direcci[oó]n incorrecta|da[ñn]ado|damaged"),
    (LABEL_CREATED, r"prerregistrad|pre-?admisi[oó]n|label created|shipper created a label|order processed|informaci[oó]n recibida|"
                    r"information received|shipment information|datos del env[ií]o recibidos|pending"),
    (IN_TRANSIT, r"tr[aá]nsito|transit|clasificad|admitido|admisi[oó]n|arriv|departed|sal(?:i[oó]|ida)|lleg[oó]|llegada|recogid|"
                 r"picked up|origin scan|processing|procesad|hub|centro (?:log[ií]stico|de tratamiento)|en camino|on the way|"
                 r"loaded|cargado|scan|escaneado"),
]
_TEXT_STATUS = [(s, re.compile(rx, re.I)) for s, rx in TEXT_STATUS]


def status_from_text(text: str, default: str = IN_TRANSIT) -> str:
    for status, rx in _TEXT_STATUS:
        if rx.search(text or ""):
            return status
    return default


def to_ts(value: Any) -> Optional[float]:
    """ISO 8601 (with or without zone), epoch seconds or milliseconds → epoch seconds."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000 if v > 1e11 else v
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()          # local time of this machine
    return dt.timestamp()


def iso_date(value: Any) -> str:
    """Any date-ish value → YYYY-MM-DD ('' when unknown)."""
    if not value:
        return ""
    text = str(value).strip()
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def latest_status(events: list[TrackEvent], fallback: str = UNKNOWN) -> str:
    if not events:
        return fallback
    return max(events, key=lambda e: e.ts).status


def now_utc() -> float:
    return datetime.now(timezone.utc).timestamp()


NOT_FOUND_RESULT = NOT_FOUND
