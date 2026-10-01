"""Correos (Spain): the public JSON the parcel locator of correos.es uses. No key.

``GET https://api1.correos.es/digital-services/searchengines/api/v1/envios?text=<code>&language=ES``
answers ``{shipment: [{events: [{eventDate: dd/mm/yyyy, eventTime, phase, desPhase, summaryText, extendedText}]}]}``,
or 204 when the code is unknown. Times are Spanish local time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from ..model import AVAILABLE_FOR_PICKUP, DELIVERED, IN_TRANSIT, LABEL_CREATED, NOT_FOUND, OUT_FOR_DELIVERY
from .base import TrackEvent, TrackResult, fail, latest_status, status_from_text
from .tz import madrid

URL = "https://api1.correos.es/digital-services/searchengines/api/v1/envios"
PHASES = {"1": LABEL_CREATED, "2": IN_TRANSIT, "3": OUT_FOR_DELIVERY, "4": DELIVERED}


def parse(data: Any) -> TrackResult:
    result = TrackResult(ok=True, source="correos", raw=data)
    shipments = (data or {}).get("shipment") or []
    if not shipments:
        result.status = NOT_FOUND
        return result
    ship = shipments[0]
    err = (ship.get("error") or {}).get("errorCode")
    events = []
    for e in ship.get("events") or []:
        try:
            when = datetime.strptime(f"{e.get('eventDate')} {e.get('eventTime') or '00:00:00'}", "%d/%m/%Y %H:%M:%S").replace(tzinfo=madrid())
        except (TypeError, ValueError):
            continue
        summary = str(e.get("summaryText") or "").strip().rstrip(".")
        extended = str(e.get("extendedText") or "").strip()
        status = status_from_text(f"{summary} {extended}", PHASES.get(str(e.get("phase")), IN_TRANSIT))
        if str(e.get("phase")) == "3" and status == IN_TRANSIT:
            status = OUT_FOR_DELIVERY
        if str(e.get("phase")) == "4":
            status = DELIVERED
        events.append(TrackEvent(ts=when.timestamp(), status=status, description=summary + (f" — {extended}" if extended and extended != summary else ""),
                                 location=""))
    if not events:
        result.status = NOT_FOUND if err not in (None, "", "0") else LABEL_CREATED
        result.found = err in (None, "", "0")
        return result
    result.found = True
    result.events = events
    result.status = latest_status(events)
    last = max(events, key=lambda e: e.ts)
    result.status_text = last.description
    if result.status == DELIVERED:
        result.delivered_ts = last.ts
    result.dest_country = "ES"
    if result.status == AVAILABLE_FOR_PICKUP:
        result.service = "office"
    return result


def track(number: str, client: httpx.Client) -> TrackResult:
    try:
        response = client.get(URL, params={"text": number, "language": "ES"}, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        return fail("correos", f"network: {type(exc).__name__}", 1800)
    if response.status_code == 204:
        return TrackResult(ok=True, source="correos", status=NOT_FOUND)
    if response.status_code != 200:
        return fail("correos", f"http {response.status_code}", 3600)
    try:
        return parse(response.json())
    except ValueError:
        return fail("correos", "not JSON", 3600)
