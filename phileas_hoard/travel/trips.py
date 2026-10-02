"""Group segments into trips.

Automatic grouping is deterministic: the same segments always give the same trips. A segment the user moved by hand is ``locked`` to
its trip and never regrouped; a trip with locked segments is an anchor that free segments close in time join. The rest is grouped
by time (a gap of at most ``gap_days`` between the end of one segment and the start of the next) and cut where the traveller
gets back to where the trip began (the home city, or the first departure city when none is set).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Optional

from . import airports
from .airlines import fold
from .model import CANCELLED, FLIGHT, LODGING, ONGOING, PAST, TRANSPORT, UPCOMING
from .store import TravelStore

OPEN_RETURN_DAYS = 45
MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Home:
    city: str = ""
    airports: frozenset = frozenset()
    tz: str = "Europe/Madrid"

    def is_home(self, seg: dict[str, Any], side: str) -> bool:
        code = (seg.get(f"{side}_code") or "").upper()
        city = fold(seg.get(f"{side}_city") or "")
        if code and code in self.airports:
            return True
        return bool(self.city and city and fold(self.city) == city)


@dataclass
class Result:
    created: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def _d(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


def date_range(start: str, end: str, lang: str = "es") -> str:
    a, b = _d(start), _d(end or start)
    if a is None:
        return ""
    b = b or a
    months = MONTHS_ES if lang == "es" else MONTHS_EN
    if a == b:
        return f"{a.day} {months[a.month - 1]} {a.year}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {months[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day} {months[a.month - 1]} – {b.day} {months[b.month - 1]} {a.year}"
    return f"{a.day} {months[a.month - 1]} {a.year} – {b.day} {months[b.month - 1]} {b.year}"


def destination_of(segs: list[dict[str, Any]], home: Home) -> tuple[str, str]:
    """The main place of the trip: the city with most nights, else the first city reached away from home."""
    nights: dict[str, int] = {}
    country: dict[str, str] = {}
    for s in segs:
        if s.get("kind") == LODGING and s.get("status") != CANCELLED and s.get("from_city"):
            a, b = _d(s.get("start_date") or ""), _d(s.get("end_date") or "")
            nights[s["from_city"]] = nights.get(s["from_city"], 0) + (max(1, (b - a).days) if a and b else 1)
            country[s["from_city"]] = s.get("from_country") or ""
    away = {c: n for c, n in nights.items() if not (home.city and fold(c) == fold(home.city))}
    if away:
        city = max(away, key=lambda c: (away[c], -list(away).index(c)))
        return city, country.get(city, "")
    for s in sorted(segs, key=lambda x: x.get("dep_ts") or 0):
        if s.get("kind") in TRANSPORT and s.get("to_city") and not home.is_home(s, "to"):
            return s["to_city"], s.get("to_country") or ""
    for s in segs:
        city = s.get("to_city") or s.get("from_city")
        if city:
            return city, s.get("to_country") or s.get("from_country") or ""
    return "", ""


def make_title(dest: str, start: str, end: str, lang: str, fallback: str = "") -> str:
    place = airports.city_name(dest, lang) if dest else (fallback or ("Viaje" if lang == "es" else "Trip"))
    rng = date_range(start, end, lang)
    return f"{place} · {rng}" if rng else place


def span(segs: Iterable[dict[str, Any]]) -> tuple[str, str]:
    live = [s for s in segs if s.get("status") != CANCELLED] or list(segs)
    starts = [s["start_date"] for s in live if s.get("start_date")]
    ends = [s.get("end_date") or s.get("start_date") for s in live if s.get("end_date") or s.get("start_date")]
    return (min(starts) if starts else "", max(ends) if ends else "")


def trip_status(trip: dict[str, Any], segs: list[dict[str, Any]], today: date) -> str:
    if trip.get("cancelled") or (segs and all(s.get("status") == CANCELLED for s in segs)):
        return CANCELLED
    a, b = _d(trip.get("start_date") or ""), _d(trip.get("end_date") or "")
    if a is None:
        return UPCOMING
    b = b or a
    if today < a:
        return UPCOMING
    return ONGOING if today <= b else PAST


# ------------------------------------------------------------------ grouping
@dataclass
class _Cluster:
    segs: list[dict[str, Any]] = field(default_factory=list)
    origin: str = ""

    def end(self) -> Optional[date]:
        ends = [_d(s.get("end_date") or s.get("start_date") or "") for s in self.segs]
        ends = [e for e in ends if e]
        return max(ends) if ends else None

    def _transport(self) -> list[dict[str, Any]]:
        # cancelled legs still say where the trip began and ended: cancelling one must not split the trip
        return sorted((s for s in self.segs if s.get("kind") in TRANSPORT), key=lambda s: s.get("dep_ts") or 0)

    def _by_home(self, home: Home) -> bool:
        """Home decides when the cluster touches it; a trip that never involves home (a weekend away from another city) is judged by its own first place."""
        if not (home.city or home.airports):
            return False
        return any(home.is_home(s, "from") or home.is_home(s, "to") for s in self._transport())

    def _first_city(self) -> str:
        transport = self._transport()
        return fold(transport[0].get("from_city") or transport[0].get("from_name") or "") if transport else ""

    def closed(self, home: Home) -> bool:
        """The traveller is back where the trip began."""
        transport = self._transport()
        if not transport:
            return False
        last = transport[-1]
        if self._by_home(home):
            left_home = any(home.is_home(s, "from") and not home.is_home(s, "to") for s in transport)
            return left_home and home.is_home(last, "to")
        first_city = self._first_city()
        return len(transport) >= 2 and bool(first_city) and fold(last.get("to_city") or last.get("to_name") or "") == first_city

    def away(self, home: Home) -> bool:
        """The traveller has left and not come back yet."""
        transport = self._transport()
        if not transport:
            return False
        last = transport[-1]
        if self._by_home(home):
            return any(home.is_home(s, "from") and not home.is_home(s, "to") for s in transport) and not home.is_home(last, "to")
        first_city = self._first_city()
        return bool(first_city) and fold(last.get("to_city") or last.get("to_name") or "") != first_city

    def returns(self, s: dict[str, Any], home: Home) -> bool:
        """Does ``s`` bring the traveller back to where this trip began?"""
        if s.get("kind") not in TRANSPORT:
            return False
        if self._by_home(home):
            return home.is_home(s, "to")
        first_city = self._first_city()
        return bool(first_city) and fold(s.get("to_city") or s.get("to_name") or "") == first_city


def _fits(cluster: _Cluster, s: dict[str, Any], gap: int, home: Home) -> bool:
    end = cluster.end()
    start = _d(s.get("start_date") or "")
    if end is None or start is None:
        return False
    if (start - end).days > gap:
        # a long stay: the way back, even after a quiet spell, belongs to the trip that left
        return (start - end).days <= OPEN_RETURN_DAYS and cluster.away(home) and cluster.returns(s, home)
    if cluster.closed(home):
        # back where the trip began: whatever starts afterwards is another trip (a stay that began before the return still belongs here)
        return start < end and s.get("kind") in (LODGING, "car")
    return True


def cluster_segments(free: list[dict[str, Any]], gap: int, home: Home) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for s in sorted(free, key=lambda x: (x.get("start_date") or "9999", x.get("dep_ts") or 0, x.get("created_ts") or 0)):
        if clusters and _fits(clusters[-1], s, gap, home):
            clusters[-1].segs.append(s)
        else:
            clusters.append(_Cluster([s]))
    return clusters


def regroup(store: TravelStore, *, home: Home, gap_days: int = 2, lang: str = "es", today: Optional[date] = None) -> Result:
    """Rebuild the automatic trips. Returns which trips were created, changed (segments or dates) and removed."""
    result = Result()
    segs = store.segments(include_cancelled=True)
    trips = {t["id"]: t for t in store.trips()}
    before = {tid: (tuple(sorted(s["id"] for s in segs if s.get("trip_id") == tid)), t.get("start_date"), t.get("end_date")) for tid, t in trips.items()}

    anchored: dict[str, list[dict[str, Any]]] = {}
    free: list[dict[str, Any]] = []
    for s in segs:
        if s.get("locked") and s.get("trip_id") in trips:
            anchored.setdefault(s["trip_id"], []).append(s)
        else:
            free.append(s)
    for tid, t in trips.items():
        if t.get("pinned") and tid not in anchored:
            anchored[tid] = []

    assigned: dict[str, str] = {}
    anchor_span = {tid: span(items) for tid, items in anchored.items() if items}
    rest: list[dict[str, Any]] = []
    for s in free:
        start = _d(s.get("start_date") or "")
        target = None
        for tid, (a, b) in anchor_span.items():
            da, db = _d(a), _d(b)
            if start and da and db and da - timedelta(days=gap_days) <= start <= db + timedelta(days=gap_days):
                target = tid
                break
        if target:
            assigned[s["id"]] = target
        else:
            rest.append(s)

    clusters = cluster_segments(rest, gap_days, home)
    claimed: set[str] = set(anchored)
    plan: list[tuple[Optional[str], list[dict[str, Any]]]] = []
    for cluster in sorted(clusters, key=lambda c: -len(c.segs)):
        votes: dict[str, int] = {}
        for s in cluster.segs:
            tid = s.get("trip_id")
            if tid in trips and tid not in claimed:
                votes[tid] = votes.get(tid, 0) + 1
        tid = max(votes, key=lambda k: votes[k]) if votes else None
        if tid:
            claimed.add(tid)
        plan.append((tid, cluster.segs))

    for tid, members in plan:
        start, end = span(members)
        dest, country = destination_of(members, home)
        fields = {"start_date": start, "end_date": end, "destination": dest, "destination_country": country}
        if tid is None:
            fields["title"] = make_title(dest, start, end, lang)
            fields["extra"] = {"auto": True}
            trip = store.create_trip(**fields)
            tid = trip["id"]
            result.created.append(tid)
        else:
            old = trips[tid]
            extra = dict(old.get("extra") or {})
            if not extra.get("title_manual"):
                fields["title"] = make_title(dest, start, end, lang)
            store.update_trip(tid, **fields)
        for s in members:
            if s.get("trip_id") != tid:
                store.update_segment(s["id"], trip_id=tid)
    for sid, tid in assigned.items():
        store.update_segment(sid, trip_id=tid)
    # anchors: refresh their span and destination from everything they hold now
    for tid in anchored:
        members = [s for s in store.segments(trip_id=tid, include_cancelled=True)]
        start, end = span(members)
        dest, country = destination_of(members, home)
        old = trips[tid]
        fields: dict[str, Any] = {"start_date": start, "end_date": end}
        if dest and not old.get("destination"):
            fields.update(destination=dest, destination_country=country)
        if not (old.get("extra") or {}).get("title_manual") and old.get("extra", {}).get("auto") and members:
            fields["title"] = make_title(old.get("destination") or dest, start, end, lang)
        store.update_trip(tid, **fields)

    keep = set(claimed) | {tid for tid, _ in plan if tid} | {r for r in result.created}
    for tid, t in trips.items():
        if tid in keep:
            continue
        has_stuff = store.people(tid) or store.expenses(tid) or t.get("pinned") or t.get("notes")
        if not store.segments(trip_id=tid) and not has_stuff:
            store.delete_trip(tid)
            result.removed.append(tid)
    for tid in {t["id"] for t in store.trips()}:
        now_members = tuple(sorted(s["id"] for s in store.segments(trip_id=tid)))
        t = store.trip(tid)
        if tid in before and (now_members, t.get("start_date"), t.get("end_date")) != before[tid]:
            result.changed.append(tid)
    return result
