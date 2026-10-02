"""The family agenda: what Phileas knows is coming, answered to the hub as ``GET /api/family/agenda``.

Real dated things only:

* **delivery** — the expected arrival day (``eta_likely``) of every parcel on its way; a parcel out for delivery is today;
* **deadline** — the last day to pick up a parcel that is waiting at a point (``pickup_deadline``);
* **other** — trips (all-day span from their first to their last day) and the departures of their flights, trains, buses and ferries
  (a moment, in the time zone of the departure place when known).

Nothing that is over is listed (delivered and returned parcels, trips that ended, departures that left) and a parcel that is late stays
on its expected day so the hub shows it as overdue. ``provider(...)`` is what ``fam_agenda.install_fastapi`` calls; it never raises.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import numbers
from .model import ACTIVE, AVAILABLE_FOR_PICKUP, OUT_FOR_DELIVERY, label as status_label
from .travel import trips as tripslib
from .travel.model import CANCELLED, PAST, TRANSPORT, kind_label

MAX_ITEMS = 300


def _day(value: Any) -> str:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def _inside(day: str, date_from: date, date_to: date) -> bool:
    return bool(day) and date_from <= date.fromisoformat(day) <= date_to


def _parcel_items(svc: Any, date_from: date, date_to: date, today: date, base: str, lang: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for s in svc.store.shipments(archived=False, history_only=False, active=True, limit=500):
        if s.get("status") not in ACTIVE:
            continue
        name = (s.get("label") or s.get("item") or s.get("merchant") or s.get("tracking_number") or "").strip()
        if not name:
            continue
        url = f"{base}/#/envio/{quote(s['id'])}"
        carrier = numbers.carrier_name(s.get("carrier") or "")
        status = s.get("status") or ""
        if status == AVAILABLE_FOR_PICKUP:
            deadline = _day(s.get("pickup_deadline"))
            if _inside(deadline, date_from, date_to):
                where = " · ".join(x for x in (s.get("pickup_place"), f"code {s['pickup_code']}" if s.get("pickup_code") else "") if x)
                items.append({"id": f"phileas:deadline:{s['id']}", "title": ("Recoger: " if lang == "es" else "Pick up: ") + name, "start": deadline,
                              "all_day": True, "kind": "deadline", "priority": "high", "url": url, "detail": (where or carrier)[:240]})
            continue
        if status == OUT_FOR_DELIVERY:
            day, priority = today.isoformat(), "high"
        else:
            day, priority = _day(s.get("eta_likely")), "normal"
            if day and date.fromisoformat(day) < today:
                priority = "high"                                   # late: the hub lists it as overdue
        if not _inside(day, date_from, date_to):
            continue
        bits = [carrier, status_label(status, lang)]
        if s.get("eta_from") and s.get("eta_to") and s["eta_from"] != s["eta_to"]:
            bits.append(f"{s['eta_from']} → {s['eta_to']}")
        items.append({"id": f"phileas:delivery:{s['id']}", "title": name, "start": day, "all_day": True, "kind": "delivery",
                      "priority": priority, "url": url, "detail": " · ".join(b for b in bits if b)[:240]})
    return items


def _moment(seg: dict[str, Any]) -> str:
    """The departure as an ISO date-time: with the offset of the departure place when its time zone is known, local otherwise."""
    local = str(seg.get("dep_local") or "").strip()
    if not local:
        return ""
    stamp = seg.get("dep_ts")
    zone = str(seg.get("dep_tz") or "")
    if stamp and zone:
        try:
            return datetime.fromtimestamp(float(stamp), tz=ZoneInfo(zone)).isoformat(timespec="seconds")
        except Exception:  # noqa: BLE001 - an unknown zone: the local time stands
            pass
    try:
        return datetime.fromisoformat(local).isoformat(timespec="seconds")
    except ValueError:
        return _day(local)


def _trip_items(svc: Any, date_from: date, date_to: date, today: date, base: str, lang: str, now_ts: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        if not svc.travel.cfg().enabled:
            return items
        trips = svc.tstore.trips(include_history=False)
    except Exception:  # noqa: BLE001 - the travel facet is optional
        return items
    for trip in trips:
        segs = [g for g in svc.tstore.segments(trip_id=trip["id"], include_cancelled=False)]
        if trip.get("cancelled") or tripslib.trip_status(trip, segs, today) in (CANCELLED, PAST):
            continue
        start, end = _day(trip.get("start_date")), _day(trip.get("end_date")) or _day(trip.get("start_date"))
        url = f"{base}/#/viaje/{quote(trip['id'])}"
        title = (trip.get("title") or trip.get("destination") or "").strip()
        if title and start and date.fromisoformat(start) <= date_to and date.fromisoformat(end) >= date_from:
            item = {"id": f"phileas:trip:{trip['id']}", "title": title, "start": start, "all_day": True, "kind": "other",
                    "priority": "normal", "url": url, "detail": (trip.get("destination") or "")[:240]}
            if end != start:
                item["end"] = end
            items.append(item)
        for seg in segs:
            if seg.get("kind") not in TRANSPORT or (seg.get("dep_ts") and float(seg["dep_ts"]) < now_ts):
                continue
            when = _moment(seg)
            if not when or not _inside(when[:10], date_from, date_to):
                continue
            route = " → ".join(x for x in (seg.get("from_code") or seg.get("from_city"), seg.get("to_code") or seg.get("to_city")) if x)
            name = " ".join(x for x in (kind_label(seg["kind"], lang), seg.get("number") or seg.get("carrier"), route) if x)
            items.append({"id": f"phileas:segment:{seg['id']}", "title": name[:200], "start": when, "all_day": False, "kind": "other",
                          "priority": "normal", "url": url, "detail": " · ".join(x for x in (title, seg.get("booking_ref")) if x)[:240]})
    return items


def build_items(svc: Any, date_from: date, date_to: date, *, base_url: str) -> list[dict[str, Any]]:
    today = datetime.fromtimestamp(svc.clock()).date()
    lang = "en" if svc.setting("ui.language") == "en" else "es"
    items = _parcel_items(svc, date_from, date_to, today, base_url, lang)
    items += _trip_items(svc, date_from, date_to, today, base_url, lang, float(svc.clock()))
    items.sort(key=lambda i: (i["start"], i["title"]))
    return items[:MAX_ITEMS]


def make_provider(get_services: Callable[[], Any], base_url: Callable[[], str]) -> Callable[[date, date, str], list[dict[str, Any]]]:
    """``provider(date_from, date_to, sphere)`` for ``fam_agenda.install_fastapi``; ``sphere`` is ignored (Phileas has no spheres)."""
    def provider(date_from: date, date_to: date, sphere: str) -> list[dict[str, Any]]:
        svc = get_services()
        if svc is None:
            return []
        return build_items(svc, date_from, date_to, base_url=base_url())
    return provider
