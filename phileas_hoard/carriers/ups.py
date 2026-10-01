"""UPS: the official Tracking API when you have a (free) developer app, otherwise the public tracking page.

* API: OAuth client credentials (``UPS_CLIENT_ID`` / ``UPS_CLIENT_SECRET``) → ``GET /api/track/v1/details/{number}``.
* Web: the tracking page is opened in the shared off-screen browser and the JSON its own script fetches
  (``webapis.ups.com/track/api/Track/GetStatus``) is read. One page visit per check, never more often than the
  scheduler allows (two hours while in transit). An unknown number answers ``errorCode 504`` (not scanned yet).
"""

from __future__ import annotations

import base64
import html
import re
import secrets
import time
from datetime import datetime
from typing import Any, Optional

import httpx

from ..model import (AVAILABLE_FOR_PICKUP, CUSTOMS, DELIVERED, EXCEPTION, FAILED_ATTEMPT, IN_TRANSIT, LABEL_CREATED, NOT_FOUND,
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


# The page's milestones (``nameKey``) say where the parcel is better than the free text does.
MILESTONES = {"cms.stapp.orderreceived": LABEL_CREATED, "cms.stapp.wehaveyourpkg": IN_TRANSIT, "cms.stapp.ontheway": IN_TRANSIT,
              "cms.stapp.intransit": IN_TRANSIT, "cms.stapp.outfordelivery": OUT_FOR_DELIVERY, "cms.stapp.delivered": DELIVERED,
              "cms.stapp.readyforpickup": AVAILABLE_FOR_PICKUP, "cms.stapp.returned": RETURNED, "cms.stapp.exception": EXCEPTION}
PROGRESS_BAR = {"labelcreated": LABEL_CREATED, "orderreceived": LABEL_CREATED, "intransit": IN_TRANSIT, "outfordelivery": OUT_FOR_DELIVERY,
                "delivered": DELIVERED, "exception": EXCEPTION, "returned": RETURNED, "readyforpickup": AVAILABLE_FOR_PICKUP}
MONTH_KEYS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
COUNTRIES = {"united kingdom": "GB", "reino unido": "GB", "netherlands": "NL", "países bajos": "NL", "paises bajos": "NL",
             "germany": "DE", "alemania": "DE", "spain": "ES", "españa": "ES", "france": "FR", "francia": "FR", "italy": "IT",
             "italia": "IT", "belgium": "BE", "bélgica": "BE", "poland": "PL", "polonia": "PL", "portugal": "PT", "ireland": "IE",
             "irlanda": "IE", "china": "CN", "united states": "US", "estados unidos": "US", "czech republic": "CZ",
             "república checa": "CZ", "austria": "AT", "switzerland": "CH", "suiza": "CH", "hungary": "HU", "hungría": "HU"}


def country_of(location: str) -> str:
    """ISO code of the country at the end of a UPS location ("Dewsbury, United Kingdom" → GB)."""
    tail = (location or "").split(",")[-1].strip().lower()
    if re.fullmatch(r"[a-z]{2}", tail):
        return tail.upper()
    return COUNTRIES.get(tail, "")


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def _milestone_status(m: dict[str, Any]) -> str:
    key = str(m.get("nameKey") or "").lower()
    if key in MILESTONES:
        return MILESTONES[key]
    return status_from_text(str(m.get("name") or ""), "")


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
        text = _clean(act.get("activityScan"))
        if ts is None or not text:
            continue
        loc = _clean(act.get("location"))
        status = _milestone_status(act.get("milestoneName") or {}) or status_from_text(text, IN_TRANSIT)
        # an exception scan inside a milestone ("En tránsito") is still an exception
        if act.get("exceptionCodes") or status_from_text(text, "") in (EXCEPTION, FAILED_ATTEMPT, RETURNED):
            status = status_from_text(text, EXCEPTION)
        events.append(TrackEvent(ts, status, text, loc))
    result.events = events
    text = _clean(d.get("packageStatus"))
    status = (_milestone_status(d.get("currentMilestone") or {})
              or PROGRESS_BAR.get(str(d.get("progressBarType") or "").lower(), "")
              or latest_status(events, IN_TRANSIT))
    if d.get("isDelivered") or d.get("isPickedUpByCustomer"):
        status = DELIVERED
    elif d.get("isDeliveredToUAP") or (d.get("upsAccessPoint") and status not in (DELIVERED, OUT_FOR_DELIVERY)):
        status = AVAILABLE_FOR_PICKUP
    attention = d.get("attentionNeeded") or {}
    needs = bool(attention.get("actions") or attention.get("isCorrectMyAddress")) if isinstance(attention, dict) else bool(attention)
    if needs and status not in (DELIVERED, OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP):
        status = FAILED_ATTEMPT if re.search(r"intent|attempt", text, re.I) else EXCEPTION
    if events and status == IN_TRANSIT:
        last = max(events, key=lambda e: e.ts)
        if last.status in (EXCEPTION, FAILED_ATTEMPT, RETURNED, CUSTOMS):
            status = last.status
    result.status = status
    result.status_text = text or (max(events, key=lambda e: e.ts).description if events else "")
    # scheduled day: "sdd" YYYYMMDD, else the day/month keys, else a dd/mm/yyyy date
    sdd = str(d.get("sdd") or "")
    sched = d.get("scheduledDeliveryDateDetail") or {}
    if re.fullmatch(r"\d{8}", sdd):
        result.eta_from = result.eta_to = f"{sdd[:4]}-{sdd[4:6]}-{sdd[6:]}"
    elif isinstance(sched, dict) and sched.get("dayNum") and sched.get("monthCMSKey"):
        month = MONTH_KEYS.get(str(sched["monthCMSKey"]).rsplit(".", 1)[-1][:3].lower())
        if month:
            today = datetime.now()
            year = today.year + (1 if month < today.month - 6 else 0)
            result.eta_from = result.eta_to = f"{year}-{month:02d}-{int(sched['dayNum']):02d}"
    else:
        eta = d.get("scheduledDeliveryDate") or ""
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(eta))
        if m:
            day, month, year = _dmy(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            result.eta_from = result.eta_to = f"{year}-{month:02d}-{day:02d}"
    start, end = str(d.get("sdst") or "")[:5], str(d.get("sdt") or "")[:5]
    if re.fullmatch(r"\d{2}:\d{2}", start) and re.fullmatch(r"\d{2}:\d{2}", end):
        result.eta_time = f"{start}–{end}"
    elif re.fullmatch(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", _clean(d.get("packageStatusTime"))):
        result.eta_time = _clean(d.get("packageStatusTime")).replace(" - ", "–")
    if status == DELIVERED and events:
        result.delivered_ts = max(e.ts for e in events)
    frm = d.get("shipFromAddress") or {}
    to = d.get("shipToAddress") or {}
    origin = str(frm.get("country") or frm.get("countryCode") or "")[:2].upper()
    if not origin:
        first = [m.get("location") for m in d.get("milestones") or [] if m.get("location")]
        located = sorted(events, key=lambda e: e.ts)
        origin = country_of(first[0] if first else "") or (country_of(located[0].location) if located else "")
    result.origin_country = origin
    result.origin_city = str(frm.get("city") or "") or (sorted(events, key=lambda e: e.ts)[0].location.split(",")[0] if events else "")
    result.dest_country = str(to.get("country") or to.get("countryCode") or "")[:2].upper()
    info = d.get("additionalInformation") if isinstance(d.get("additionalInformation"), dict) else {}
    result.service = _clean((info.get("serviceInformation") or {}).get("serviceName"))
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
