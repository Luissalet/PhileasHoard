"""What the tools and the screens ask of the travel facet: views of trips and segments, and every edit the user can make."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from ..errors import PhileasError
from . import airports, checkin, expenses as exp, hubcalls, ics, notices, segments as seglib, trips as tripslib
from .airlines import fold
from .draft import SegmentDraft
from .model import (CANCELLED, CAR, CONFIRMED, EVENT, EXPENSE_CATEGORIES, FLIGHT, KINDS, LODGING, ONGOING, PAST, SPLIT_MODES, TRANSPORT, UPCOMING, kind_label)

SEGMENT_INPUT = ("kind", "booking_ref", "carrier", "carrier_code", "number", "provider", "from_code", "from_name", "from_city", "from_country", "to_code",
                 "to_name", "to_city", "to_country", "dep_local", "dep_tz", "arr_local", "arr_tz", "terminal", "gate", "seat", "coach", "travel_class",
                 "passengers", "price", "currency", "address", "notes", "links", "status")
CATEGORY_OF_KIND = {"flight": "transport", "train": "transport", "bus": "transport", "ferry": "transport", "car": "transport", "lodging": "lodging", "event": "activities"}


def _local(value: str) -> str:
    value = (value or "").strip().replace(" ", "T")
    if value and airports.parse_local(value) is None:
        raise PhileasError("invalid", f"{value!r} is not a date and time.", "Use YYYY-MM-DD or YYYY-MM-DDTHH:MM (local time at the place).")
    return value[:16]


class Ops:
    # ================================================================== views
    def segment_view(self, seg: dict[str, Any], cfg: Any = None, now: Optional[float] = None) -> dict[str, Any]:
        cfg = cfg or self.cfg()
        now = self.now() if now is None else now
        lang = cfg.lang
        out = dict(seg)
        out["kind_label"] = kind_label(seg["kind"], lang)
        out["label"] = notices.label(seg, lang)
        out["from_city_label"] = airports.city_name(seg.get("from_city") or "", lang)
        out["to_city_label"] = airports.city_name(seg.get("to_city") or "", lang)
        out["has_time"] = airports.has_time(seg.get("dep_local") or "")
        if seg["kind"] == FLIGHT:
            out["checkin"] = checkin.state(seg, now)
        out["mails"] = [{k: m.get(k) for k in ("message_id", "ts", "role", "subject", "from_address")} for m in self.t.mails_of_segment(seg["id"])]
        return out

    def timeline(self, trip: dict[str, Any], segs: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
        start, end = tripslib._d(trip.get("start_date") or ""), tripslib._d(trip.get("end_date") or "")
        if not start or not end:
            return []
        end = min(end, start + timedelta(days=120))
        days: dict[str, list[dict[str, Any]]] = {}
        d = start
        while d <= end:
            days[d.isoformat()] = []
            d += timedelta(days=1)

        def add(day: str, role: str, seg: dict[str, Any], time_: str = "") -> None:
            if day in days:
                days[day].append({"role": role, "segment_id": seg["id"], "kind": seg["kind"], "label": notices.label(seg, lang), "time": time_,
                                  "cancelled": seg["status"] == CANCELLED})

        for seg in segs:
            a, b = seg.get("start_date") or "", seg.get("end_date") or seg.get("start_date") or ""
            if seg["kind"] == LODGING:
                add(a, "checkin", seg, notices.hhmm(seg.get("dep_local") or ""))
                x = tripslib._d(a)
                while x and tripslib._d(b) and x + timedelta(days=1) < tripslib._d(b):
                    x += timedelta(days=1)
                    add(x.isoformat(), "stay", seg)
                if b != a:
                    add(b, "checkout", seg, notices.hhmm(seg.get("arr_local") or ""))
            elif seg["kind"] == CAR:
                add(a, "pickup", seg, notices.hhmm(seg.get("dep_local") or ""))
                if b != a:
                    add(b, "dropoff", seg, notices.hhmm(seg.get("arr_local") or ""))
            elif seg["kind"] == EVENT:
                add(a, "event", seg, notices.hhmm(seg.get("dep_local") or ""))
            else:
                add(a, "departs", seg, notices.hhmm(seg.get("dep_local") or ""))
                if b and b != a:
                    add(b, "arrives", seg, notices.hhmm(seg.get("arr_local") or ""))
        order = {"checkout": 0, "arrives": 1, "stay": 2, "pickup": 3, "departs": 4, "event": 4, "checkin": 5, "dropoff": 6}
        return [{"date": day, "items": sorted(items, key=lambda i: (i["time"] or "99:99", order.get(i["role"], 9)))} for day, items in days.items()]

    def trip_card(self, trip: dict[str, Any], cfg: Any = None, segs: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        cfg = cfg or self.cfg()
        segs = self.t.segments(trip_id=trip["id"]) if segs is None else segs
        today = self.today(cfg)
        status = tripslib.trip_status(trip, segs, today)
        start = tripslib._d(trip.get("start_date") or "")
        live = [s for s in segs if s["status"] != CANCELLED]
        nxt = min((s for s in live if (s.get("dep_ts") or 0) >= self.now() and s["kind"] in TRANSPORT), key=lambda s: s["dep_ts"], default=None)
        return {"id": trip["id"], "title": trip.get("title") or "", "destination": trip.get("destination") or "",
                "destination_label": airports.city_name(trip.get("destination") or "", cfg.lang), "destination_country": trip.get("destination_country") or "",
                "start_date": trip.get("start_date") or "", "end_date": trip.get("end_date") or "", "status": status, "currency": trip.get("currency") or "EUR",
                "days_to_go": (start - today).days if start and status == UPCOMING else None, "pinned": trip.get("pinned"), "muted": trip.get("muted"),
                "cancelled": trip.get("cancelled"), "notes": trip.get("notes") or "", "segments": len(segs), "active_segments": len(live),
                "kinds": sorted({s["kind"] for s in live}), "needs_review": sum(1 for s in segs if s.get("needs_review")),
                "next": ({"id": nxt["id"], "label": notices.label(nxt, cfg.lang), "dep_local": nxt.get("dep_local")} if nxt else None),
                "docs": (trip.get("extra") or {}).get("docs"), "history_only": trip.get("history_only"),
                "expenses": len(self.t.expenses(trip["id"]))}

    def trip_detail(self, key: str) -> dict[str, Any]:
        cfg = self.cfg()
        trip = self.t.find_trip(key)
        segs = self.t.segments(trip_id=trip["id"])
        now = self.now()
        views = [self.segment_view(s, cfg, now) for s in segs]
        card = self.trip_card(trip, cfg, segs)
        links = []
        for s in segs:
            for x in s.get("links") or []:
                if not any(y["url"] == x["url"] for y in links):
                    links.append({**x, "segment_id": s["id"], "segment": notices.label(s, cfg.lang)})
        people = self.t.people(trip["id"])
        passengers = sorted({p for s in segs for p in s.get("passengers") or []})
        return {"trip": card, "segments": views, "timeline": self.timeline(trip, segs, cfg.lang), "links": links,
                "people": people, "suggested_people": [p for p in passengers if fold(p) not in {fold(x["name"]) for x in people}],
                "expenses": self.expenses_view(trip["id"]), "mails": self._trip_mails(segs), "unassigned_hint": len(self.t.segments(unassigned=True))}

    def _trip_mails(self, segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for s in segs:
            for m in self.t.mails_of_segment(s["id"]):
                seen.setdefault(m["message_id"], {k: m.get(k) for k in ("message_id", "ts", "subject", "from_address", "role")})
        return sorted(seen.values(), key=lambda m: m.get("ts") or 0)

    def trips_list(self, which: str = "upcoming") -> list[dict[str, Any]]:
        cfg = self.cfg()
        today = self.today(cfg)
        out = []
        for trip in self.t.trips():
            card = self.trip_card(trip, cfg)
            if which == "all" or card["status"] == which or (which == "active" and card["status"] in (UPCOMING, ONGOING)):
                out.append(card)
        out.sort(key=lambda c: c["start_date"] or "9999", reverse=(which in (PAST, CANCELLED)))
        return out

    def overview(self) -> dict[str, Any]:
        cfg = self.cfg()
        now = self.now()
        today = self.today(cfg)
        cards = [self.trip_card(t, cfg) for t in self.t.trips()]
        ongoing = [c for c in cards if c["status"] == ONGOING]
        upcoming = sorted((c for c in cards if c["status"] == UPCOMING), key=lambda c: c["start_date"])
        today_items = []
        for c in ongoing:
            tl = self.timeline(self.t.trip(c["id"]), self.t.segments(trip_id=c["id"]), cfg.lang)
            today_items.append({"trip_id": c["id"], "title": c["title"], "items": next((d["items"] for d in tl if d["date"] == today.isoformat()), [])})
        checkins = []
        for s in self.t.segments(include_cancelled=False):
            if s["kind"] == FLIGHT and s.get("dep_ts") and now < s["dep_ts"] <= now + 3 * 86400 and not s.get("checkin_done"):
                st = checkin.state(s, now)
                if st.get("state") in ("open", "unknown_open", "not_open"):
                    checkins.append({"segment_id": s["id"], "trip_id": s.get("trip_id"), "label": notices.label(s, cfg.lang), "dep_local": s.get("dep_local"),
                                     "state": st["state"], "opens_ts": st.get("opens_ts"), "closes_ts": st.get("closes_ts"), "airline": st.get("airline")})
        review_mails = len(self.store.mails(kind=["travel"], state=["new"], limit=500))
        return {"today": today.isoformat(), "enabled": cfg.enabled, "ongoing": ongoing, "today_items": today_items, "next_trip": upcoming[0] if upcoming else None,
                "upcoming": upcoming[:10], "checkins": sorted(checkins, key=lambda c: c.get("opens_ts") or 0),
                "needs_review": {"mails": review_mails, "segments": sum(c["needs_review"] for c in cards if c["status"] in (UPCOMING, ONGOING))},
                "counts": {"upcoming": len(upcoming), "ongoing": len(ongoing), "past": sum(1 for c in cards if c["status"] == PAST),
                           "cancelled": sum(1 for c in cards if c["status"] == CANCELLED), "unassigned_segments": len(self.t.segments(unassigned=True))},
                "home": {"city": cfg.home.city, "airports": sorted(cfg.home.airports), "tz": cfg.home.tz}, "kinds": sorted(cfg.kinds)}

    def mails_list(self, state: str = "new", limit: int = 30) -> list[dict[str, Any]]:
        rows = self.store.mails(kind=["travel"], state=None if state == "all" else [state], limit=limit)
        out = []
        for m in rows:
            f = m.get("facts") or {}
            out.append({"message_id": m["message_id"], "ts": m.get("ts"), "from_address": m.get("from_address"), "subject": m.get("subject"), "state": m.get("state"),
                        "score": m.get("score"), "snippet": m.get("snippet"), "source": f.get("source"), "sender": f.get("sender"), "change": f.get("change"),
                        "ref": f.get("ref"), "reasons": f.get("reasons"), "model": f.get("model"),
                        "read": [{k: d.get(k) for k in ("kind", "number", "from_code", "from_name", "to_code", "to_name", "dep_local", "arr_local", "booking_ref",
                                                        "confidence", "source", "evidence")} for d in f.get("drafts") or []],
                        "segments": self.t.segments_of_mail(m["message_id"])})
        return out

    # ================================================================== trips
    def create_trip(self, title: str, start_date: str = "", end_date: str = "", currency: str = "EUR", notes: str = "") -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise PhileasError("invalid", "A trip needs a title.")
        trip = self.t.create_trip(title=title[:120], start_date=start_date[:10], end_date=(end_date or start_date)[:10], currency=currency.upper()[:3] or "EUR",
                                  notes=notes[:4000], pinned=True, extra={"manual": True, "title_manual": True})
        return self.trip_detail(trip["id"])

    def update_trip(self, key: str, **f: Any) -> dict[str, Any]:
        trip = self.t.find_trip(key)
        updates: dict[str, Any] = {}
        extra = dict(trip.get("extra") or {})
        if f.get("title") is not None:
            title = str(f["title"]).strip()
            if title:
                updates["title"] = title[:120]
                extra["title_manual"] = True
            else:
                extra.pop("title_manual", None)               # an empty title gives the automatic one back
                updates["title"] = tripslib.make_title(trip.get("destination") or "", trip.get("start_date") or "", trip.get("end_date") or "", self.cfg().lang)
        for k in ("notes", "currency", "pinned", "muted", "cancelled"):
            if f.get(k) is not None:
                updates[k] = (str(f[k]).upper()[:3] if k == "currency" else str(f[k])[:4000]) if k in ("currency", "notes") else bool(f[k])
        if f.get("currency") and self.t.expenses(trip["id"]) and f["currency"].upper() != trip.get("currency"):
            raise PhileasError("invalid", "The trip already has expenses in its base currency.", "Change expense currencies first or keep the trip currency.")
        updates["extra"] = extra
        self.t.update_trip(trip["id"], **updates)
        if f.get("title") is not None:
            self.regroup(quiet=True)
        return self.trip_detail(trip["id"])

    def delete_trip(self, key: str, keep_segments: bool = False) -> dict[str, Any]:
        """Delete a trip with its bookings (remembered as deleted, so a later read of the same mail does not bring them back). With
        ``keep_segments`` the bookings stay, detached from any trip and marked "no trip" so the grouping leaves them alone."""
        trip = self.t.find_trip(key)
        lang = self.cfg().lang
        segs = self.t.segments(trip_id=trip["id"], include_cancelled=True)
        for s in segs:
            if keep_segments:
                self.t.update_segment(s["id"], trip_id=None, locked=False, extra={**(s.get("extra") or {}), "no_trip": True})
            else:
                self.t.forget_segment(s, notices.label(s, lang))
                self.t.delete_segment(s["id"])
        self.t.delete_trip(trip["id"])
        self.regroup(quiet=True)
        return {"deleted": trip["id"], "title": trip.get("title"), "segments_deleted": 0 if keep_segments else len(segs),
                "segments_kept": len(segs) if keep_segments else 0}

    def merge_trips(self, keep_key: str, drop_key: str) -> dict[str, Any]:
        keep, drop = self.t.find_trip(keep_key), self.t.find_trip(drop_key)
        if keep["id"] == drop["id"]:
            raise PhileasError("invalid", "Those are the same trip.")
        for s in self.t.segments(trip_id=drop["id"]):
            self.t.update_segment(s["id"], trip_id=keep["id"], locked=True)
        for s in self.t.segments(trip_id=keep["id"]):
            if not s.get("locked"):
                self.t.update_segment(s["id"], locked=True)
        mapping: dict[str, str] = {}
        mine = {fold(p["name"]): p for p in self.t.people(keep["id"])}
        for p in self.t.people(drop["id"]):
            hit = mine.get(fold(p["name"]))
            if hit is None:
                hit = self.t.add_person(keep["id"], p["name"], is_me=p["is_me"] and not any(x["is_me"] for x in mine.values()))
                mine[fold(p["name"])] = hit
            mapping[p["id"]] = hit["id"]
        for e in self.t.expenses(drop["id"]):
            split = {k: ({mapping.get(i, i): v for i, v in val.items()} if isinstance(val, dict) else [mapping.get(i, i) for i in val]) for k, val in (e.get("split") or {}).items()}
            self.t._set_expense_trip(e["id"], keep["id"], mapping.get(e["payer_id"], e["payer_id"]), split)
        notes = "\n".join(x for x in (keep.get("notes"), drop.get("notes")) if x)
        self.t.update_trip(keep["id"], notes=notes, pinned=True)
        self.t.delete_trip(drop["id"])
        self.regroup(quiet=True)
        return self.trip_detail(keep["id"])

    def split_trip(self, key: str, segment_ids: list[str], title: str = "") -> dict[str, Any]:
        trip = self.t.find_trip(key)
        mine = {s["id"] for s in self.t.segments(trip_id=trip["id"])}
        chosen = [sid for sid in dict.fromkeys(segment_ids) if sid in mine]
        if not chosen or len(chosen) == len(mine):
            raise PhileasError("invalid", "Pick some, but not all, of the trip's segments to split off.", "Segment ids are in trip_get.")
        for sid in mine - set(chosen):
            self.t.update_segment(sid, locked=True)
        moved = self.t.segments_by_ids(chosen)
        start, end = tripslib.span(moved)
        dest, country = tripslib.destination_of(moved, self.cfg().home)
        new = self.t.create_trip(title=title.strip()[:120] or tripslib.make_title(dest, start, end, self.cfg().lang), destination=dest, destination_country=country,
                                 start_date=start, end_date=end, currency=trip.get("currency") or "EUR",
                                 extra={"manual": True, "title_manual": bool(title.strip())})
        for sid in chosen:
            self.t.update_segment(sid, trip_id=new["id"], locked=True)
        self.regroup(quiet=True)
        return {"original": self.trip_detail(trip["id"])["trip"], "new": self.trip_detail(new["id"])["trip"]}

    # ================================================================== segments
    def _draft_from_fields(self, f: dict[str, Any]) -> SegmentDraft:
        data = {k: f[k] for k in SEGMENT_INPUT if f.get(k) is not None}
        for k in ("dep_local", "arr_local"):
            if k in data:
                data[k] = _local(str(data[k]))
        if data.get("kind") not in KINDS:
            raise PhileasError("invalid", f"kind must be one of {', '.join(KINDS)}.")
        if "passengers" in data and isinstance(data["passengers"], str):
            data["passengers"] = [x.strip() for x in data["passengers"].split(",") if x.strip()]
        d = SegmentDraft.from_dict(data)
        d.source, d.confidence = "manual", 100
        d.enrich(self.cfg().home.tz)
        if d.kind == LODGING and not d.provider:
            d.provider = d.from_name
        return d

    def add_segment(self, trip: str = "", **f: Any) -> dict[str, Any]:
        d = self._draft_from_fields(f)
        if not d.usable():
            raise PhileasError("invalid", "A segment needs its kind, a start date and a place: from and to for transport, a name for stays and rentals.",
                               "dep_local is YYYY-MM-DD or YYYY-MM-DDTHH:MM, local time at the place.")
        row = seglib.row_from_draft(d, self.cfg().home.tz)
        row.update(needs_review=False, edited=True, locked=False, last_change_ts=self.now())
        self.t.unforget(row)                                      # adding it by hand again is a decision too
        if trip:
            row.update(trip_id=self.t.find_trip(trip)["id"], locked=True)
        seg = self.t.create_segment(**row)
        self.regroup(quiet=True)
        return {"segment": self.segment_view(self.t.segment(seg["id"])), "trip": self.trip_card(self.t.trip(self.t.segment(seg["id"])["trip_id"]))
                if self.t.segment(seg["id"]).get("trip_id") else None}

    def update_segment(self, sid: str, **f: Any) -> dict[str, Any]:
        seg = self.t.segment(sid)
        patch = {k: v for k, v in f.items() if k in SEGMENT_INPUT and v is not None}
        if "kind" in patch and patch["kind"] != seg["kind"]:
            raise PhileasError("invalid", "A segment cannot change kind.", "Delete it and add a new one.")
        merged = {**seg}
        for side in ("from", "to"):
            side_tz = "dep_tz" if side == "from" else "arr_tz"
            if patch.get(f"{side}_code") is not None and patch[f"{side}_code"].upper() != (seg.get(f"{side}_code") or ""):
                for k in (f"{side}_city", f"{side}_country", f"{side}_name"):
                    if k not in patch:
                        merged[k] = ""
                if side_tz not in patch:
                    merged[side_tz] = ""
        merged.update(patch)
        for k in ("dep_local", "arr_local"):
            if k in patch:
                merged[k] = _local(str(patch[k]))
        merged["dep_offset"] = merged["arr_offset"] = None if any(k in patch for k in ("dep_local", "arr_local")) else merged.get("dep_offset")
        d = SegmentDraft.from_dict({**merged, "passengers": merged.get("passengers") or []})
        d.enrich(self.cfg().home.tz)
        if not d.usable():
            raise PhileasError("invalid", "That edit would leave the segment without a date or a place.")
        row = seglib.derive({**merged, **{k: getattr(d, k) for k in SEGMENT_INPUT if k != "status" and hasattr(d, k)}}, self.cfg().home.tz)
        changes = {k: row[k] for k in list(SEGMENT_INPUT) + ["start_date", "end_date", "dep_ts", "arr_ts"] if k in row and row[k] != seg.get(k)}
        changes.update(edited=True, needs_review=False)
        if "dep_local" in changes or "arr_local" in changes or "dep_tz" in changes:
            changes["checkin_done"] = seg.get("checkin_done", False)
        self.t.update_segment(sid, **changes)
        self.regroup(quiet=True)
        return {"segment": self.segment_view(self.t.segment(sid))}

    def delete_segment(self, sid: str) -> dict[str, Any]:
        seg = self.t.segment(sid)
        label = notices.label(seg, self.cfg().lang)
        self.t.forget_segment(seg, label)
        self.t.delete_segment(sid)
        self.regroup(quiet=True)
        return {"deleted": sid, "label": label}

    def move_segment(self, sid: str, trip: Optional[str]) -> dict[str, Any]:
        """``trip``: a trip id or title, ``"new"`` for a trip of its own, or empty to let the grouping place it again."""
        seg = self.t.segment(sid)
        cfg = self.cfg()
        if (seg.get("extra") or {}).get("no_trip"):
            self.t.update_segment(sid, extra={k: v for k, v in (seg.get("extra") or {}).items() if k != "no_trip"})
        if trip == "new":
            start, end = tripslib.span([seg])
            dest, country = tripslib.destination_of([seg], cfg.home)
            target = self.t.create_trip(title=tripslib.make_title(dest, start, end, cfg.lang), destination=dest, destination_country=country, start_date=start,
                                        end_date=end, extra={"manual": True})
            self.t.update_segment(sid, trip_id=target["id"], locked=True)
        elif trip:
            target = self.t.find_trip(trip)
            self.t.update_segment(sid, trip_id=target["id"], locked=True)
        else:
            self.t.update_segment(sid, trip_id=None, locked=False)
        self.regroup(quiet=True)
        fresh = self.t.segment(sid)
        return {"segment": self.segment_view(fresh), "trip": self.trip_card(self.t.trip(fresh["trip_id"])) if fresh.get("trip_id") else None}

    def set_checkin_done(self, sid: str, done: bool = True) -> dict[str, Any]:
        seg = self.t.segment(sid)
        if seg["kind"] != FLIGHT:
            raise PhileasError("invalid", "Check-in only applies to flights.")
        self.t.update_segment(sid, checkin_done=bool(done), checkin_done_ts=self.now() if done else None)
        return {"segment": self.segment_view(self.t.segment(sid))}

    def checkin_status(self, trip: str = "") -> dict[str, Any]:
        cfg = self.cfg()
        now = self.now()
        rows = []
        for s in self.t.segments(trip_id=self.t.find_trip(trip)["id"] if trip else None, include_cancelled=False):
            if s["kind"] != FLIGHT or not s.get("dep_ts") or s["dep_ts"] < now - 3600:
                continue
            if not trip and s["dep_ts"] > now + 45 * 86400:
                continue
            st = checkin.state(s, now)
            rows.append({"segment_id": s["id"], "trip_id": s.get("trip_id"), "label": notices.label(s, cfg.lang), "dep_local": s["dep_local"], "dep_tz": s.get("dep_tz"),
                         "state": st.get("state"), "known_rule": st.get("known"), "airline": st.get("airline"), "opens_ts": st.get("opens_ts"), "closes_ts": st.get("closes_ts"),
                         "rule": st.get("note_es" if cfg.lang == "es" else "note_en"), "source": st.get("source"), "checked": st.get("checked"),
                         "link": next((x["url"] for x in s.get("links") or [] if x.get("kind") == "checkin"), ""), "done": bool(s.get("checkin_done"))})
        return {"flights": rows, "table": checkin.table(), "now": now}

    # ================================================================== documents (Kafka)
    def docs_check(self, key: str) -> dict[str, Any]:
        trip = self.t.find_trip(key)
        segs = self.t.segments(trip_id=trip["id"], include_cancelled=False)
        if self.call is None:
            return {"trip": trip["id"], "status": "unknown", "reason": "no_hub", "documents": [], "problems": []}
        result = hubcalls.check_trip_documents(self.call, trip, segs)
        extra = dict(trip.get("extra") or {})
        extra["docs_checked_ts"] = self.now()
        extra["docs"] = {k: result.get(k) for k in ("status", "reason", "return_date")}
        self.t.update_trip(trip["id"], extra=extra)
        return result

    # ================================================================== calendar
    def ics(self, trip: str = "", *, include_cancelled: bool = False) -> dict[str, Any]:
        cfg = self.cfg()
        if trip:
            t = self.t.find_trip(trip)
            items = [(t, self.t.segments(trip_id=t["id"]))]
            name = t.get("title") or "Viaje"
        else:
            today = self.today(cfg)
            items = []
            for t in self.t.trips():
                segs = self.t.segments(trip_id=t["id"])
                if tripslib.trip_status(t, segs, today) in (UPCOMING, ONGOING):
                    items.append((t, segs))
            name = "Viajes próximos" if cfg.lang == "es" else "Upcoming trips"
        text = ics.build(items, now=self.now(), lang=cfg.lang, name=name, include_cancelled=include_cancelled)
        return {"filename": re.sub(r"[^A-Za-z0-9_-]+", "-", fold(name)).strip("-")[:60] + ".ics", "events": text.count("BEGIN:VEVENT"), "ics": text}

    # ================================================================== people and expenses
    def ensure_people(self, trip_id: str) -> list[dict[str, Any]]:
        people = self.t.people(trip_id)
        if not people:
            cfg = self.cfg()
            self.t.add_person(trip_id, cfg.my_name or ("Yo" if cfg.lang == "es" else "Me"), is_me=True)
            people = self.t.people(trip_id)
        return people

    def add_people(self, key: str, names: list[str]) -> dict[str, Any]:
        trip = self.t.find_trip(key)
        people = self.ensure_people(trip["id"])
        have = {fold(p["name"]) for p in people}
        for name in names:
            name = " ".join(str(name).split())[:40]
            if name and fold(name) not in have:
                self.t.add_person(trip["id"], name)
                have.add(fold(name))
        return {"people": self.t.people(trip["id"])}

    def rename_person(self, key: str, person: str, name: str = "", is_me: Optional[bool] = None) -> dict[str, Any]:
        trip = self.t.find_trip(key)
        p = self._person(trip["id"], person)
        if name.strip():
            self.t.update_person(p["id"], name=" ".join(name.split())[:40])
        if is_me:
            used = {e["payer_id"] for e in self.t.expenses(trip["id"])} | {i for e in self.t.expenses(trip["id"]) for i in json_ids(e)}
            for other in self.t.people(trip["id"]):
                if other["is_me"] and other["id"] != p["id"] and other["id"] not in used and fold(other["name"]) in ("yo", "me"):
                    self.t.delete_person(other["id"])      # the placeholder made for the user, now replaced by a real name
                    continue
                self.t.update_person(other["id"], is_me=other["id"] == p["id"])
        return {"people": self.t.people(trip["id"])}

    def remove_person(self, key: str, person: str) -> dict[str, Any]:
        trip = self.t.find_trip(key)
        p = self._person(trip["id"], person)
        for e in self.t.expenses(trip["id"]):
            if e["payer_id"] == p["id"] or p["id"] in json_ids(e):
                raise PhileasError("invalid", f"{p['name']} is in expenses of this trip.", "Delete or edit those expenses first.")
        self.t.delete_person(p["id"])
        return {"people": self.t.people(trip["id"])}

    def _person(self, trip_id: str, ref: str) -> dict[str, Any]:
        people = self.ensure_people(trip_id)
        ref = (ref or "").strip()
        for p in people:
            if p["id"] == ref:
                return p
        hits = [p for p in people if fold(p["name"]) == fold(ref)] or [p for p in people if fold(ref) and fold(p["name"]).startswith(fold(ref))]
        if len(hits) == 1:
            return hits[0]
        if ref.lower() in ("yo", "me", "mi") and any(p["is_me"] for p in people):
            return next(p for p in people if p["is_me"])
        raise PhileasError("not_found", f"No person {ref!r} on this trip.", "People: " + ", ".join(p["name"] for p in people) + ". Add one with trip_people.")

    def _resolve_split(self, trip_id: str, mode: str, split: dict[str, Any]) -> dict[str, Any]:
        split = split or {}
        if mode == "equal":
            who = split.get("participants") or split.get("people") or []
            return {"participants": [self._person(trip_id, w)["id"] for w in who]} if who else {}
        key = "shares" if mode == "shares" else "amounts"
        values = split.get(key) or split.get("people") or {}
        if not isinstance(values, dict) or not values:
            raise PhileasError("invalid", f"A {mode} split needs {{name: {'weight' if mode == 'shares' else 'amount'}}}.")
        return {key: {self._person(trip_id, who)["id"]: float(v) for who, v in values.items()}}

    def add_expense(self, key: str, *, description: str, amount: float, payer: str = "", currency: str = "", rate: float = 1.0, split_mode: str = "equal",
                    split: Optional[dict[str, Any]] = None, day: str = "", category: str = "other", segment_id: str = "") -> dict[str, Any]:
        trip = self.t.find_trip(key)
        people = self.ensure_people(trip["id"])
        payer_p = self._person(trip["id"], payer) if payer else next((p for p in people if p["is_me"]), people[0])
        if split_mode not in SPLIT_MODES:
            raise PhileasError("invalid", f"split_mode must be one of {', '.join(SPLIT_MODES)}.")
        if category not in EXPENSE_CATEGORIES:
            raise PhileasError("invalid", f"category must be one of {', '.join(EXPENSE_CATEGORIES)}.")
        base = (trip.get("currency") or "EUR").upper()
        cur = (currency or base).upper()
        row = {"description": description.strip()[:200], "amount": float(amount), "currency": cur, "rate": float(rate or 1.0) if cur != base else 1.0,
               "payer_id": payer_p["id"], "split_mode": split_mode, "split": self._resolve_split(trip["id"], split_mode, split or {}),
               "date": (day or self.today().isoformat())[:10], "category": category, "segment_id": segment_id or None}
        exp.validate(row, [p["id"] for p in people], base)
        e = self.t.create_expense(trip["id"], **row)
        return {"expense": self._expense_row(e, people), "summary": self.expenses_view(trip["id"])["summary"]}

    def update_expense(self, eid: str, **f: Any) -> dict[str, Any]:
        e = self.t.expense(eid)
        trip = self.t.trip(e["trip_id"])
        people = self.ensure_people(trip["id"])
        base = (trip.get("currency") or "EUR").upper()
        row = {k: e[k] for k in ("description", "amount", "currency", "rate", "payer_id", "split_mode", "split", "date", "category", "segment_id")}
        if f.get("description") is not None:
            row["description"] = f["description"].strip()[:200]
        if f.get("amount") is not None:
            row["amount"] = float(f["amount"])
        if f.get("currency"):
            row["currency"] = f["currency"].upper()
        if f.get("rate") is not None:
            row["rate"] = float(f["rate"])
        if row["currency"] == base:
            row["rate"] = 1.0
        if f.get("payer"):
            row["payer_id"] = self._person(trip["id"], f["payer"])["id"]
        if f.get("day"):
            row["date"] = f["day"][:10]
        if f.get("category"):
            if f["category"] not in EXPENSE_CATEGORIES:
                raise PhileasError("invalid", f"category must be one of {', '.join(EXPENSE_CATEGORIES)}.")
            row["category"] = f["category"]
        if f.get("split_mode") or f.get("split") is not None:
            row["split_mode"] = f.get("split_mode") or row["split_mode"]
            row["split"] = self._resolve_split(trip["id"], row["split_mode"], f.get("split") or {})
        exp.validate(row, [p["id"] for p in people], base)
        updated = self.t.update_expense(eid, **row)
        return {"expense": self._expense_row(updated, people), "summary": self.expenses_view(trip["id"])["summary"]}

    def delete_expense(self, eid: str) -> dict[str, Any]:
        e = self.t.expense(eid)
        self.t.delete_expense(eid)
        return {"deleted": eid, "summary": self.expenses_view(e["trip_id"])["summary"]}

    def _expense_row(self, e: dict[str, Any], people: list[dict[str, Any]]) -> dict[str, Any]:
        names = {p["id"]: p["name"] for p in people}
        shares = exp.shares_of(e, [p["id"] for p in people])
        me = next((p["id"] for p in people if p["is_me"]), None)
        return {**e, "payer": names.get(e["payer_id"], "?"), "base_amount": exp.base_cents(e) / 100,
                "shares": [{"person_id": pid, "name": names.get(pid, "?"), "amount": c / 100} for pid, c in shares.items()], "my_share": exp.my_share(e, me, [p["id"] for p in people]) / 100,
                "sent_to_ledger": e.get("ledger_sent_ts") is not None}

    def expenses_view(self, trip_id: str) -> dict[str, Any]:
        trip = self.t.trip(trip_id)
        people = self.t.people(trip_id)
        rows = self.t.expenses(trip_id)
        if not people and not rows:
            return {"people": [], "expenses": [], "summary": exp.summary([], [], trip.get("currency") or "EUR"), "currency": trip.get("currency") or "EUR"}
        people = self.ensure_people(trip_id)
        return {"people": people, "expenses": [self._expense_row(e, people) for e in rows], "currency": trip.get("currency") or "EUR",
                "summary": exp.summary(people, rows, trip.get("currency") or "EUR")}

    def expense_from_segment(self, sid: str, payer: str = "") -> dict[str, Any]:
        seg = self.t.segment(sid)
        if seg.get("price") is None:
            raise PhileasError("invalid", "That segment has no price from its mail.")
        if not seg.get("trip_id"):
            raise PhileasError("invalid", "That segment is not in a trip yet.")
        for e in self.t.expenses(seg["trip_id"]):
            if e.get("segment_id") == sid:
                raise PhileasError("invalid", "That price is already an expense of the trip.")
        cfg = self.cfg()
        trip = self.t.trip(seg["trip_id"])
        cur = (seg.get("currency") or trip.get("currency") or "EUR").upper()
        if cur != (trip.get("currency") or "EUR").upper():
            raise PhileasError("rate_required", f"The price is in {cur} and the trip in {trip.get('currency')}.", "Add the expense by hand with its exchange rate.")
        return self.add_expense(trip["id"], description=notices.label(seg, cfg.lang), amount=float(seg["price"]), payer=payer, currency=cur,
                                category=CATEGORY_OF_KIND.get(seg["kind"], "other"), segment_id=sid, day=(seg.get("start_date") or ""))

    def to_ledger(self, key: str, *, account: str = "", dry_run: bool = False) -> dict[str, Any]:
        """Pass my share of each expense not yet sent to Ledger. Sent expenses are remembered and never sent twice."""
        trip = self.t.find_trip(key)
        people = self.ensure_people(trip["id"])
        me = next((p for p in people if p["is_me"]), None)
        if me is None:
            raise PhileasError("invalid", "Mark which person is you first (trip_people).")
        ids = [p["id"] for p in people]
        pending = []
        for e in self.t.expenses(trip["id"]):
            share = exp.my_share(e, me["id"], ids)
            if e.get("ledger_sent_ts") is None and share > 0:
                pending.append((e, share))
        sent_before = [e for e in self.t.expenses(trip["id"]) if e.get("ledger_sent_ts") is not None]
        base = {"trip": trip["id"], "currency": trip.get("currency") or "EUR", "already_sent": len(sent_before)}
        if not pending:
            return {**base, "status": "nothing_to_send", "sent": [], "pending": []}
        listing = [{"expense": e["id"], "description": e["description"], "my_share": s / 100, "date": e["date"]} for e, s in pending]
        if dry_run or self.call is None:
            return {**base, "status": "dry_run" if dry_run else "no_hub", "sent": [], "pending": listing}
        target = hubcalls.ledger_target(self.call, account or self.cfg().ledger_account)
        if not target["ok"]:
            return {**base, "status": "ledger_unavailable", "reason": target["reason"], "accounts": target.get("accounts"), "sent": [], "pending": listing}
        if target["currency"] != (trip.get("currency") or "EUR").upper():
            return {**base, "status": "currency_mismatch", "reason": f"The Ledger account {target['account']} is in {target['currency']} and the trip in {trip.get('currency')}.",
                    "sent": [], "pending": listing}
        sent, failed = [], []
        for e, share in pending:
            out = hubcalls.send_entry(self.call, target, cents=share, day=e.get("date") or "", counterparty=trip.get("title") or "", tags=["viaje"],
                                      note=f"{trip.get('title')}: {e['description']}")
            if out["ok"]:
                self.t.update_expense(e["id"], ledger_sent_ts=self.now(), ledger_amount=share / 100, ledger_entry=out["entry_id"])
                sent.append({"expense": e["id"], "description": e["description"], "amount": share / 100, "entry": out.get("entry")})
            else:
                failed.append({"expense": e["id"], "description": e["description"], "reason": out["reason"]})
                if out["reason"] in ("hub_down", "app_down"):
                    break
        return {**base, "status": "ok" if not failed else "partial", "account": target["account"], "category": target["category"], "sent": sent, "failed": failed,
                "pending": [x for x in listing if x["expense"] not in {s["expense"] for s in sent}]}


def json_ids(e: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for v in (e.get("split") or {}).values():
        out |= set(v.keys()) if isinstance(v, dict) else set(v)
    return out
