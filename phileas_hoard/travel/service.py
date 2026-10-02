"""The travel facet: bookings from mail, trips, check-in reminders, documents and shared expenses.

``Travel`` owns the rules; ``Services`` builds one and ``Engine.ingest`` hands it every mail first (a mail that is clearly a booking
is filed here, anything else goes on to the parcel rules untouched).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from ..errors import PhileasError
from . import airports, checkin, hubcalls, ics, llm, notices, segments as seglib, trips as tripslib
from .airlines import fold
from .analyze import TravelFacts, analyze_travel
from .draft import SegmentDraft
from .model import (CANCELLED, CONFIRMED, EVENT, FLIGHT, KINDS, LODGING, N_CHECKIN_CLOSING, N_CHECKIN_OPEN, N_DEPARTURE, N_DOC_PROBLEM, N_LODGING_DAY,
                    N_SEGMENT_CANCELLED, N_SEGMENT_CHANGED, N_TRIP_NEW, N_TRIP_TOMORROW, ONGOING, PAST, TRANSPORT, UPCOMING)
from .ops import Ops
from .store import TravelStore

log = logging.getLogger("phileas.travel")

HOUR = 3600.0
QUIET_AGE_S = 36 * HOUR
MODEL_CALLS_PER_BATCH = 6
FRESH_OPEN_S = 6 * HOUR            # a check-in that opened longer ago than this is only announced when the flight is close
CLOSE_FLIGHT_S = 72 * HOUR
URGENT_S = 4 * HOUR                # events this close are announced even during night silence

DEFAULTS = {
    "travel.enabled": "1", "travel.home_city": "", "travel.home_airports": "", "travel.home_tz": "Europe/Madrid", "travel.gap_days": "2",
    "travel.kinds": "flight,train,bus,ferry,car,lodging", "travel.departure_hours": "3", "travel.tomorrow_hour": "18", "travel.my_name": "",
    "travel.model_fallback": "1", "travel.docs_check": "1", "travel.docs_days": "45", "travel.ledger_account": "",
}


@dataclass
class Config:
    enabled: bool
    home: tripslib.Home
    gap_days: int
    kinds: frozenset
    departure_hours: int
    tomorrow_hour: int
    my_name: str
    model: bool
    docs_check: bool
    docs_days: int
    ledger_account: str
    lang: str
    night: tuple[int, int]


def _int(value: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


class Travel(Ops):
    def __init__(self, store: Any, tstore: TravelStore, notifier: Any, *, setting: Callable[[str, Optional[str]], str],
                 set_setting: Callable[[str, str], None], emit: Callable[[str, dict], None] = lambda t, d: None,
                 clock: Callable[[], float] = time.time, chat: Optional[llm.Chat] = None, call: Optional[hubcalls.Call] = None):
        self.store = store
        self.t = tstore
        self.notifier = notifier
        self._setting = setting
        self._set = set_setting
        self.emit = emit
        self.clock = clock
        self.chat = chat
        self.call = call
        self._model_calls = 0

    # ================================================================== settings
    def setting(self, key: str) -> str:
        try:
            value = self._setting(key, None)
        except Exception:  # noqa: BLE001
            value = None
        return DEFAULTS.get(key, "") if value in (None, "") else str(value)

    def cfg(self) -> Config:
        tz = self.setting("travel.home_tz")
        home = tripslib.Home(city=self.setting("travel.home_city").strip(),
                             airports=frozenset(c.strip().upper() for c in self.setting("travel.home_airports").replace(";", ",").split(",") if c.strip()),
                             tz=tz if airports.valid_tz(tz) else "Europe/Madrid")
        if home.airports and not home.city:                       # an airport alone is enough to know the home city
            first = airports.lookup(sorted(home.airports)[0])
            home.city = (first or {}).get("city", "")
        kinds = frozenset(k.strip() for k in self.setting("travel.kinds").split(",") if k.strip() in KINDS)
        night_from, night_to = _int(self._get("checks.night_from", "23"), 23, 0, 24), _int(self._get("checks.night_to", "7"), 7, 0, 24)
        lang = "en" if self._get("ui.language", "es") == "en" else "es"
        return Config(self.setting("travel.enabled") == "1", home, _int(self.setting("travel.gap_days"), 2, 0, 14), kinds,
                      _int(self.setting("travel.departure_hours"), 3, 1, 24), _int(self.setting("travel.tomorrow_hour"), 18, 0, 23),
                      self.setting("travel.my_name").strip(), self.setting("travel.model_fallback") == "1", self.setting("travel.docs_check") == "1",
                      _int(self.setting("travel.docs_days"), 45, 1, 365), self.setting("travel.ledger_account").strip(), lang, (night_from, night_to))

    def _get(self, key: str, default: str) -> str:
        try:
            value = self._setting(key, None)
        except Exception:  # noqa: BLE001
            value = None
        return default if value in (None, "") else str(value)

    def now(self) -> float:
        return self.clock()

    def today(self, cfg: Optional[Config] = None) -> date:
        tz = (cfg or self.cfg()).home.tz
        return datetime.fromtimestamp(self.now(), ZoneInfo(tz)).date()

    # ================================================================== mail
    def existing_trips(self, ids: list[str]) -> list[str]:
        have = {t["id"] for t in self.t.trips()}
        return [i for i in dict.fromkeys(ids) if i in have]

    def begin_batch(self) -> None:
        self._model_calls = 0

    def process_mail(self, message: dict[str, Any], *, bootstrap: bool = False, force: bool = False, force_travel: bool = False,
                     parcel_shipping: bool = False) -> Optional[dict[str, Any]]:
        """File a travel mail. ``None`` means "not a travel mail" and the caller carries on with the parcel rules.

        ``force`` (a mail pasted by hand) claims the mail when it reads as travel at all; ``force_travel`` claims it unconditionally."""
        cfg = self.cfg()
        if not cfg.enabled:
            return None
        facts = analyze_travel(message, default_tz=cfg.home.tz)
        claim = facts.candidate or force_travel or (force and bool(facts.drafts))
        if parcel_shipping and not force_travel and not (facts.sender or facts.source == "schema"):
            claim = False                                       # the parcel rules read it as shipping and nothing says travel company
        if not claim:
            return None
        if not force_travel and facts.drafts and facts.source == "schema":
            kept = [d for d in facts.drafts if not self._event_not_travel(d, cfg)]
            if not kept:
                return None                                     # tickets for something in the home city are not travel
            facts.drafts = kept
        ts = float(message.get("ts") or self.now())
        quiet = bootstrap or (self.now() - ts) > QUIET_AGE_S
        drafts = [d for d in facts.drafts if d.kind in cfg.kinds or force_travel]
        summary: dict[str, Any] = {"created": 0, "updated": 0, "cancelled": 0, "segments": [], "trips": [], "model": None}
        state = "linked"
        if facts.drafts and not drafts:
            state = "skipped"                                   # a kind the user turned off in the settings
            summary["skipped_kinds"] = sorted({d.kind for d in facts.drafts})
        elif not drafts:
            if facts.change == "cancel" and facts.ref:
                done = self._cancel_ref(facts.ref, message, ts, quiet, cfg)
                summary.update(done)
                state = "linked" if done["cancelled"] else "new"
            else:
                model = self._model_pass(message, cfg)
                summary["model"] = {k: model[k] for k in ("status", "model", "error")}
                facts.drafts = model["drafts"]
                facts.source = "model" if model["drafts"] else "none"
                state = "new"
        else:
            filed = self._file(message, drafts, facts.change, quiet, cfg, ref=facts.ref, revive=force_travel)
            summary.update(filed)
        data = facts.to_dict()
        if state == "new":
            data["text"] = str(message.get("text") or "")[:20000]       # kept so the model can read it again later
            data["model"] = summary.get("model")
        return {"kind": "travel", "state": state, "score": facts.score, "facts": data, "summary": summary}

    @staticmethod
    def _event_not_travel(d: SegmentDraft, cfg: Config) -> bool:
        """An event is travel only with a date and a venue or city away from home; one in the home city, or with no place at all, is left out."""
        if d.kind != EVENT:
            return False
        place = fold(" ".join((d.from_city, d.from_name, d.address)))
        if not place.strip() or not d.dep_local:
            return True
        return bool(cfg.home.city and fold(cfg.home.city) in place)

    def _model_pass(self, message: dict[str, Any], cfg: Config) -> dict[str, Any]:
        if not cfg.model:
            return {"status": "off", "drafts": [], "model": "", "error": ""}
        if self._model_calls >= MODEL_CALLS_PER_BATCH:
            return {"status": "deferred", "drafts": [], "model": "", "error": "too many mails in one scan; open the review list to read it again"}
        self._model_calls += 1
        return llm.read_with_model(message, self.chat)

    def recheck_review(self) -> dict[str, Any]:
        """Run the booking-evidence gate again over the travel mails waiting for review and drop the ones that were never bookings
        (marketing, notices, event tickets). A mail with something read from it, a pasted one and one the user already handled stay."""
        cfg = self.cfg()
        dropped, kept = [], 0
        for row in self.store.mails(kind=["travel"], state=["new"], limit=2000):
            mid = row["message_id"]
            facts = row.get("facts") or {}
            if mid.startswith("<pasted-") or facts.get("drafts"):
                kept += 1
                continue
            message = {"message_id": mid, "ts": row.get("ts"), "subject": row.get("subject") or "", "from_address": row.get("from_address") or "",
                       "from_name": row.get("from_name") or "", "text": facts.get("text") or row.get("snippet") or ""}
            again = analyze_travel(message, default_tz=cfg.home.tz)
            if again.candidate:
                kept += 1
                continue
            data = {**{k: v for k, v in facts.items() if k != "text"}, "reasons": again.reasons, "rechecked": True}
            self.store.save_mail({**message, "account": row.get("account") or ""}, kind="noise", score=again.score, facts=data, shipment_id=None, state="skipped")
            dropped.append(mid)
        return {"dropped": len(dropped), "kept": kept, "message_ids": dropped[:50]}

    def read_again(self, message_id: str) -> dict[str, Any]:
        """Ask the model pass again for a mail waiting in the review list."""
        row = self.store.mail(message_id)
        if row is None or row.get("kind") != "travel":
            raise PhileasError("not_found", "No such travel mail.")
        facts = TravelFacts.from_dict(row.get("facts") or {})
        raw = (row.get("facts") or {}).get("text") or row.get("snippet") or ""
        message = {"message_id": message_id, "ts": row.get("ts"), "subject": row.get("subject"), "from_address": row.get("from_address"), "text": raw}
        self._model_calls = 0
        model = llm.read_with_model(message, self.chat)
        facts.drafts = model["drafts"]
        facts.source = "model" if model["drafts"] else "none"
        data = facts.to_dict()
        data["text"] = raw
        data["model"] = {k: model[k] for k in ("status", "model", "error")}
        self.store.save_mail({**message, "account": row.get("account") or ""}, kind="travel", score=row.get("score") or 0, facts=data, shipment_id=None, state="new")
        return {"model": data["model"], "drafts": [d.to_dict() for d in facts.drafts]}

    def accept_mail(self, message_id: str) -> dict[str, Any]:
        """Turn a travel mail from the review list into segments (what the rules or the model read from it)."""
        row = self.store.mail(message_id)
        if row is None or row.get("kind") != "travel":
            raise PhileasError("not_found", "No such travel mail.", "List them with travel_mail_list.")
        facts = TravelFacts.from_dict(row.get("facts") or {})
        if not facts.drafts:
            raise PhileasError("nothing_to_accept", "Nothing was read from that mail.",
                               "Add the segment by hand with segment_add, or read it again with travel_mail_read_again once a model is available.")
        cfg = self.cfg()
        filed = self._file({"message_id": message_id, "ts": row.get("ts"), "subject": row.get("subject")}, facts.drafts, facts.change, True, cfg,
                           ref=facts.ref, accepted=True)
        self.store.set_mail_state(message_id, "linked")
        return filed

    def paste(self, *, subject: str, text: str, from_address: str = "", trip: str = "", html: str = "") -> dict[str, Any]:
        """A booking mail pasted by hand. Reads it like any mail; ``trip`` puts what was read into that trip."""
        mid = "<pasted-" + hashlib.sha1(f"{subject}|{text}".encode("utf-8", "replace")).hexdigest()[:16] + "@phileas>"
        known = self.store.mail(mid)
        if known and known.get("kind") == "travel":
            return {"already_known": True, "message_id": mid, "state": known.get("state"), "segments": self.t.segments_of_mail(mid)}
        message = {"message_id": mid, "ts": self.now(), "subject": subject, "text": text, "from_address": from_address, "from_name": "", "links": [], "html": html}
        res = self.process_mail(message, force=True, force_travel=True)
        if res is None:
            raise PhileasError("disabled", "The travel facet is turned off.", "Turn on travel.enabled in the settings.")
        if res:
            self.store.save_mail(message, kind="travel", score=res["score"], facts=res["facts"], shipment_id=None, state=res["state"])
        out = {"message_id": mid, "state": res["state"], "score": res["score"], **res["summary"],
               "read": [d for d in res["facts"].get("drafts", [])]}
        if trip and res["summary"].get("segments"):
            target = self.t.find_trip(trip)
            for sid in res["summary"]["segments"]:
                self.move_segment(sid, target["id"])
            out["moved_to"] = target["id"]
        return out

    # ------------------------------------------------------------------ filing
    def _file(self, message: dict[str, Any], drafts: list[SegmentDraft], change: str, quiet: bool, cfg: Config, *, ref: str = "",
              accepted: bool = False, revive: bool = False) -> dict[str, Any]:
        revive = revive or accepted
        mid = str(message.get("message_id") or "")
        ts = float(message.get("ts") or self.now())
        out: dict[str, Any] = {"created": 0, "updated": 0, "cancelled": 0, "segments": [], "trips": []}
        existing = self.t.segments(include_cancelled=True)
        first_label = ""
        for d in drafts:
            row = seglib.row_from_draft(d, cfg.home.tz)
            row["last_mail_ts"] = ts
            match = seglib.find_match(existing, row)
            cancel = d.change == "cancel" or d.status == CANCELLED
            if match is None:
                if cancel:
                    continue                                    # a cancellation for something never booked here
                if self.t.is_forgotten(row):
                    if not revive:
                        out["skipped_deleted"] = out.get("skipped_deleted", 0) + 1
                        continue                                # the user deleted this booking: reading its mail again does not bring it back
                    self.t.unforget(row)
                end_ts = row.get("arr_ts") or row.get("dep_ts")
                row.update(trip_id=None, locked=False, history_only=bool(quiet and end_ts and end_ts < self.now() - 10 * 86400), last_change_ts=ts)
                if accepted:
                    row["needs_review"] = False
                seg = self.t.create_segment(**row)
                self.t.link_mail(seg["id"], mid, ts, "confirmation")
                existing.append(seg)
                out["created"] += 1
                out["segments"].append(seg["id"])
                first_label = first_label or notices.label(seg, cfg.lang)
                continue
            out["segments"].append(match["id"])
            self.t.link_mail(match["id"], mid, ts, "cancellation" if cancel else ("change" if d.change == "change" else "confirmation"))
            stale = bool(match.get("last_mail_ts")) and ts < float(match["last_mail_ts"]) - 1
            if cancel:
                if match["status"] != CANCELLED and not stale:
                    self.t.update_segment(match["id"], status=CANCELLED, last_change_ts=ts, last_mail_ts=ts)
                    out["cancelled"] += 1
                    if not quiet:
                        self._notify_segment(N_SEGMENT_CANCELLED, self.t.segment(match["id"]), cfg, dedupe=f"seg:{match['id']}|cancelled")
                continue
            if stale:
                continue
            authoritative = d.change == "change" or (not match.get("edited") and bool(seglib.differences(match, row)))
            updates = seglib.merge_fields(match, row, authoritative=authoritative)
            diffs = seglib.differences(match, {**row, **updates}) if authoritative else []
            if match["status"] == CANCELLED and d.change != "cancel" and ts > float(match.get("last_change_ts") or 0):
                updates["status"] = CONFIRMED                    # booked again
            if updates or authoritative:
                merged = seglib.derive({**match, **updates}, cfg.home.tz)
                updates.update({k: merged[k] for k in ("start_date", "end_date", "dep_ts", "arr_ts")})
                updates["last_mail_ts"] = ts
                if diffs:
                    updates["last_change_ts"] = ts
                self.t.update_segment(match["id"], **updates)
                out["updated"] += 1
                if diffs and not quiet:
                    seg = self.t.segment(match["id"])
                    key = "|".join(f"{x['field']}={x['new']}" for x in diffs)
                    self._notify_segment(N_SEGMENT_CHANGED, seg, cfg, dedupe=f"seg:{seg['id']}|changed|{hashlib.sha1(key.encode()).hexdigest()[:10]}", diffs=diffs)
        result = self.regroup(quiet=quiet)
        out["trips"] = sorted({s["trip_id"] for sid in out["segments"] for s in [self.t.segment(sid)] if s.get("trip_id")})
        out["new_trips"] = result.created
        if result.created and not quiet:
            for tid in result.created:
                trip = self.t.trip(tid)
                if tripslib.trip_status(trip, self.t.segments(trip_id=tid), self.today(cfg)) in (UPCOMING, ONGOING):
                    self._notify_trip(N_TRIP_NEW, trip, cfg, dedupe=f"trip:{tid}|new", count=len(self.t.segments(trip_id=tid)), first=first_label)
        return out

    def _cancel_ref(self, ref: str, message: dict[str, Any], ts: float, quiet: bool, cfg: Config) -> dict[str, Any]:
        out = {"created": 0, "updated": 0, "cancelled": 0, "segments": [], "trips": []}
        for seg in self.t.segments(ref=ref.upper(), include_cancelled=True):
            if seg["status"] == CANCELLED or (seg.get("last_mail_ts") and ts < float(seg["last_mail_ts"]) - 1):
                continue
            self.t.update_segment(seg["id"], status=CANCELLED, last_change_ts=ts, last_mail_ts=ts)
            self.t.link_mail(seg["id"], str(message.get("message_id") or ""), ts, "cancellation")
            out["cancelled"] += 1
            out["segments"].append(seg["id"])
            if not quiet:
                self._notify_segment(N_SEGMENT_CANCELLED, self.t.segment(seg["id"]), cfg, dedupe=f"seg:{seg['id']}|cancelled")
        if out["cancelled"]:
            self.regroup(quiet=True)
        return out

    def regroup(self, *, quiet: bool = True) -> tripslib.Result:
        cfg = self.cfg()
        result = tripslib.regroup(self.t, home=cfg.home, gap_days=cfg.gap_days, lang=cfg.lang, today=self.today(cfg))
        today = self.today(cfg)
        for tid in {t["id"] for t in self.t.trips()}:         # trips that are already over are history (no reminders, quiet lists)
            trip = self.t.trip(tid)
            segs = self.t.segments(trip_id=tid)
            past = bool(segs) and tripslib.trip_status(trip, segs, today) == PAST
            if past != bool(trip.get("history_only")):
                self.t.update_trip(tid, history_only=past)
        for tid in result.created:
            self._emit("phileas.trip.new", self._brief(self.t.trip(tid)))
        for tid in result.changed:
            if tid not in result.created:
                self._emit("phileas.trip.changed", self._brief(self.t.trip(tid)))
        return result

    def _emit(self, type_: str, data: dict[str, Any]) -> None:
        try:
            self.emit(type_, data)
        except Exception:  # noqa: BLE001
            pass

    def _brief(self, trip: dict[str, Any]) -> dict[str, Any]:
        return {"trip_id": trip["id"], "title": trip.get("title"), "start_date": trip.get("start_date"), "end_date": trip.get("end_date")}

    # ================================================================== notifications
    def _night(self, cfg: Config) -> bool:
        hour = datetime.fromtimestamp(self.now(), ZoneInfo(cfg.home.tz)).hour
        lo, hi = cfg.night
        return (hour >= lo or hour < hi) if lo > hi else (lo <= hour < hi)

    def _notify_trip(self, type_: str, trip: dict[str, Any], cfg: Config, *, dedupe: str, seg: Optional[dict[str, Any]] = None, urgent: bool = False,
                     **kw: Any) -> bool:
        if self.store.notified(dedupe) or trip.get("muted"):
            return False
        if self._night(cfg) and not urgent:
            return self._queue(type_, trip["id"], (seg or {}).get("id"), dedupe, kw)
        return self._send(type_, trip, seg, cfg, dedupe, kw)

    def _notify_segment(self, type_: str, seg: dict[str, Any], cfg: Config, *, dedupe: str, urgent: bool = False, **kw: Any) -> bool:
        trip = self.t.trip(seg["trip_id"]) if seg.get("trip_id") else {"id": None, "title": "", "muted": False}
        if not urgent and seg.get("dep_ts") and 0 <= float(seg["dep_ts"]) - self.now() <= URGENT_S:
            urgent = True
        if type_ in (N_SEGMENT_CHANGED, N_SEGMENT_CANCELLED):
            urgent = urgent or (seg.get("dep_ts") and float(seg["dep_ts"]) - self.now() <= 12 * HOUR) or False
        return self._notify_trip(type_, trip, cfg, dedupe=dedupe, seg=seg, urgent=bool(urgent), **kw)

    def _queue(self, type_: str, trip_id: Optional[str], seg_id: Optional[str], dedupe: str, kw: dict[str, Any]) -> bool:
        """Night silence: keep the notice and send it when the night ends."""
        pending = self._pending()
        if any(p["dedupe"] == dedupe for p in pending):
            return False
        pending.append({"type": type_, "trip_id": trip_id, "seg_id": seg_id, "dedupe": dedupe, "kw": kw, "queued": self.now()})
        self._set("travel.pending", json.dumps(pending[-100:], default=str))
        return False

    def _pending(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._get("travel.pending", "[]"))
            return data if isinstance(data, list) else []
        except ValueError:
            return []

    def flush_pending(self, cfg: Config) -> int:
        if self._night(cfg):
            return 0
        pending = self._pending()
        if not pending:
            return 0
        self._set("travel.pending", "[]")
        sent = 0
        for p in pending:
            try:
                trip = self.t.trip(p["trip_id"]) if p.get("trip_id") else {"id": None, "title": ""}
                seg = self.t.segment(p["seg_id"]) if p.get("seg_id") else None
            except PhileasError:
                continue
            if self.store.notified(p["dedupe"]):
                continue
            if seg and seg.get("dep_ts") and float(seg["dep_ts"]) < self.now() and p["type"] != N_SEGMENT_CANCELLED:
                continue                                         # it is over: nothing to announce any more
            sent += bool(self._send(p["type"], trip, seg, cfg, p["dedupe"], p.get("kw") or {}))
        return sent

    def _send(self, type_: str, trip: dict[str, Any], seg: Optional[dict[str, Any]], cfg: Config, dedupe: str, kw: dict[str, Any]) -> bool:
        title, body = notices.compose(type_, cfg.lang, trip=trip, seg=seg, **kw)
        link = ""
        for x in (seg or {}).get("links") or []:
            if x.get("kind") == ("checkin" if type_ in (N_CHECKIN_OPEN, N_CHECKIN_CLOSING) else "manage"):
                link = x["url"]
                break
        if not link and seg:
            link = next((x["url"] for x in seg.get("links") or []), "")
        event = {"id": f"{trip.get('id') or ''}:{type_}", "type": type_, "severity": notices.SEVERITY.get(type_, "medium"), "title": title, "summary": body,
                 "url": link, "trip_id": trip.get("id"), "segment_id": (seg or {}).get("id"), "trip_title": trip.get("title"),
                 "start_date": trip.get("start_date"), "end_date": trip.get("end_date"), "dedupe_key": f"phileas:{dedupe}"}
        try:
            results = self.notifier.send(event, ["toast", "hub", "ntfy", "telegram", "email"])
        except Exception as exc:  # noqa: BLE001
            results = [{"channel": "all", "ok": False, "error": type(exc).__name__}]
        self.store.add_notification(shipment_id=None, trip_id=trip.get("id"), type_=type_, severity=event["severity"], title=title, body=body,
                                    results=results, dedupe=dedupe)
        if type_ == N_CHECKIN_OPEN and seg:
            self._emit("phileas.checkin.open", {"trip_id": trip.get("id"), "segment_id": seg["id"], "number": seg.get("number"),
                                                "from": seg.get("from_code"), "to": seg.get("to_code"), "dep_local": seg.get("dep_local")})
        return True

    # ================================================================== time-driven reminders
    def tick(self) -> dict[str, int]:
        """Called every minute or so: announce what is due. Every notice is sent once (dedupe by segment/trip and type)."""
        cfg = self.cfg()
        out = {"sent": 0}
        if not cfg.enabled:
            return out
        now = self.now()
        out["sent"] += self.flush_pending(cfg)
        today = self.today(cfg)
        for trip in self.t.trips(include_history=False):
            if trip.get("cancelled") or trip.get("muted"):
                continue
            segs = [s for s in self.t.segments(trip_id=trip["id"]) if s["status"] != CANCELLED]
            status = tripslib.trip_status(trip, segs, today)
            if status == UPCOMING and trip.get("start_date") == (today + timedelta(days=1)).isoformat():
                local_hour = datetime.fromtimestamp(now, ZoneInfo(cfg.home.tz)).hour
                if local_hour >= cfg.tomorrow_hour:
                    first = min((s for s in segs if s.get("dep_ts")), key=lambda s: s["dep_ts"], default=None)
                    out["sent"] += bool(self._notify_trip(N_TRIP_TOMORROW, trip, cfg, dedupe=f"trip:{trip['id']}|tomorrow", seg=first))
            if status in (UPCOMING, ONGOING):
                for seg in segs:
                    out["sent"] += self._tick_segment(trip, seg, cfg, now, today)
            if status == UPCOMING and cfg.docs_check and self.call is not None:
                out["sent"] += self._tick_documents(trip, segs, cfg, today)
        return out

    def _tick_segment(self, trip: dict[str, Any], seg: dict[str, Any], cfg: Config, now: float, today: date) -> int:
        sent = 0
        dep = seg.get("dep_ts")
        has_time = airports.has_time(seg.get("dep_local") or "")
        if seg["kind"] == FLIGHT and dep and has_time and now < dep and not seg.get("checkin_done"):
            w = checkin.window(seg)
            opens, closes = w.get("opens_ts"), w.get("closes_ts")
            if opens is not None and now >= opens and (closes is None or now < closes) and (now - opens <= FRESH_OPEN_S or dep - now <= CLOSE_FLIGHT_S):
                note = w.get("note_es" if cfg.lang == "es" else "note_en") or ""
                sent += bool(self._notify_segment(N_CHECKIN_OPEN, seg, cfg, dedupe=f"seg:{seg['id']}|checkin_open", known=bool(w.get("known")), note=note))
            if closes is not None and 0 < closes - now <= 3 * HOUR and now >= (opens or 0):
                sent += bool(self._notify_segment(N_CHECKIN_CLOSING, seg, cfg, dedupe=f"seg:{seg['id']}|checkin_closing", urgent=True,
                                                  left=notices.hours_text(closes - now, cfg.lang)))
        if seg["kind"] in TRANSPORT and dep and has_time and 0 < dep - now <= cfg.departure_hours * HOUR:
            sent += bool(self._notify_segment(N_DEPARTURE, seg, cfg, dedupe=f"seg:{seg['id']}|departure", urgent=True, left=notices.hours_text(dep - now, cfg.lang)))
        if seg["kind"] == LODGING and seg.get("start_date") == today.isoformat():
            hour = datetime.fromtimestamp(now, ZoneInfo(cfg.home.tz)).hour
            if hour >= 8:
                sent += bool(self._notify_segment(N_LODGING_DAY, seg, cfg, dedupe=f"seg:{seg['id']}|lodging_day"))
        return sent

    def _tick_documents(self, trip: dict[str, Any], segs: list[dict[str, Any]], cfg: Config, today: date) -> int:
        start = tripslib._d(trip.get("start_date") or "")
        if not start or (start - today).days > cfg.docs_days:
            return 0
        extra = dict(trip.get("extra") or {})
        if self.now() - float(extra.get("docs_checked_ts") or 0) < 12 * HOUR:
            return 0
        result = hubcalls.check_trip_documents(self.call, trip, segs)       # type: ignore[arg-type]
        extra["docs_checked_ts"] = self.now()
        extra["docs"] = {k: result.get(k) for k in ("status", "reason", "return_date")}
        self.t.update_trip(trip["id"], extra=extra)
        sent = 0
        if result["status"] in ("problem", "warning"):
            for problem in result["problems"]:
                key = hashlib.sha1(json.dumps(problem, sort_keys=True).encode()).hexdigest()[:10]
                sent += bool(self._notify_trip(N_DOC_PROBLEM, trip, cfg, dedupe=f"trip:{trip['id']}|doc|{key}", problem=problem, return_date=result["return_date"]))
        return sent
