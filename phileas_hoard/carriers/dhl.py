"""DHL: the official Shipment Tracking – Unified API (free key from developer.dhl.com, ``DHL_API_KEY``).

DHL's website forbids automated reads of its tracking page, so without a key DHL numbers go to 17TRACK (when
configured) or stay with the status the shop's mails give.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..model import AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, IN_TRANSIT, LABEL_CREATED, NOT_FOUND, OUT_FOR_DELIVERY
from .base import TrackEvent, TrackResult, fail, iso_date, latest_status, status_from_text, to_ts

URL = "https://api-eu.dhl.com/track/shipments"
CODES = {"pre-transit": LABEL_CREATED, "transit": IN_TRANSIT, "delivered": DELIVERED, "failure": EXCEPTION, "unknown": IN_TRANSIT}


def _event(e: dict[str, Any]) -> TrackEvent | None:
    ts = to_ts(e.get("timestamp"))
    if ts is None:
        return None
    text = str(e.get("description") or e.get("status") or "").strip()
    loc = ((e.get("location") or {}).get("address") or {})
    where = ", ".join(x for x in (loc.get("addressLocality"), loc.get("countryCode")) if x)
    code = str(e.get("statusCode") or "")
    status = status_from_text(text, CODES.get(code, IN_TRANSIT))
    if code == "delivered":
        status = DELIVERED
    return TrackEvent(ts, status, text, where)


def parse(data: dict[str, Any]) -> TrackResult:
    result = TrackResult(ok=True, source="dhl_api", raw=data)
    shipments = (data or {}).get("shipments") or []
    if not shipments:
        result.status = NOT_FOUND
        return result
    s = shipments[0]
    result.found = True
    events = [ev for ev in (_event(e) for e in s.get("events") or []) if ev]
    current = _event(s.get("status") or {})
    if current and not any(abs(e.ts - current.ts) < 1 and e.description == current.description for e in events):
        events.append(current)
    result.events = events
    result.status = current.status if current else latest_status(events, IN_TRANSIT)
    result.status_text = current.description if current else ""
    frame = s.get("estimatedDeliveryTimeFrame") or {}
    result.eta_from = iso_date(frame.get("estimatedFrom") or s.get("estimatedTimeOfDelivery"))
    result.eta_to = iso_date(frame.get("estimatedThrough") or s.get("estimatedTimeOfDelivery")) or result.eta_from
    if result.status == DELIVERED and events:
        result.delivered_ts = max(e.ts for e in events)
    origin = ((s.get("origin") or {}).get("address") or {})
    dest = ((s.get("destination") or {}).get("address") or {})
    result.origin_country, result.origin_city = origin.get("countryCode") or "", origin.get("addressLocality") or ""
    result.dest_country = dest.get("countryCode") or ""
    result.service = str(s.get("service") or "")
    if "servicepoint" in (result.status_text or "").lower() and result.status != DELIVERED:
        result.status = AVAILABLE_FOR_PICKUP
    if result.status == IN_TRANSIT and "out for delivery" in (result.status_text or "").lower():
        result.status = OUT_FOR_DELIVERY
    return result


def track(number: str, key: str, client: httpx.Client) -> TrackResult:
    try:
        response = client.get(URL, params={"trackingNumber": number, "language": "es"}, headers={"DHL-API-Key": key, "Accept": "application/json"})
    except httpx.HTTPError as exc:
        return fail("dhl_api", f"network: {type(exc).__name__}", 1800)
    if response.status_code == 404:
        return TrackResult(ok=True, source="dhl_api", status=NOT_FOUND)
    if response.status_code in (401, 403):
        return fail("dhl_api", "the DHL key was refused", 6 * 3600)
    if response.status_code == 429:
        return fail("dhl_api", "rate limited", 3600)
    if response.status_code != 200:
        return fail("dhl_api", f"http {response.status_code}", 3600)
    try:
        return parse(response.json())
    except ValueError:
        return fail("dhl_api", "not JSON", 3600)
