"""Wiring: database, mail source, carriers, notifier, engine and scheduler behind one object that the API routers and
the agent tools share."""

from __future__ import annotations

import logging
import os
import secrets as _secrets
import time
from datetime import date, timedelta
from typing import Any, Callable, Optional

import httpx

from . import SERVICE, __version__, numbers
from .bizdays import REGIONS
from .carriers import Carriers
from .config import Config
from .db import Database
from .engine import Engine
from .errors import PhileasError
from .mail.source import FaustusMail
from .model import (ACTIVE, AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, FAILED_ATTEMPT, FINAL, OUT_FOR_DELIVERY, RETURNED, STATUSES,
                    UNKNOWN, label as status_label, progress)
from .notify import CHANNELS, EMAIL_BACKENDS, Notifier
from .scheduler import Scheduler
from .store import Store
from .travel import airports as travel_airports
from .travel.llm import make_link_chat
from .travel.model import KINDS as TRAVEL_KINDS
from .travel.service import DEFAULTS as TRAVEL_DEFAULTS, Travel
from .travel.store import TravelStore

log = logging.getLogger("phileas")

SECRET_NAMES = ("TRACK17_KEY", "UPS_CLIENT_ID", "UPS_CLIENT_SECRET", "DHL_API_KEY", "FAUSTUS_DIR", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID",
                "NTFY_TOPIC", "NTFY_TOKEN", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_TO")
SHOWN_SECRETS = ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_TO", "TELEGRAM_CHAT_ID", "FAUSTUS_DIR", "UPS_CLIENT_ID")
UI_SETTINGS: dict[str, Optional[tuple[str, ...]]] = {
    "ui.language": ("es", "en"),
    "scheduler.paused": ("0", "1"),
    "mail.enabled": ("1", "0"),
    "mail.interval_min": None,
    "mail.window_days": None,
    "mail.first_days": None,
    "mail.faustus_dir": None,
    "mail.faustus_owner": None,
    "carriers.web_pages": ("1", "0"),
    "eta.region": REGIONS,
    "eta.extra_holidays": None,
    "archive.after_days": None,
    "checks.night_from": None,
    "checks.night_to": None,
    "notify.ntfy.server": None,
    "notify.email.backend": EMAIL_BACKENDS,
    "travel.enabled": ("1", "0"),
    "travel.home_city": None,
    "travel.home_airports": None,
    "travel.home_tz": None,
    "travel.gap_days": None,
    "travel.kinds": None,
    "travel.departure_hours": None,
    "travel.tomorrow_hour": None,
    "travel.my_name": None,
    "travel.model_fallback": ("1", "0"),
    "travel.docs_check": ("1", "0"),
    "travel.docs_days": None,
    "travel.ledger_account": None,
    **{f"notify.{c}.enabled": ("1", "0") for c in CHANNELS},
    **{f"notify.{c}.min_severity": ("low", "medium", "high") for c in CHANNELS},
}
DEFAULTS = {"ui.language": "es", "scheduler.paused": "0", "mail.enabled": "1", "mail.interval_min": "10", "mail.window_days": "14",
            "mail.first_days": "120", "carriers.web_pages": "1", "eta.region": "ES-MD", "archive.after_days": "5",
            "checks.night_from": "23", "checks.night_to": "7", "notify.ntfy.server": "https://ntfy.sh", "notify.email.backend": "auto", **TRAVEL_DEFAULTS}
NUMERIC = {"travel.gap_days": (0, 14), "travel.departure_hours": (1, 24), "travel.tomorrow_hour": (0, 23), "travel.docs_days": (1, 365), "mail.interval_min": (2, 1440), "mail.window_days": (1, 365), "mail.first_days": (1, 730), "archive.after_days": (0, 365),
           "checks.night_from": (0, 24), "checks.night_to": (0, 24)}


def write_token(config: Config) -> str:
    """The MCP token is persistent: created once, reused on every later start."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        existing = config.token_path.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if len(existing) >= 32:
        return existing
    token = _secrets.token_hex(32)
    config.token_path.write_text(token, encoding="utf-8")
    try:
        config.token_path.chmod(0o600)
    except OSError:
        pass
    return token


def write_url(config: Config) -> None:
    try:
        config.url_path.write_text(f"http://127.0.0.1:{config.port}", encoding="utf-8")
    except OSError:
        pass


class Services:
    def __init__(self, config: Config, *, http_transport: Optional[httpx.BaseTransport] = None, clock_fn: Callable[[], float] = time.time,
                 notifier: Any = None, browser: Any = None, mail_runner: Optional[Callable[..., Any]] = None, mail_source: Any = None,
                 travel_chat: Optional[Callable[..., Any]] = None, hub_call: Optional[Callable[..., Any]] = None):
        self.config = config
        self.clock = clock_fn
        self.started_at = time.time()
        for d in (config.data_dir, config.cache_dir, config.logs_dir, config.raw_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.token = write_token(config)
        write_url(config)
        self.db = Database(config.db_path)
        self.store = Store(self.db, clock_fn)
        self._load_secrets()
        self.notifier = notifier or Notifier(config, self.db.get_setting, clock=clock_fn)
        self.mail = mail_source or FaustusMail(self.setting, config.secret, runner=mail_runner, clock=clock_fn)
        self.carriers = Carriers(config, config.secret, transport=http_transport, browser=browser, setting=self.setting)
        self.tstore = TravelStore(self.db, clock_fn)
        self.travel = Travel(self.store, self.tstore, self.notifier, setting=self.setting, set_setting=self.db.set_setting, emit=self._emit, clock=clock_fn,
                             chat=travel_chat or make_link_chat(config.backend_json_path, config.offline), call=hub_call or self._hub_call)
        self.engine = Engine(self.store, self.carriers, self.notifier, settings_get=self.db.get_setting, settings_set=self.db.set_setting,
                             emit=self._emit, clock=clock_fn, raw_dir=config.raw_dir, mail_source=self.mail, travel=self.travel)
        self.scheduler = Scheduler(self.engine, self.store, clock=clock_fn, enabled=config.scheduler,
                                   paused=lambda: self.setting("scheduler.paused") == "1",
                                   mail_interval_min=lambda: float(self.setting("mail.interval_min") or 10),
                                   mail_enabled=lambda: self.setting("mail.enabled") == "1" and not config.offline, travel_tick=self.travel.tick)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self.config.scheduler:
            self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.stop()
        self.carriers.close()
        self.db.close()

    def _hub_call(self, app: str, tool: str, arguments: Optional[dict[str, Any]] = None, **kw: Any) -> dict[str, Any]:
        """Calls to the other Hoards through the hub; offline mode never leaves the process."""
        if self.config.offline:
            return {"ok": False, "app": app, "tool": tool, "status": None, "error": "hub not reachable (offline mode)"}
        from .hoard_link import family
        return family.call(app, tool, arguments, **kw)

    def _emit(self, type_: str, data: dict[str, Any]) -> None:
        try:
            from .hoard_link import family
            family.emit(type_, data)
        except Exception:  # noqa: BLE001 — events are hints; the database is the truth
            pass

    # ------------------------------------------------------------------ settings and secrets
    def setting(self, key: str, default: Optional[str] = None) -> str:
        value = self.db.get_setting(key, None)
        if value in (None, ""):
            if default is not None:
                return default
            if key.endswith(".enabled") and key.startswith("notify."):
                from .notify import DEFAULT_ENABLED
                return "1" if DEFAULT_ENABLED.get(key.split(".")[1]) else "0"
            if key.endswith(".min_severity"):
                return "medium" if key == "notify.email.min_severity" else "low"
            return DEFAULTS.get(key, "")
        return str(value)

    def settings(self) -> dict[str, str]:
        return {key: self.setting(key) for key in UI_SETTINGS}

    def set_settings(self, values: dict[str, Any]) -> dict[str, str]:
        for key, value in values.items():
            if key not in UI_SETTINGS:
                raise PhileasError("invalid", f"Unknown setting {key}.", f"Known: {', '.join(UI_SETTINGS)}.")
            value = ("1" if value else "0") if isinstance(value, bool) else str(value).strip()
            allowed = UI_SETTINGS[key]
            if allowed and value not in allowed:
                raise PhileasError("invalid", f"{key} must be one of {', '.join(a or '(none)' for a in allowed)}.")
            if key in NUMERIC and value:
                try:
                    number = int(float(value))
                except ValueError as exc:
                    raise PhileasError("invalid", f"{key} must be a number.") from exc
                lo, hi = NUMERIC[key]
                if not lo <= number <= hi:
                    raise PhileasError("invalid", f"{key} must be between {lo} and {hi}.")
                value = str(number)
            if key == "travel.home_tz" and value and not travel_airports.valid_tz(value):
                raise PhileasError("invalid", f"{value!r} is not a time zone.", "Use a name like Europe/Madrid or Atlantic/Canary.")
            if key == "travel.home_airports" and value:
                codes = [c.strip().upper() for c in value.replace(";", ",").split(",") if c.strip()]
                bad = [c for c in codes if not travel_airports.known(c)]
                if bad:
                    raise PhileasError("invalid", f"Unknown airport code {', '.join(bad)}.", "Use IATA codes such as MAD, BCN.")
                value = ",".join(codes)
            if key == "travel.kinds" and value:
                kinds = [c.strip() for c in value.split(",") if c.strip()]
                bad = [c for c in kinds if c not in TRAVEL_KINDS]
                if bad:
                    raise PhileasError("invalid", f"Unknown segment kind {', '.join(bad)}.", f"Known: {', '.join(TRAVEL_KINDS)}.")
                value = ",".join(kinds)
            if key == "eta.extra_holidays" and value:
                for chunk in value.replace(";", ",").split(","):
                    try:
                        date.fromisoformat(chunk.strip())
                    except ValueError as exc:
                        raise PhileasError("invalid", f"Holiday {chunk.strip()!r} is not YYYY-MM-DD.") from exc
            self.db.set_setting(key, value)
        return self.settings()

    def _load_secrets(self) -> None:
        for name in SECRET_NAMES:
            value = self.db.get_setting(f"secret.{name}")
            key = f"PHILEAS_{name}"
            if value and key not in self.config.secrets:
                self.config.secrets[key] = value

    def set_secret(self, name: str, value: str) -> dict[str, Any]:
        name = name.upper().removeprefix("PHILEAS_")
        if name not in SECRET_NAMES:
            raise PhileasError("invalid", f"Unknown secret {name}.", f"Known: {', '.join(SECRET_NAMES)}.")
        key = f"PHILEAS_{name}"
        value = (value or "").strip()
        if value:
            self.db.set_setting(f"secret.{name}", value)
            self.config.secrets[key] = value
        else:
            self.db.execute("DELETE FROM settings WHERE key = ?", (f"secret.{name}",))
            self.config.secrets.pop(key, None)
        return self.secrets_status()[name]

    def secrets_status(self) -> dict[str, dict[str, Any]]:
        out = {}
        for name in SECRET_NAMES:
            key = f"PHILEAS_{name}"
            value = self.config.secret(name)
            env = bool(os.environ.get(key))
            db = self.db.get_setting(f"secret.{name}") is not None
            source = "env" if env else ("settings" if db else (".env" if value else ""))
            shown = value if name in SHOWN_SECRETS else (("…" + value[-4:]) if len(value) >= 8 else ("****" if value else ""))
            out[name] = {"configured": bool(value), "source": source, "value": shown}
        return out

    # ------------------------------------------------------------------ views
    def card(self, s: dict[str, Any]) -> dict[str, Any]:
        extra = s.get("extra") or {}
        lang = self.setting("ui.language")
        return {**{k: s.get(k) for k in ("id", "label", "item", "merchant", "order_ref", "carrier", "tracking_number", "tracking_url",
                                          "merchant_url", "status", "status_text", "status_ts", "status_source", "last_location", "eta_from",
                                          "eta_to", "eta_likely", "eta_confidence", "pickup_code", "pickup_place", "pickup_deadline",
                                          "delivered_ts", "delivered_assumed", "shipped_ts", "ordered_ts", "last_check_ts", "next_check_ts",
                                          "last_error", "archived", "muted", "history_only", "price", "currency", "origin_country",
                                          "service", "created_ts", "last_change_ts", "notes", "source", "fail_count")},
                "carrier_name": numbers.carrier_name(s.get("carrier") or ""), "status_label": status_label(s.get("status") or UNKNOWN, lang),
                "progress": progress(s.get("status") or UNKNOWN), "late": bool(extra.get("late")), "eta_time": extra.get("eta_time") or "", "days_left": extra.get("days_left"),
                "eta_basis": (s.get("eta_basis") or [])[:3], "mail_only": not s.get("tracking_number")}

    def detail(self, sid: str) -> dict[str, Any]:
        s = self.store.find_shipment(sid)
        extra = s.get("extra") or {}
        return {"shipment": {**self.card(s), "eta_basis": s.get("eta_basis") or [], "carrier_eta_from": s.get("carrier_eta_from"),
                             "carrier_eta_to": s.get("carrier_eta_to"), "merchant_eta_from": s.get("merchant_eta_from"),
                             "merchant_eta_to": s.get("merchant_eta_to"), "merchant_eta_text": s.get("merchant_eta_text"),
                             "promise_min_days": s.get("promise_min_days"), "promise_max_days": s.get("promise_max_days"),
                             "promise_business": s.get("promise_business"), "check_count": s.get("check_count"),
                             "fail_count": s.get("fail_count"), "sub_ref": s.get("sub_ref"), "origin_city": s.get("origin_city"),
                             "dest_country": s.get("dest_country")},
                "events": self.store.events(s["id"]),
                "mails": [{k: m.get(k) for k in ("message_id", "ts", "from_address", "subject", "kind", "snippet")}
                          for m in self.store.mails(shipment_id=s["id"], limit=50)],
                "similar": extra.get("similar") or [],
                "sources": self.carriers.plan(s.get("carrier") or "") if s.get("tracking_number") else [],
                "notifications": [n for n in self.store.notifications(limit=200) if n.get("shipment_id") == s["id"]][:20]}

    def dashboard(self) -> dict[str, Any]:
        now = self.clock()
        today = date.fromtimestamp(now).isoformat()
        active = [self.card(s) for s in self.store.shipments(archived=False, history_only=False, active=True, limit=300)]
        active.sort(key=lambda c: (c["eta_likely"] or "9999", -(c["progress"] or 0)))
        attention = [c for c in active if c["status"] in (EXCEPTION, FAILED_ATTEMPT, AVAILABLE_FOR_PICKUP) or c["late"] or
                     (c["last_error"] and (c.get("fail_count") or 0) >= 3)]
        today_list = [c for c in active if c["status"] == OUT_FOR_DELIVERY or c["eta_likely"] == today]
        week = (date.fromtimestamp(now) - timedelta(days=7)).isoformat()
        delivered = [self.card(s) for s in self.store.shipments(archived=None, history_only=False, active=False, limit=40)
                     if s.get("delivered_ts") and date.fromtimestamp(s["delivered_ts"]).isoformat() >= week]
        last_visit = float(self.db.get_setting("dashboard.last_visit_ts", "0") or 0)
        news = [n for n in self.store.notifications(limit=30) if n["ts"] > last_visit]
        return {"now": now, "today": today, "active": active, "today_list": today_list, "attention": attention, "delivered": delivered,
                "news": news, "last_visit_ts": last_visit or None, "counts": self.store.counts(),
                "review": [{k: m.get(k) for k in ("message_id", "ts", "from_address", "subject", "snippet", "score")}
                           for m in self.store.mails(kind=["maybe"], state=["new"], limit=10)],
                "mail": {"last_scan_ts": float(self.setting("mail.last_scan_ts") or 0) or None, "last_error": self.setting("mail.last_error"),
                         "enabled": self.setting("mail.enabled") == "1"},
                "scheduler": self.scheduler.status(), "sources": self.carriers.sources(), "travel": self._travel_block()}

    def _travel_block(self) -> dict[str, Any]:
        """The travel facet in the dashboard: what is on now, the next trip and what needs a look. Never breaks the dashboard."""
        try:
            o = self.travel.overview()
            return {k: o[k] for k in ("enabled", "ongoing", "today_items", "next_trip", "checkins", "needs_review", "counts")}
        except Exception:  # noqa: BLE001
            log.exception("travel block failed")
            return {"enabled": False, "ongoing": [], "today_items": [], "next_trip": None, "checkins": [], "needs_review": {"mails": 0, "segments": 0}, "counts": {}}

    def mark_visit(self) -> dict[str, Any]:
        now = self.clock()
        n = self.store.mark_notifications_seen(now)
        self.db.set_setting("dashboard.last_visit_ts", str(now))
        return {"marked_seen": n, "last_visit_ts": now}

    def stats(self) -> dict[str, Any]:
        """Delivery times on past parcels, per carrier and per shop (delivery days from shipped to delivered)."""
        from .eta import transit_days
        cal = self.engine.calendar()
        groups: dict[str, dict[str, list[int]]] = {"carrier": {}, "merchant": {}}
        accuracy: dict[str, list[int]] = {}
        for s in self.engine.history():
            days = transit_days(s, cal)
            if days is None or days > 60:
                continue
            groups["carrier"].setdefault(s.get("carrier") or "", []).append(days)
            groups["merchant"].setdefault(s.get("merchant") or "", []).append(days)
            for key in ("carrier_eta_first", "merchant_eta_first"):
                promised = s.get(key)
                real = date.fromtimestamp(s["delivered_ts"]) if s.get("delivered_ts") else None
                if promised and real:
                    try:
                        delta = (real - date.fromisoformat(promised)).days
                    except ValueError:
                        continue
                    accuracy.setdefault(f"{key.split('_')[0]}:{s.get('carrier') if key.startswith('carrier') else s.get('merchant')}", []).append(delta)

        def summary(values: list[int]) -> dict[str, Any]:
            values = sorted(values)
            mid = values[len(values) // 2]
            return {"n": len(values), "min": values[0], "median": mid, "max": values[-1], "avg": round(sum(values) / len(values), 1)}
        return {"by_carrier": {k: {**summary(v), "name": numbers.carrier_name(k) or ("Sin identificar" if self.setting("ui.language") == "es" else "Unknown")} for k, v in sorted(groups["carrier"].items())},
                "by_merchant": {k: summary(v) for k, v in sorted(groups["merchant"].items())},
                "promise_accuracy": {k: {"n": len(v), "avg_days_late": round(sum(v) / len(v), 2), "on_time_or_early": sum(1 for x in v if x <= 0)}
                                     for k, v in sorted(accuracy.items())}}

    # ------------------------------------------------------------------ status
    def counts(self) -> dict[str, int]:
        return self.store.counts()

    def status(self) -> dict[str, Any]:
        return {"service": SERVICE, "version": __version__, "data_dir": str(self.config.data_dir), "uptime_s": int(time.time() - self.started_at),
                "counts": self.counts(), "travel": self.tstore.counts(), "scheduler": self.scheduler.status(), "channels": self.notifier.channels_status(),
                "sources": self.carriers.sources(), "mail": {"faustus_dir": str(self.mail.faustus_dir() or ""),
                                                              "last_scan_ts": float(self.setting("mail.last_scan_ts") or 0) or None,
                                                              "last_error": self.setting("mail.last_error"),
                                                              "first_scan_done": self.setting("mail.first_scan_done") == "1"},
                "offline": self.config.offline, "recent_runs": self.store.runs(limit=12)}

    # ------------------------------------------------------------------ manual shipments
    def add_manual(self, number: str, *, carrier: str = "", label: str = "", merchant: str = "", notes: str = "") -> dict[str, Any]:
        number = numbers.normalize(number)
        if not numbers.plausible(number):
            raise PhileasError("invalid", f"{number!r} does not look like a tracking number.", "8-35 letters and digits, at least four digits.")
        existing = self.store.by_number(number)
        if existing:
            return {"created": False, "shipment": self.card(existing)}
        fmt_carrier, _ = numbers.classify(number)
        carrier = (carrier or fmt_carrier or "").lower()
        if carrier and carrier not in numbers.CARRIERS:
            raise PhileasError("invalid", f"Unknown carrier {carrier}.", f"Known: {', '.join(sorted(numbers.CARRIERS))}.")
        s = self.store.create_shipment(label=(label or merchant or numbers.carrier_name(carrier) or number)[:120], merchant=merchant[:60],
                                       carrier=carrier, tracking_number=number, tracking_url=numbers.tracking_url(carrier or "other", number),
                                       status=UNKNOWN, source="manual", notes=notes[:2000], dest_country="ES", last_change_ts=self.clock())
        self.engine.recompute_eta(s["id"], quiet=True)
        return {"created": True, "shipment": self.card(self.store.shipment(s["id"]))}

    def edit(self, sid: str, fields: dict[str, Any]) -> dict[str, Any]:
        s = self.store.find_shipment(sid)
        allowed = {"label", "merchant", "carrier", "tracking_number", "notes", "archived", "muted", "origin_country", "item"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "tracking_number" in updates:
            updates["tracking_number"] = numbers.normalize(updates["tracking_number"])
            if updates["tracking_number"] and not numbers.plausible(updates["tracking_number"]):
                raise PhileasError("invalid", "That does not look like a tracking number.")
            updates["next_check_ts"] = None
        if "carrier" in updates:
            updates["carrier"] = str(updates["carrier"]).lower()
            if updates["carrier"] and updates["carrier"] not in numbers.CARRIERS:
                raise PhileasError("invalid", f"Unknown carrier {updates['carrier']}.")
        if "tracking_number" in updates or "carrier" in updates:
            carrier = updates.get("carrier", s.get("carrier") or "")
            number = updates.get("tracking_number", s.get("tracking_number") or "")
            updates["tracking_url"] = numbers.tracking_url(carrier or "other", number) if number else ""
        if "status" in fields and fields["status"]:
            if fields["status"] not in STATUSES:
                raise PhileasError("invalid", f"Unknown status {fields['status']}.")
        self.store.update_shipment(s["id"], **updates)
        if fields.get("status"):
            self.engine.apply_status(s["id"], fields["status"], self.clock(), source="manual", text="Marcado a mano", quiet=True)
            if fields["status"] in FINAL:
                self.store.update_shipment(s["id"], delivered_ts=self.clock() if fields["status"] == DELIVERED else s.get("delivered_ts"))
        self.engine.recompute_eta(s["id"], quiet=True)
        return self.card(self.store.shipment(s["id"]))


__all__ = ["Services", "SECRET_NAMES", "UI_SETTINGS", "ACTIVE", "RETURNED"]
