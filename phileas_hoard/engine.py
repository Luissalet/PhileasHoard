"""The work: read shipping mail into shipments, ask carriers, keep statuses and estimates current, tell the user.

Everything that changes a shipment goes through ``Engine`` so the rules live in one place:

* **Linking** a mail to a shipment: tracking number → Amazon package id → order number → the carrier's own mail about
  the parcel you are waiting for → the shop's earlier mail without numbers → a new shipment (only for clear shipping mail).
* **Status** never goes backwards on stale news; "not found" never hides a known status; carrier news beats mail news
  of the same moment.
* **Checks** are paced by status (out for delivery every 30 min, in transit every 2 h, nothing at night) and by what a
  source asked for after a failure.
* **Notifications** are deduplicated per shipment and type; the first mail import builds history quietly.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional

from . import eta as eta_mod
from . import numbers
from .bizdays import Calendar
from .mail.parse import analyze
from .model import (ACTIVE, AVAILABLE_FOR_PICKUP, CUSTOMS, DELIVERED, EXCEPTION, FAILED_ATTEMPT, FINAL, IN_TRANSIT, LABEL_CREATED,
                    N_DELIVERED, N_ETA, N_NEW, N_OUT, N_PICKUP, N_PICKUP_DEADLINE, N_PROBLEM, N_STALE, N_STATUS, NOT_FOUND, ORDERED,
                    OUT_FOR_DELIVERY, RETURNED, UNKNOWN, label as status_label, progress)

log = logging.getLogger("phileas.engine")

DAY = 86400.0
HISTORY_AGE_DAYS = 10          # on the first import, parcels whose last mail is older than this become history
QUIET_AGE_S = 36 * 3600        # mails older than this never notify
STALE_DELIVERY_DAYS = 4        # in transit without news for this many delivery days → "stale"
GIVE_UP_NOT_FOUND_DAYS = 14


def _date_of(ts: Optional[float]) -> Optional[date]:
    return datetime.fromtimestamp(float(ts)).date() if ts else None


class Engine:
    def __init__(self, store: Any, carriers: Any, notifier: Any, *, settings_get: Callable[[str, Optional[str]], Optional[str]],
                 settings_set: Callable[[str, str], None], emit: Callable[[str, dict], None] = lambda t, d: None,
                 clock: Callable[[], float] = time.time, raw_dir: Any = None, mail_source: Any = None, travel: Any = None):
        self.store = store
        self.carriers = carriers
        self.notifier = notifier
        self.get = settings_get
        self.set = settings_set
        self.emit = emit
        self.clock = clock
        self.raw_dir = raw_dir
        self.mail = mail_source
        self.travel = travel          # the travel facet (bookings from mail); None keeps the engine parcels-only

    # ------------------------------------------------------------------ settings
    def setting(self, key: str, default: str = "") -> str:
        try:
            value = self.get(key, None)
        except Exception:  # noqa: BLE001
            value = None
        return default if value in (None, "") else str(value)

    def lang(self) -> str:
        return "en" if self.setting("ui.language", "es") == "en" else "es"

    def calendar(self) -> Calendar:
        extra = []
        for chunk in self.setting("eta.extra_holidays", "").replace(";", ",").split(","):
            try:
                extra.append(date.fromisoformat(chunk.strip()))
            except ValueError:
                continue
        return Calendar(self.setting("eta.region", "ES-MD"), extra)

    def today(self) -> date:
        return datetime.fromtimestamp(self.clock()).date()

    # ================================================================== mail
    def scan_mail(self, *, since_days: Optional[int] = None, query: str = "", limit: int = 0) -> dict[str, Any]:
        if self.mail is None:
            return {"ok": False, "error": "no mail source"}
        first = self.setting("mail.first_scan_done", "0") != "1"
        days = since_days or int(self.setting("mail.first_days", "120") if first else self.setting("mail.window_days", "14"))
        limit = limit or (800 if first else 150)
        t0 = time.monotonic()
        answer = self.mail.scan(since_days=days, limit=limit, skip=self.store.known_message_ids(), query=query,
                                 travel=bool(self.travel is not None and self.travel.cfg().enabled))
        if not answer.get("ok"):
            self.store.add_run("mail", "", False, int((time.monotonic() - t0) * 1000), str(answer.get("error") or "mail failed"))
            self.set("mail.last_error", str(answer.get("error") or "mail failed")[:300])
            return {"ok": False, "error": answer.get("error") or "mail failed", "accounts": answer.get("accounts") or []}
        messages = answer.get("messages") or []
        summary = self.ingest(messages, bootstrap=first)
        if first:
            self.finish_bootstrap()
            self.set("mail.first_scan_done", "1")
        self.set("mail.last_scan_ts", str(self.clock()))
        self.set("mail.last_error", "")
        detail = f"{len(messages)} new mails, {summary['shipping']} shipping, {summary['created']} new shipments, {summary['linked']} updates"
        if summary.get("travel"):
            detail += f", {summary['travel']} travel"
        self.store.add_run("mail", "", True, int((time.monotonic() - t0) * 1000), detail)
        return {"ok": True, "accounts": answer.get("accounts") or [], "messages": len(messages), "error": answer.get("error") or "", **summary}

    def ingest(self, messages: list[dict[str, Any]], *, bootstrap: bool = False, force: bool = False) -> dict[str, Any]:
        """Analyze and file messages, oldest first so statuses build up in order."""
        out = {"shipping": 0, "maybe": 0, "noise": 0, "created": 0, "linked": 0, "shipments": [], "travel": 0, "trips": []}
        known = set(self.store.known_message_ids(20000))
        quiet_ids: set[str] = set()
        if self.travel is not None:
            self.travel.begin_batch()
        for message in sorted(messages, key=lambda m: m.get("ts") or 0):
            mid = str(message.get("message_id") or "")
            if not mid or mid in known:
                continue
            known.add(mid)
            facts = analyze(message)
            if force and facts.kind != "shipping" and (facts.numbers or facts.order_ref or facts.status):
                facts.kind = "shipping"
            if self.travel is not None:
                booked = self._travel_first(message, facts, bootstrap=bootstrap, force=force)
                if booked is not None:
                    out["travel"] += 1
                    for tid in (booked["summary"].get("trips") or []):
                        if tid not in out["trips"]:
                            out["trips"].append(tid)
                    self.store.save_mail(message, kind="travel", score=booked["score"], facts=booked["facts"], shipment_id=None, state=booked["state"])
                    continue
            out[facts.kind] += 1
            sid, created = None, False
            if facts.kind == "shipping":
                old_mail = bootstrap or self._older_than_live(message)
                sid, created = self._file(message, facts, bootstrap=old_mail)
                if sid and old_mail and not bootstrap:
                    quiet_ids.add(sid)
                    self._settle_if_stale(sid)               # an old mail found by a deep scan never makes an active parcel
                if sid:
                    out["created" if created else "linked"] += 1
                    if sid not in out["shipments"]:
                        out["shipments"].append(sid)
            state = "linked" if sid else ("review" if facts.kind == "maybe" else "skipped")
            if facts.kind == "maybe":
                state = "new"
            self.store.save_mail(message, kind=facts.kind, score=facts.score, facts=facts.to_dict(), shipment_id=sid, state=state)
        if self.travel is not None and out["trips"]:
            out["trips"] = self.travel.existing_trips(out["trips"])
        for sid in out["shipments"]:
            try:
                self.recompute_eta(sid, quiet=bootstrap or sid in quiet_ids)
            except Exception:  # noqa: BLE001
                log.exception("eta failed for %s", sid)
        return out

    def _travel_first(self, message: dict[str, Any], parcel: Any, *, bootstrap: bool, force: bool) -> Optional[dict[str, Any]]:
        """A booking mail is filed by the travel facet. A mail the parcel rules read as shipping stays a parcel unless the sender is a
        travel company or the mail carries reservation markup. A failure here never costs the parcel pass."""
        try:
            return self.travel.process_mail(message, bootstrap=bootstrap, force=force, parcel_shipping=parcel.kind == "shipping")
        except Exception:  # noqa: BLE001
            log.exception("travel pass failed for %s", message.get("message_id"))
            return None

    def _match(self, facts: Any, message: dict[str, Any]) -> Optional[dict[str, Any]]:
        for found in facts.numbers:
            hit = self.store.by_number(found["number"])
            if hit:
                return hit
        if facts.sub_ref:
            hit = self.store.by_sub_ref(facts.merchant, facts.sub_ref)
            if hit:
                return hit
        if facts.order_ref:
            same = self.store.by_order(facts.merchant, facts.order_ref)
            if same:
                if facts.sub_ref:
                    free = [s for s in same if not s.get("sub_ref")]
                    if free:
                        return free[0]
                    return None                       # another parcel of the same order
                if facts.numbers:
                    free = [s for s in same if not s.get("tracking_number")]
                    return free[0] if free else None
                return same[-1]
        ts = float(message.get("ts") or self.clock())
        if facts.carrier_sender and not facts.numbers:
            pool = [s for s in self.store.recent_for(carrier=facts.carrier, since_ts=ts - 21 * DAY)
                    if s["status"] not in FINAL or (facts.status == DELIVERED and s["status"] != DELIVERED)]
            if facts.status == DELIVERED:
                pool = [s for s in pool if s["status"] in (AVAILABLE_FOR_PICKUP, OUT_FOR_DELIVERY, IN_TRANSIT)] or pool
            if pool:
                return pool[0]
        pool = [s for s in self.store.recent_for(merchant=facts.merchant, since_ts=ts - 30 * DAY)
                if s["status"] not in FINAL and not s.get("tracking_number") and not s.get("order_ref") and not s.get("sub_ref")]
        if pool and facts.merchant and not facts.carrier_sender:
            return pool[0]
        return None

    def _file(self, message: dict[str, Any], facts: Any, *, bootstrap: bool) -> tuple[Optional[str], bool]:
        ts = float(message.get("ts") or self.clock())
        shipment = self._match(facts, message)
        created = False
        if shipment is None:
            if facts.status == DELIVERED and not facts.numbers and not facts.order_ref:
                return None, False            # a survey or "delivered" note about something we never saw
            if facts.status in (FAILED_ATTEMPT, EXCEPTION) and not facts.numbers and not facts.order_ref:
                return None, False
            number = facts.numbers[0] if facts.numbers else None
            carrier = (number or {}).get("carrier") or facts.carrier
            label = facts.item or (self._order_label(facts.merchant, facts.order_ref) if facts.order_ref else facts.merchant or numbers.carrier_name(carrier))
            shipment = self.store.create_shipment(
                label=label[:120], item=facts.item[:200], merchant=facts.merchant, merchant_domain=facts.merchant_domain,
                order_ref=facts.order_ref, sub_ref=facts.sub_ref, carrier=carrier or "", dest_country="ES",
                tracking_number=(number or {}).get("number", ""), tracking_url=numbers.tracking_url(carrier, (number or {}).get("number", "")),
                merchant_url=facts.tracking_link, status=UNKNOWN, source="mail", history_only=bootstrap, created_ts=ts)
            self.store.update_shipment(shipment["id"], last_change_ts=ts)
            created = True
        sid = shipment["id"]
        updates: dict[str, Any] = {}
        if facts.item and not shipment.get("item"):
            updates["item"] = facts.item[:200]
            if not shipment.get("label") or shipment["label"] in (facts.merchant, self._order_label(facts.merchant, shipment.get("order_ref") or "")):
                updates["label"] = facts.item[:120]
        for key in ("order_ref", "sub_ref", "merchant_domain"):
            if getattr(facts, key) and not shipment.get(key):
                updates[key] = getattr(facts, key)
        if facts.order_ref and not shipment.get("item") and not facts.item and shipment.get("label") in ("", facts.merchant, shipment.get("merchant")):
            updates["label"] = self._order_label(facts.merchant or shipment.get("merchant") or "", facts.order_ref)
        if facts.merchant and (not shipment.get("merchant") or (shipment.get("merchant") in ("InPost", "Correos", "UPS", "DHL", "SEUR", "GLS")
                                                                and not facts.carrier_sender)):
            updates["merchant"] = facts.merchant
        if facts.numbers and not shipment.get("tracking_number"):
            n = facts.numbers[0]
            updates["tracking_number"] = n["number"]
            carrier = n.get("carrier") or facts.carrier or shipment.get("carrier") or ""
            updates["carrier"] = carrier
            updates["tracking_url"] = numbers.tracking_url(carrier, n["number"])
            updates["next_check_ts"] = None
        elif facts.carrier and (not shipment.get("carrier") or shipment.get("carrier") == "amazon" and facts.carrier != "amazon"):
            updates["carrier"] = facts.carrier
        if facts.tracking_link and not shipment.get("merchant_url"):
            updates["merchant_url"] = facts.tracking_link
        if facts.eta_from:
            updates.update(merchant_eta_from=facts.eta_from, merchant_eta_to=facts.eta_to or facts.eta_from, merchant_eta_text=facts.eta_text[:120])
            if not shipment.get("merchant_eta_first"):
                updates["merchant_eta_first"] = facts.eta_from
        if facts.promise_min_days is not None or facts.promise_max_days is not None:
            # a promise in the shipping mail beats one in the order confirmation
            if not shipment.get("promise_stage") or facts.status in (IN_TRANSIT, LABEL_CREATED) or shipment.get("promise_stage") == ORDERED:
                updates.update(promise_min_days=facts.promise_min_days, promise_max_days=facts.promise_max_days,
                               promise_business=facts.promise_business, promise_base_ts=ts, promise_stage=facts.status or "")
        if facts.pickup_code or facts.pickup_place or facts.pickup_deadline:
            updates.update(pickup_code=facts.pickup_code or shipment.get("pickup_code") or "",
                           pickup_place=facts.pickup_place or shipment.get("pickup_place") or "",
                           pickup_deadline=facts.pickup_deadline or shipment.get("pickup_deadline") or "")
        if facts.price and not shipment.get("price"):
            updates.update(price=facts.price, currency=facts.currency)
        if updates:
            shipment = self.store.update_shipment(sid, **updates)
        quiet = bootstrap or (self.clock() - ts) > QUIET_AGE_S or shipment.get("history_only")
        if facts.status:
            self.store.add_event(sid, ts=ts, status=facts.status, description=str(message.get("subject") or "")[:300],
                                 location="", source="mail", key=f"mail|{message.get('message_id')}")
            self.apply_status(sid, facts.status, ts, source="mail", text=str(message.get("subject") or ""), quiet=quiet)
        if created and not quiet:
            s = self.store.shipment(sid)
            self.notify(s, N_NEW, "low", self._t("new_title", s), self._t("new_body", s), dedupe=f"{sid}|new")
        return sid, created

    def accept_mail(self, message_id: str) -> dict[str, Any]:
        """Turn a mail filed as "maybe" (or skipped) into a shipment update, as if it had been clear shipping mail."""
        from .mail.parse import MailFacts
        row = self.store.mail(message_id)
        if row is None:
            raise KeyError(f"No mail {message_id}")
        if row.get("kind") == "travel" and self.travel is not None:
            return {"travel": self.travel.accept_mail(message_id)}
        facts = MailFacts(**{k: v for k, v in (row.get("facts") or {}).items() if k in MailFacts.__dataclass_fields__})
        facts.kind = "shipping"
        message = {"message_id": message_id, "ts": row.get("ts"), "subject": row.get("subject"), "from_address": row.get("from_address")}
        sid, created = self._file(message, facts, bootstrap=False)
        if sid is None:
            facts_number = facts.numbers[0]["number"] if facts.numbers else ""
            s = self.store.create_shipment(label=(facts.item or row.get("subject") or "Envío")[:120], merchant=facts.merchant,
                                           order_ref=facts.order_ref, carrier=facts.carrier, tracking_number=facts_number,
                                           tracking_url=numbers.tracking_url(facts.carrier, facts_number) if facts_number else "",
                                           status=facts.status or UNKNOWN, source="mail", dest_country="ES", last_change_ts=self.clock())
            sid, created = s["id"], True
        self.store.set_mail_state(message_id, "linked", sid)
        self.recompute_eta(sid, quiet=True)
        return {"shipment_id": sid, "created": created}

    def ingest_text(self, *, subject: str, text: str, from_address: str = "", when: Optional[float] = None) -> dict[str, Any]:
        """A mail pasted by hand (for shops whose mail is not in the connected inbox)."""
        import hashlib
        ts = when or self.clock()
        mid = "<pasted-" + hashlib.sha1(f"{subject}|{text}".encode("utf-8", "replace")).hexdigest()[:16] + "@phileas>"
        message = {"message_id": mid, "ts": ts, "subject": subject, "text": text, "from_address": from_address, "from_name": "", "links": []}
        if self.store.mail(mid):
            row = self.store.mail(mid)
            return {"facts": row.get("facts"), "already_known": True, "shipments": [row.get("shipment_id")] if row.get("shipment_id") else []}
        summary = self.ingest([message], force=True)
        return {"facts": analyze(message).to_dict(), **summary}

    def _order_label(self, merchant: str, order_ref: str) -> str:
        word = "pedido" if self.lang() == "es" else "order"
        return f"{merchant} · {word} {order_ref}".strip(" ·")

    def history_days(self) -> int:
        try:
            return max(1, int(float(self.setting("mail.history_days", "30"))))
        except ValueError:
            return 30

    def _older_than_live(self, message: dict[str, Any]) -> bool:
        """A mail dated before the live window (``mail.history_days``) only ever feeds the history, however it was fetched."""
        ts = message.get("ts")
        return bool(ts) and (self.clock() - float(ts)) > self.history_days() * DAY

    def activity_ts(self, s: dict[str, Any]) -> float:
        """The newest sign of life of a parcel: the newest carrier or mail event and the newest mail about it. When it has neither, its last
        change. Bookkeeping times (when it was created, last checked or last re-evaluated) say nothing about the parcel itself."""
        times = [e.get("ts") or 0 for e in self.store.events(s["id"], limit=1)]
        times.extend(m.get("ts") or 0 for m in self.store.mails(shipment_id=s["id"], limit=1))
        found = [x for x in times if x]
        if found:
            return float(max(found))
        return float(s.get("last_change_ts") or s.get("created_ts") or 0)

    def _settle(self, s: dict[str, Any]) -> str:
        """Move one parcel to the history quietly: delivered (assumed) when it was out for delivery, archived otherwise."""
        updates: dict[str, Any] = {"history_only": True}
        action = "history"
        if s["status"] not in FINAL:
            if s.get("out_for_delivery_ts") or s["status"] == AVAILABLE_FOR_PICKUP:
                updates.update(status=DELIVERED, delivered_ts=s.get("out_for_delivery_ts") or s.get("status_ts"), delivered_assumed=True,
                               status_text="Entrega supuesta (sin noticias después del reparto)")
                action = "history, delivered (assumed)"
            else:
                updates["archived"] = True
                action = "history, archived"
        updates["next_check_ts"] = None
        self.store.update_shipment(s["id"], **updates)
        self.recompute_eta(s["id"], quiet=True)
        return action

    def _settle_if_stale(self, sid: str) -> None:
        s = self.store.shipment(sid)
        if not s.get("history_only") or s.get("archived") or s["status"] in FINAL:
            return
        if self.clock() - self.activity_ts(s) > self.history_days() * DAY:
            self._settle(s)

    def history_repair(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Apply the live-window rule to existing parcels: every parcel that is neither delivered nor archived and whose newest mail, carrier
        event and change are all older than ``mail.history_days`` moves to the history, quietly. ``dry_run`` only reports."""
        now = self.clock()
        window = self.history_days() * DAY
        changes = []
        for s in self.store.shipments(archived=False, history_only=False, active=True, limit=2000):
            if s.get("source") not in ("mail", "", None):
                continue                                                   # a parcel added by hand is the user's, never settled for them
            last = self.activity_ts(s)
            if now - last <= window:
                continue
            will = "history, delivered (assumed)" if (s.get("out_for_delivery_ts") or s["status"] == AVAILABLE_FOR_PICKUP) else "history, archived"
            changes.append({"id": s["id"], "label": s.get("label") or "", "carrier": s.get("carrier") or "", "status": s["status"],
                            "last_activity": datetime.fromtimestamp(last).date().isoformat(), "days_idle": int((now - last) // DAY), "action": will})
            if not dry_run:
                self._settle(s)
        return {"dry_run": dry_run, "window_days": self.history_days(), "count": len(changes), "shipments": changes}

    def finish_bootstrap(self) -> None:
        """After the first import: settle old parcels so they feed the history instead of waiting for news forever."""
        now = self.clock()
        for s in self.store.shipments(archived=None, history_only=None, limit=2000):
            last = s.get("last_change_ts") or s.get("created_ts") or now
            old = now - last > HISTORY_AGE_DAYS * DAY
            if not old:
                if s.get("history_only"):
                    self.store.update_shipment(s["id"], history_only=False)
                continue
            self._settle(s)

    # ================================================================== status
    def apply_status(self, sid: str, status: str, ts: float, *, source: str, text: str = "", quiet: bool = False) -> bool:
        s = self.store.shipment(sid)
        current = s.get("status") or UNKNOWN
        cur_ts = s.get("status_ts") or 0
        if not status or status == UNKNOWN:
            return False
        if status == NOT_FOUND and current not in (UNKNOWN, NOT_FOUND):
            return False
        if current in FINAL and status not in FINAL:
            return False
        if current == UNKNOWN:
            cur_ts = 0
        newer = ts >= cur_ts - 60
        forward = progress(status) >= progress(current)
        problem = status in (EXCEPTION, FAILED_ATTEMPT, RETURNED)
        if current != UNKNOWN and not (forward and (newer or progress(status) > progress(current)) or (problem and newer)
                                       or (newer and source != "mail")):
            return False
        if status == current and source == "mail" and ts <= cur_ts:
            return False
        updates: dict[str, Any] = {"status": status, "status_ts": ts, "status_source": source, "last_change_ts": max(ts, s.get("last_change_ts") or 0)}
        if text:
            updates["status_text"] = text[:300]
        if status == ORDERED and not s.get("ordered_ts"):
            updates["ordered_ts"] = ts
        # the shipping day: the first "shipped" news (a pickup or delivery notice says nothing about when it left)
        if status in (IN_TRANSIT, LABEL_CREATED, CUSTOMS, OUT_FOR_DELIVERY) and not s.get("shipped_ts"):
            if status != LABEL_CREATED or source == "mail":
                updates["shipped_ts"] = ts
        if status == OUT_FOR_DELIVERY:
            updates["out_for_delivery_ts"] = ts
        if status == DELIVERED:
            updates["delivered_ts"] = ts
            updates["delivered_assumed"] = False
        self.store.update_shipment(sid, **updates)
        if status != current and not quiet:
            self._notify_status(self.store.shipment(sid), current, status)
        if status != current:
            self.emit("phileas.status", {"shipment_id": sid, "from": current, "to": status, "label": s.get("label"), "source": source})
        return status != current

    def _notify_status(self, s: dict[str, Any], old: str, new: str) -> None:
        sid = s["id"]
        if s.get("muted") or s.get("history_only"):
            return
        if new == OUT_FOR_DELIVERY:
            self.notify(s, N_OUT, "high", self._t("out_title", s), self._t("out_body", s), dedupe=f"{sid}|out|{self.today()}")
        elif new == DELIVERED:
            self.notify(s, N_DELIVERED, "medium", self._t("delivered_title", s), self._t("delivered_body", s), dedupe=f"{sid}|delivered")
        elif new == AVAILABLE_FOR_PICKUP:
            self.notify(s, N_PICKUP, "high", self._t("pickup_title", s), self._t("pickup_body", s), dedupe=f"{sid}|pickup")
        elif new in (EXCEPTION, FAILED_ATTEMPT, RETURNED):
            self.notify(s, N_PROBLEM, "high", self._t("problem_title", s, status=new), s.get("status_text") or "",
                        dedupe=f"{sid}|problem|{new}|{int((s.get('status_ts') or 0) // 3600)}")
        elif new == IN_TRANSIT and old in (UNKNOWN, ORDERED, LABEL_CREATED, NOT_FOUND):
            self.notify(s, N_STATUS, "medium", self._t("moving_title", s), self._t("moving_body", s), dedupe=f"{sid}|moving")

    # ================================================================== carriers
    def refresh(self, sid: str, *, reason: str = "schedule") -> dict[str, Any]:
        s = self.store.shipment(sid)
        if not s.get("tracking_number"):
            return {"ok": False, "error": "no tracking number: this parcel is followed from the shop's mails", "shipment": s}
        t0 = time.monotonic()
        raw_path = (self.raw_dir / f"{sid}.json") if self.raw_dir is not None else None
        result, attempts = self.carriers.track(s.get("carrier") or "", s["tracking_number"], raw_path=raw_path)
        now = self.clock()
        updates: dict[str, Any] = {"last_check_ts": now, "check_count": (s.get("check_count") or 0) + 1}
        changed = False
        if result.ok:
            updates.update(fail_count=0, last_error="")
            added = 0
            for ev in sorted(result.events, key=lambda e: e.ts):
                if self.store.add_event(sid, ts=ev.ts, status=ev.status, description=ev.description, location=ev.location, source="carrier",
                                        key="c|" + ev.key()):
                    added += 1
            if result.events:
                first_scan = min((e.ts for e in result.events if e.status not in (LABEL_CREATED, NOT_FOUND)), default=None)
                if first_scan and not s.get("first_scan_ts"):
                    updates["first_scan_ts"] = first_scan
                last = max(result.events, key=lambda e: e.ts)
                updates["last_location"] = last.location or s.get("last_location") or ""
                updates["last_change_ts"] = max(last.ts, s.get("last_change_ts") or 0)
            extra = dict(s.get("extra") or {})
            if (result.eta_time or "") != extra.get("eta_time", ""):
                extra["eta_time"] = result.eta_time or ""
                updates["extra"] = extra
            if result.eta_from:
                updates.update(carrier_eta_from=result.eta_from, carrier_eta_to=result.eta_to or result.eta_from)
                if not s.get("carrier_eta_first"):
                    updates["carrier_eta_first"] = result.eta_from
            for key in ("origin_country", "origin_city", "dest_country", "service"):
                value = getattr(result, key)
                if value and (not s.get(key) or (key == "service" and value != s.get(key))):
                    updates[key] = value
            if result.carrier and result.carrier != s.get("carrier"):
                updates["carrier"] = result.carrier
            self.store.update_shipment(sid, **updates)
            status_ts = max((e.ts for e in result.events), default=now)
            if result.status == DELIVERED and result.delivered_ts:
                status_ts = result.delivered_ts
            changed = self.apply_status(sid, result.status, status_ts, source=result.source, text=result.status_text) or added > 0
            first_scan = bool(updates.get("first_scan_ts") and not s.get("first_scan_ts"))
        else:
            first_scan = False
            updates.update(fail_count=(s.get("fail_count") or 0) + 1, last_error=result.error[:300])
            self.store.update_shipment(sid, **updates)
        s = self.store.shipment(sid)
        self.store.update_shipment(sid, next_check_ts=self.next_check(s, result))
        self.recompute_eta(sid, quiet=first_scan)
        fresh = self.store.shipment(sid)
        if (first_scan and not fresh.get("muted") and not fresh.get("history_only") and fresh["status"] not in FINAL
                and fresh["status"] not in (OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP)):
            self.notify(fresh, N_STATUS, "medium", self._t("scanned_title", fresh), self._t("scanned_body", fresh), dedupe=f"{sid}|first_scan")
        self.store.add_run("check", sid, result.ok, int((time.monotonic() - t0) * 1000),
                           f"{result.source}: {result.status}" + (f" ({result.error})" if result.error else "") + f" via {reason}")
        return {"ok": result.ok, "changed": changed, "source": result.source, "status": result.status, "error": result.error,
                "attempts": attempts, "shipment": self.store.shipment(sid)}

    def next_check(self, s: dict[str, Any], result: Any = None) -> Optional[float]:
        now = self.clock()
        status = s.get("status")
        if status in FINAL or s.get("archived") or not s.get("tracking_number"):
            return None
        minutes = {OUT_FOR_DELIVERY: 30, EXCEPTION: 60, FAILED_ATTEMPT: 60, IN_TRANSIT: 120, CUSTOMS: 180, LABEL_CREATED: 180,
                   AVAILABLE_FOR_PICKUP: 360, NOT_FOUND: 120, ORDERED: 240, UNKNOWN: 60}.get(status or UNKNOWN, 120)
        if status == NOT_FOUND and now - (s.get("created_ts") or now) > DAY:
            minutes = 360
        likely = s.get("eta_likely")
        if status == IN_TRANSIT and likely and likely <= (self.today() + timedelta(days=1)).isoformat():
            minutes = 60
        if result is not None and getattr(result, "source", "") == "ups_web":
            minutes = max(minutes, 60)
        delay = minutes * 60.0
        if result is not None and not result.ok and result.retry_after_s:
            delay = max(delay, float(result.retry_after_s))
        delay *= min(4, 1 + 0.5 * max(0, (s.get("fail_count") or 0) - 1))
        due = now + delay
        quiet_from, quiet_to = int(self.setting("checks.night_from", "23")), int(self.setting("checks.night_to", "7"))
        when = datetime.fromtimestamp(due)
        if status != OUT_FOR_DELIVERY and (when.hour >= quiet_from or when.hour < quiet_to):
            morning = when.replace(hour=quiet_to, minute=5, second=0, microsecond=0)
            if when.hour >= quiet_from:
                morning += timedelta(days=1)
            due = morning.timestamp()
        return due

    # ================================================================== estimates
    def history(self) -> list[dict[str, Any]]:
        return [s for s in self.store.shipments(archived=None, history_only=None, active=False, limit=2000)]

    def recompute_eta(self, sid: str, *, quiet: bool = False) -> dict[str, Any]:
        s = self.store.shipment(sid)
        est = eta_mod.estimate(s, self.history(), self.calendar(), self.today(), self.lang())
        basis = [b for b in est.to_dict()["basis"]]
        old_likely = s.get("eta_likely") or ""
        self.store.update_shipment(sid, eta_from=est.eta_from, eta_to=est.eta_to, eta_likely=est.eta_likely, eta_confidence=est.confidence,
                                   eta_basis=basis)
        extra = dict(s.get("extra") or {})
        extra.update(late=est.late, days_left=est.days_left, similar=est.similar)
        self.store.update_shipment(sid, extra=extra)
        if (not quiet and old_likely and est.eta_likely and est.eta_likely != old_likely and s["status"] in ACTIVE
                and not s.get("history_only") and not s.get("muted") and s["status"] not in (OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP)):
            try:
                shift = (date.fromisoformat(est.eta_likely) - date.fromisoformat(old_likely)).days
            except ValueError:
                shift = 0
            if abs(shift) >= 1:
                fresh = self.store.shipment(sid)
                self.notify(fresh, N_ETA, "medium", self._t("eta_title", fresh, shift=shift), self._t("eta_body", fresh),
                            dedupe=f"{sid}|eta|{est.eta_likely}")
        return est.to_dict()

    # ================================================================== housekeeping
    def housekeeping(self) -> dict[str, int]:
        now, today, cal = self.clock(), self.today(), self.calendar()
        archived = assumed = stale = reminders = 0
        keep_days = int(self.setting("archive.after_days", "5"))
        for s in self.store.shipments(archived=False, history_only=False, limit=1000):
            sid = s["id"]
            if s["status"] in FINAL:
                if s.get("delivered_ts") and now - s["delivered_ts"] > keep_days * DAY:
                    self.store.update_shipment(sid, archived=True)
                    archived += 1
                continue
            # parcels only the shop's mails follow (Amazon): "en reparto" yesterday and silence since → delivered
            if not s.get("tracking_number") and s["status"] == OUT_FOR_DELIVERY and s.get("out_for_delivery_ts"):
                if _date_of(s["out_for_delivery_ts"]) < today:
                    self.store.update_shipment(sid, status=DELIVERED, delivered_ts=s["out_for_delivery_ts"], delivered_assumed=True,
                                               status_text="Entrega supuesta: estaba en reparto y no hubo más noticias", last_change_ts=now)
                    assumed += 1
                    self.recompute_eta(sid, quiet=True)
                    continue
            if s["status"] == NOT_FOUND and now - (s.get("created_ts") or now) > GIVE_UP_NOT_FOUND_DAYS * DAY:
                self.store.update_shipment(sid, archived=True, last_error="the carrier never knew this number")
                archived += 1
                continue
            if s["status"] in (IN_TRANSIT, CUSTOMS, LABEL_CREATED) and s.get("last_change_ts"):
                quiet_days = cal.count(_date_of(s["last_change_ts"]), today, s.get("carrier") or "")
                if quiet_days >= STALE_DELIVERY_DAYS and not s.get("muted"):
                    if self.notify(s, N_STALE, "medium", self._t("stale_title", s), self._t("stale_body", s, days=quiet_days),
                                   dedupe=f"{sid}|stale|{_date_of(s['last_change_ts'])}"):
                        stale += 1
            if s["status"] == AVAILABLE_FOR_PICKUP and s.get("pickup_deadline") and not s.get("muted"):
                try:
                    left = (date.fromisoformat(s["pickup_deadline"]) - today).days
                except ValueError:
                    left = 99
                if 0 <= left <= 2:
                    if self.notify(s, N_PICKUP_DEADLINE, "high", self._t("deadline_title", s, days=left), self._t("pickup_body", s),
                                   dedupe=f"{sid}|deadline|{left}"):
                        reminders += 1
            if s.get("eta_likely"):
                self.recompute_eta(sid)
        return {"archived": archived, "assumed_delivered": assumed, "stale": stale, "pickup_reminders": reminders}

    # ================================================================== notifications
    def notify(self, s: dict[str, Any], type_: str, severity: str, title: str, body: str, *, dedupe: str) -> bool:
        if self.store.notified(dedupe):
            return False
        url = s.get("tracking_url") or s.get("merchant_url") or ""
        event = {"id": f"{s['id']}:{type_}", "type": type_, "severity": severity, "title": title, "summary": body, "url": url,
                 "shipment_id": s["id"], "status": s.get("status"), "eta_likely": s.get("eta_likely"), "label": s.get("label"),
                 "carrier": s.get("carrier"), "tracking_number": s.get("tracking_number")}
        channels = ["toast", "hub", "ntfy", "telegram", "email"]
        try:
            results = self.notifier.send(event, channels)
        except Exception as exc:  # noqa: BLE001
            results = [{"channel": "all", "ok": False, "error": type(exc).__name__}]
        self.store.add_notification(shipment_id=s["id"], type_=type_, severity=severity, title=title, body=body, results=results, dedupe=dedupe)
        return True

    def _t(self, key: str, s: dict[str, Any], **kw: Any) -> str:
        es = self.lang() == "es"
        name = s.get("label") or s.get("item") or s.get("merchant") or s.get("tracking_number") or "envío"
        carrier = numbers.carrier_name(s.get("carrier") or "")
        likely = s.get("eta_likely") or ""
        when = _human_day(likely, self.today(), es) if likely else ""
        texts = {
            "new_title": (f"Nuevo envío: {name}", f"New shipment: {name}"),
            "new_body": ((f"{s.get('merchant') or ''} · {carrier} {s.get('tracking_number') or ''}".strip(" ·") +
                          (f". Llegada estimada {when}" if when else "")),
                         (f"{s.get('merchant') or ''} · {carrier} {s.get('tracking_number') or ''}".strip(" ·") +
                          (f". Expected {when}" if when else ""))),
            "moving_title": (f"En camino: {name}", f"On its way: {name}"),
            "moving_body": ((f"{carrier} ya lo tiene." + (f" Llegada estimada {when}." if when else "")),
                            (f"{carrier} has it." + (f" Expected {when}." if when else ""))),
            "scanned_title": (f"{carrier} ya lo tiene: {name}", f"{carrier} has it: {name}"),
            "scanned_body": ((f"Primer escaneo" + (f" en {s.get('last_location')}" if s.get("last_location") else "") +
                              (f". Llegada estimada {when}." if when else ".")),
                             (f"First scan" + (f" in {s.get('last_location')}" if s.get("last_location") else "") +
                              (f". Expected {when}." if when else "."))),
            "out_title": (f"Llega hoy: {name}", f"Arriving today: {name}"),
            "out_body": (f"{carrier}: en reparto" + (f" entre las {(s.get('extra') or {}).get('eta_time')}" if (s.get('extra') or {}).get('eta_time') else "") + "." + (f" {s.get('status_text')}" if s.get("status_text") and s.get("status_source") != "mail" else ""),
                         f"{carrier}: out for delivery."),
            "delivered_title": (f"Entregado: {name}", f"Delivered: {name}"),
            "delivered_body": (s.get("status_text") or f"{carrier} lo ha entregado.", s.get("status_text") or f"{carrier} delivered it."),
            "pickup_title": (f"Listo para recoger: {name}", f"Ready for pickup: {name}"),
            "pickup_body": (" · ".join(x for x in (s.get("pickup_place"), f"código {s.get('pickup_code')}" if s.get("pickup_code") else "",
                                                     f"hasta el {s.get('pickup_deadline')}" if s.get("pickup_deadline") else "") if x) or carrier,
                            " · ".join(x for x in (s.get("pickup_place"), f"code {s.get('pickup_code')}" if s.get("pickup_code") else "",
                                                     f"until {s.get('pickup_deadline')}" if s.get("pickup_deadline") else "") if x) or carrier),
            "problem_title": (f"{status_label(kw.get('status', ''), 'es')}: {name}", f"{status_label(kw.get('status', ''), 'en')}: {name}"),
            "eta_title": ((f"Se retrasa: {name}" if kw.get("shift", 0) > 0 else f"Se adelanta: {name}"),
                          (f"Later: {name}" if kw.get("shift", 0) > 0 else f"Earlier: {name}")),
            "eta_body": (f"Nueva llegada estimada {when}.", f"New expected arrival {when}."),
            "stale_title": (f"Sin noticias: {name}", f"No news: {name}"),
            "stale_body": (f"{kw.get('days', 0)} días de reparto sin movimiento en {carrier}.",
                           f"{kw.get('days', 0)} delivery days without movement at {carrier}."),
            "deadline_title": ((f"Recógelo {'hoy' if kw.get('days') == 0 else 'mañana' if kw.get('days') == 1 else 'en 2 días'}: {name}"),
                               (f"Pick it up {'today' if kw.get('days') == 0 else 'tomorrow' if kw.get('days') == 1 else 'within 2 days'}: {name}")),
        }
        pair = texts.get(key, (key, key))
        return pair[0] if es else pair[1]


def _human_day(iso: str, today: date, es: bool = True) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    delta = (d - today).days
    if delta == 0:
        return "hoy" if es else "today"
    if delta == 1:
        return "mañana" if es else "tomorrow"
    days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if 1 < delta < 7:
        return (f"el {days_es[d.weekday()]} {d.day}" if es else f"{days_en[d.weekday()]} {d.day}")
    return d.strftime("%d/%m") if es else d.strftime("%b %d")
