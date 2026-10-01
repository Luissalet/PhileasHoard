"""17TRACK: one key for 3,000+ carriers (100 new numbers a month free). ``TRACK17_KEY`` in Settings.

A number is registered once (that spends one unit of quota) and then read with ``gettrackinfo`` as often as needed.
17TRACK fetches from the carrier on its own schedule, so a freshly registered number answers "not found" for a while.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..model import (AVAILABLE_FOR_PICKUP, CUSTOMS, DELIVERED, EXCEPTION, FAILED_ATTEMPT, IN_TRANSIT, LABEL_CREATED, NOT_FOUND,
                     OUT_FOR_DELIVERY, RETURNED)
from .base import TrackEvent, TrackResult, fail, iso_date, latest_status, status_from_text, to_ts

API = "https://api.17track.net/track/v2.2"
STATUS = {"NotFound": NOT_FOUND, "InfoReceived": LABEL_CREATED, "InTransit": IN_TRANSIT, "Expired": EXCEPTION,
          "AvailableForPickup": AVAILABLE_FOR_PICKUP, "OutForDelivery": OUT_FOR_DELIVERY, "DeliveryFailure": FAILED_ATTEMPT,
          "Delivered": DELIVERED, "Exception": EXCEPTION}
SUB = {"InTransit_CustomsProcessing": CUSTOMS, "InTransit_CustomsRequiringInformation": CUSTOMS, "Exception_Returning": RETURNED,
       "Exception_Returned": RETURNED}
# 17TRACK detects the carrier from the number by itself; a wrong carrier code would answer about another parcel,
# so none is sent unless the user sets one explicitly (``carrier17`` in the shipment's extra data).
CARRIER_CODES: dict[str, int] = {}


class Track17:
    def __init__(self, key: str, client: httpx.Client):
        self.key = key
        self.client = client

    def _post(self, path: str, body: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
        try:
            response = self.client.post(f"{API}/{path}", json=body, headers={"17token": self.key, "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            return None, f"network: {type(exc).__name__}"
        if response.status_code == 401:
            return None, "the 17TRACK key was refused"
        if response.status_code != 200:
            return None, f"http {response.status_code}"
        try:
            data = response.json()
        except ValueError:
            return None, "not JSON"
        if data.get("code") not in (0, None):
            return None, f"17TRACK code {data.get('code')}"
        return data, ""

    def register(self, number: str, carrier: str = "") -> tuple[bool, str]:
        item: dict[str, Any] = {"number": number}
        if carrier in CARRIER_CODES:
            item["carrier"] = CARRIER_CODES[carrier]
        data, error = self._post("register", [item])
        if data is None:
            return False, error
        rejected = (data.get("data") or {}).get("rejected") or []
        for r in rejected:
            err = (r.get("error") or {})
            if err.get("code") == -18019901:          # already registered
                return True, ""
            return False, str(err.get("message") or "rejected")[:200]
        return True, ""

    def track(self, number: str, carrier: str = "") -> TrackResult:
        item: dict[str, Any] = {"number": number}
        if carrier in CARRIER_CODES:
            item["carrier"] = CARRIER_CODES[carrier]
        data, error = self._post("gettrackinfo", [item])
        if data is None:
            return fail("track17", error, 3600)
        accepted = (data.get("data") or {}).get("accepted") or []
        if not accepted:
            rejected = (data.get("data") or {}).get("rejected") or []
            code = ((rejected[0].get("error") or {}).get("code") if rejected else None)
            if code == -18019902:                     # not registered yet
                ok, err = self.register(number, carrier)
                if not ok:
                    return fail("track17", err or "register failed", 6 * 3600)
                return TrackResult(ok=True, source="track17", status=NOT_FOUND, status_text="registered in 17TRACK, waiting for data",
                                   retry_after_s=1800)
            return fail("track17", "no answer for this number", 3600)
        return parse(accepted[0])


def parse(item: dict[str, Any]) -> TrackResult:
    info = item.get("track_info") or item
    result = TrackResult(ok=True, source="track17", raw=item)
    latest = info.get("latest_status") or {}
    status = SUB.get(str(latest.get("sub_status") or ""), STATUS.get(str(latest.get("status") or ""), IN_TRANSIT))
    events: list[TrackEvent] = []
    for provider in ((info.get("tracking") or {}).get("providers") or []):
        for e in provider.get("events") or []:
            ts = to_ts(e.get("time_utc") or e.get("time_iso") or e.get("timestamp"))
            if ts is None:
                continue
            text = str(e.get("description") or "").strip()
            st = SUB.get(str(e.get("sub_status") or ""), STATUS.get(str(e.get("stage") or e.get("status") or ""), "")) or status_from_text(text)
            loc = e.get("location") or ""
            if isinstance(loc, dict):
                loc = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
            events.append(TrackEvent(ts, st, text, str(loc)))
        if provider.get("provider", {}).get("name") and not result.service:
            result.service = str(provider["provider"]["name"])
    result.events = events
    result.status = status if status != IN_TRANSIT or not events else latest_status(events, status)
    if status in (DELIVERED, OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP, RETURNED, NOT_FOUND):
        result.status = status
    result.found = result.status != NOT_FOUND
    last = info.get("latest_event") or {}
    result.status_text = str(last.get("description") or (max(events, key=lambda e: e.ts).description if events else ""))
    eta = ((info.get("time_metrics") or {}).get("estimated_delivery_date") or {})
    if isinstance(eta, dict):
        result.eta_from, result.eta_to = iso_date(eta.get("from")), iso_date(eta.get("to") or eta.get("from"))
    else:
        result.eta_from = result.eta_to = iso_date(eta)
    ship = info.get("shipping_info") or {}
    sa, ra = ship.get("shipper_address") or {}, ship.get("recipient_address") or {}
    if isinstance(sa, dict):
        result.origin_country, result.origin_city = str(sa.get("country") or ""), str(sa.get("city") or "")
    if isinstance(ra, dict):
        result.dest_country = str(ra.get("country") or "")
    if result.status == DELIVERED and events:
        result.delivered_ts = max(e.ts for e in events)
    return result
