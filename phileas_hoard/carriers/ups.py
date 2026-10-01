"""UPS: the official Tracking API when you have a (free) developer app, otherwise the public tracking page.

* API: OAuth client credentials (``UPS_CLIENT_ID`` / ``UPS_CLIENT_SECRET``) → ``GET /api/track/v1/details/{number}``.
* Web: the tracking page is opened in the shared off-screen browser and the JSON its own script fetches
  (``webapis.ups.com/track/api/Track/GetStatus``) is read. One page visit per check, never more often than the
  scheduler allows (two hours while in transit). An unknown number answers ``errorCode 504`` (not scanned yet).
"""

from __future__ import annotations

import base64
import re
import secrets
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from ..model import (AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, FAILED_ATTEMPT, IN_TRANSIT, LABEL_CREATED, NOT_FOUND,
                     OUT_FOR_DELIVERY, RETURNED)
from .base import TrackEvent, TrackResult, fail, iso_date, latest_status, status_from_text

API_BASE = "https://onlinetools.ups.com"
WEB_PAGE = "https://www.ups.com/track?loc=es_ES&tracknum={n}&requester=ST/trackdetails"
WEB_MATCH = "/track/api/Track/GetStatus"
API_TYPES = {"D": DELIVERED, "I": IN_TRANSIT, "M": LABEL_CREATED, "MV": LABEL_CREATED, "P": IN_TRANSIT, "X": EXCEPTION, "RS": RETURNED,
             "DO": IN_TRANSIT, "DD": IN_TRANSIT, "W": IN_TRANSIT, "NA": LABEL_CREATED, "O": OUT_FOR_DELIVERY}


# ------------------------------------------------------------------ official API
class UpsApi:
    def __init__(self, client_id: str, client_secret: str, client: httpx.Client, clock=time.time):
        self.client_id, self.client_secret = client_id, client_secret
        self.client = client
        self.clock = clock
        self._token: Optional[tuple[str, float]] = None

    def _bearer(self) -> str:
        if self._token and self._token[1] > self.clock() + 60:
            return self._token[0]
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = self.client.post(f"{API_BASE}/security/v1/oauth/token", data={"grant_type": "client_credentials"},
                                    headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
        response.raise_for_status()
        data = response.json()
        self._token = (data["access_token"], self.clock() + float(data.get("expires_in") or 3600))
        return self._token[0]

    def track(self, number: str) -> TrackResult:
        try:
            token = self._bearer()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return fail("ups_api", f"OAuth failed ({type(exc).__name__}); check UPS_CLIENT_ID/SECRET", 3600)
        try:
            response = self.client.get(f"{API_BASE}/api/track/v1/details/{number}", params={"locale": "es_ES", "returnSignature": "false"},
                                       headers={"Authorization": f"Bearer {token}", "transId": secrets.token_hex(8), "transactionSrc": "phileas"})
        except httpx.HTTPError as exc:
            return fail("ups_api", f"network: {type(exc).__name__}", 1800)
        if response.status_code == 404:
            return TrackResult(ok=True, source="ups_api", status=NOT_FOUND)
        if response.status_code == 429:
            return fail("ups_api", "rate limited", 3600)
        if response.status_code != 200:
            return fail("ups_api", f"http {response.status_code}", 3600)
        try:
            return parse_api(response.json())
        except ValueError:
            return fail("ups_api", "not JSON", 3600)


def _api_ts(date: str, time_: str) -> Optional[float]:
    try:
        return datetime.strptime(f"{date}{(time_ or '000000')[:6].ljust(6, '0')}", "%Y%m%d%H%M%S").astimezone().timestamp()
    except ValueError:
        return None


def parse_api(data: dict[str, Any]) -> TrackResult:
    result = TrackResult(ok=True, source="ups_api", raw=data)
    shipments = ((data or {}).get("trackResponse") or {}).get("shipment") or []
    pkg = ((shipments[0].get("package") or [{}])[0]) if shipments else {}
    if not pkg or (shipments and shipments[0].get("warnings") and not pkg.get("activity")):
        result.status = NOT_FOUND
        return result
    result.found = True
    events = []
    for act in pkg.get("activity") or []:
        st = act.get("status") or {}
        loc = (act.get("location") or {}).get("address") or {}
        ts = _api_ts(act.get("date") or "", act.get("time") or "")
        if ts is None:
            continue
        text = str(st.get("description") or "").strip()
        status = API_TYPES.get(str(st.get("type") or ""), "") or status_from_text(text)
        if status == IN_TRANSIT:
            status = status_from_text(text, IN_TRANSIT)
        where = ", ".join(x for x in (loc.get("city"), loc.get("countryCode")) if x)
        events.append(TrackEvent(ts, status, text, where))
    result.events = events
    current = pkg.get("currentStatus") or {}
    result.status = latest_status(events, NOT_FOUND)
    result.status_text = str(current.get("description") or (max(events, key=lambda e: e.ts).description if events else ""))
    for d in pkg.get("deliveryDate") or []:
        kind = d.get("type")
        if kind in ("SDD", "RDD", "EDD"):
            result.eta_from = result.eta_to = iso_date(d.get("date"))
        if kind == "DEL":
            result.delivered_ts = _api_ts(d.get("date") or "", (pkg.get("deliveryTime") or {}).get("endTime") or "")
    for addr in pkg.get("packageAddress") or []:
        a = addr.get("address") or {}
        if addr.get("type") == "ORIGIN":
            result.origin_country, result.origin_city = a.get("countryCode") or "", a.get("city") or ""
        if addr.get("type") == "DESTINATION":
            result.dest_country = a.get("countryCode") or ""
    result.service = str((pkg.get("service") or {}).get("description") or "")
    return result


# ------------------------------------------------------------------ public page (browser)
def _dmy(a: int, b: int, year: int) -> tuple[int, int, int]:
    """The page is asked for in es_ES, which writes DD/MM/YYYY (its own ``trackedDateTime`` does); a first number above 12
    can only be a day, a second above 12 only a day too (then the page answered MM/DD)."""
    if b > 12 >= a:
        return b, a, year
    return a, b, year


def _web_ts(act: dict[str, Any]) -> Optional[float]:
    gmt_date, gmt_time = str(act.get("gmtDate") or ""), str(act.get("gmtTime") or "")
    if re.fullmatch(r"\d{8}", gmt_date) and re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", gmt_time):
        try:
            from datetime import timezone
            hms = gmt_time if gmt_time.count(":") == 2 else gmt_time + ":00"
            dt = datetime.strptime(gmt_date + hms[:8], "%Y%m%d%H:%M:%S").replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    date, time_ = str(act.get("date") or ""), str(act.get("time") or "")
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", date)
    if not m:
        return None
    day, month, y = _dmy(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    t = re.match(r"(\d{1,2}):(\d{2})\s*([AaPp])?", time_.replace(".", ""))
    hour, minute = (int(t.group(1)), int(t.group(2))) if t else (0, 0)
    if t and t.group(3):
        pm = t.group(3).lower() == "p"
        hour = (hour % 12) + (12 if pm else 0)
    try:
        return datetime(y, month, day, hour, minute).astimezone().timestamp()
    except ValueError:
        return None


def parse_web(data: dict[str, Any]) -> TrackResult:
    result = TrackResult(ok=True, source="ups_web", raw=data)
    details = (data or {}).get("trackDetails") or []
    if not details:
        result.ok = False
        result.error = "no trackDetails in the page answer"
        return result
    d = details[0]
    if str(d.get("errorCode") or "") in ("504", "151018") or (d.get("errorText") and not d.get("shipmentProgressActivities")):
        result.status = NOT_FOUND
        result.status_text = str(d.get("errorText") or "")
        return result
    result.found = True
    events = []
    for act in d.get("shipmentProgressActivities") or []:
        ts = _web_ts(act)
        text = re.sub(r"<[^>]+>", " ", str(act.get("activityScan") or "")).strip()
        if ts is None or not text:
            continue
        loc = str(act.get("location") or "").strip()
        events.append(TrackEvent(ts, status_from_text(text, IN_TRANSIT), text, loc))
    result.events = events
    text = str(d.get("packageStatus") or "")
    status = status_from_text(text, "") or latest_status(events, IN_TRANSIT)
    if d.get("isDelivered"):
        status = DELIVERED
    if (d.get("progressBarType") or "").lower() == "outfordelivery":
        status = OUT_FOR_DELIVERY
    if d.get("isDeliveredToUAP") or d.get("upsAccessPoint") and status != DELIVERED:
        status = AVAILABLE_FOR_PICKUP if not d.get("isPickedUpByCustomer") else DELIVERED
    if d.get("attentionNeeded") and status not in (DELIVERED, OUT_FOR_DELIVERY):
        status = EXCEPTION if "intent" not in text.lower() else FAILED_ATTEMPT
    result.status = status
    result.status_text = text or (max(events, key=lambda e: e.ts).description if events else "")
    sched = d.get("scheduledDeliveryDateDetail") or {}
    eta = sched.get("date") or d.get("scheduledDeliveryDate") or ""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(eta))
    if m:
        day, month, year = _dmy(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        result.eta_from = result.eta_to = f"{year}-{month:02d}-{day:02d}"
    elif eta:
        result.eta_from = result.eta_to = iso_date(eta)
    if status == DELIVERED and events:
        result.delivered_ts = max(e.ts for e in events)
    frm = d.get("shipFromAddress") or {}
    to = d.get("shipToAddress") or {}
    result.origin_country = str(frm.get("country") or frm.get("countryCode") or "")[:2].upper()
    result.origin_city = str(frm.get("city") or "")
    result.dest_country = str(to.get("country") or to.get("countryCode") or "")[:2].upper()
    result.service = str((d.get("additionalInformation") or {}).get("serviceInformation", {}).get("serviceName") or "") \
        if isinstance(d.get("additionalInformation"), dict) else ""
    return result


def track_web(number: str, browser: Any) -> TrackResult:
    if browser is None:
        return fail("ups_web", "browser rung disabled", 6 * 3600)
    ok, why = browser.available()
    if not ok:
        return fail("ups_web", why, 6 * 3600)
    data, error = browser.capture_json(WEB_PAGE.format(n=number), WEB_MATCH, timeout_s=45)
    if data is None:
        return fail("ups_web", error or "the page did not load its tracking data", 3600)
    return parse_web(data)
