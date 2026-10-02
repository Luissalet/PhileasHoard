"""Which source answers for which carrier, in order, and the one call the engine makes: ``Carriers.track``.

Order per carrier (first that answers wins; a failure falls through to the next):

* UPS: official API (with UPS keys) → public page in the off-screen browser → 17TRACK
* Correos: public locator JSON → 17TRACK
* DHL: official API (with a DHL key) → 17TRACK
* Amazon Logistics: mail only (Amazon has no public tracking)
* anything else: 17TRACK
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import httpx

from . import correos, dhl, ups
from ..hoard_link.web.fetch import DEFAULT_USER_AGENT
from .base import TrackResult, fail
from .browser import BrowserRung
from .track17 import Track17

log = logging.getLogger("phileas.carriers")
MAIL_ONLY = {"amazon"}


class Carriers:
    def __init__(self, config: Any, secret: Callable[[str], str], *, transport: Optional[httpx.BaseTransport] = None,
                 browser: Any = None, setting: Callable[[str, str], str] = lambda k, d: d):
        self.config = config
        self.secret = secret
        self.setting = setting
        self.transport = transport
        self.browser = browser if browser is not None else BrowserRung(config)
        self._ups_api: Optional[ups.UpsApi] = None
        self._ups_key = ("", "")

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=getattr(self.config, "http_timeout_s", 25.0), follow_redirects=True,
                            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept-Language": "es-ES,es;q=0.9,en;q=0.6"})

    # ------------------------------------------------------------------ plans
    def plan(self, carrier: str) -> list[str]:
        """Source ids that would be tried for this carrier now, in order."""
        web_ok = self.setting("carriers.web_pages", "1") == "1"
        has17 = bool(self.secret("TRACK17_KEY"))
        steps: list[str] = []
        if carrier == "ups":
            if self.secret("UPS_CLIENT_ID") and self.secret("UPS_CLIENT_SECRET"):
                steps.append("ups_api")
            if web_ok and self.browser is not None and self.browser.available()[0]:
                steps.append("ups_web")
        elif carrier == "correos":
            steps.append("correos")
        elif carrier == "dhl":
            if self.secret("DHL_API_KEY"):
                steps.append("dhl_api")
        if carrier in MAIL_ONLY:
            return []
        if has17:
            steps.append("track17")
        return steps

    def sources(self) -> dict[str, Any]:
        ok, why = self.browser.available() if self.browser is not None else (False, "off")
        return {"track17": bool(self.secret("TRACK17_KEY")), "ups_api": bool(self.secret("UPS_CLIENT_ID") and self.secret("UPS_CLIENT_SECRET")),
                "dhl_api": bool(self.secret("DHL_API_KEY")), "browser": {"available": ok, "reason": why,
                                                                          "enabled": self.setting("carriers.web_pages", "1") == "1",
                                                                          "channel": getattr(self.browser, "channel", "")},
                "correos": True}

    # ------------------------------------------------------------------ track
    def track(self, carrier: str, number: str, *, raw_path: Any = None) -> tuple[TrackResult, list[dict[str, Any]]]:
        attempts: list[dict[str, Any]] = []
        steps = self.plan(carrier)
        if getattr(self.config, "offline", False):
            return fail("offline", "offline mode"), attempts
        if not steps:
            why = ("Amazon Logistics has no public tracking: Phileas follows it from Amazon's mails"
                   if carrier in MAIL_ONLY else
                   "No source for this carrier yet: add a 17TRACK key in Settings (free, 100 numbers a month)")
            return fail("none", why, 24 * 3600), attempts
        result: Optional[TrackResult] = None
        with self._client() as client:
            for step in steps:
                try:
                    result = self._run(step, carrier, number, client)
                except Exception as exc:  # noqa: BLE001 — an adapter bug must not stop the others
                    log.exception("carrier source %s failed", step)
                    result = fail(step, f"{type(exc).__name__}: {str(exc)[:160]}", 3600)
                attempts.append({"source": step, "ok": result.ok, "found": result.found, "status": result.status, "error": result.error})
                if result.ok and (result.found or step == steps[-1]):
                    break
                if result.ok and not result.found and step == "ups_web":
                    # UPS itself says "not scanned yet"; 17TRACK would only repeat it and spend quota.
                    break
        assert result is not None
        if raw_path is not None and result.raw is not None:
            try:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(result.raw, ensure_ascii=False, indent=1, default=str)[:400_000], encoding="utf-8")
            except OSError:
                pass
        return result, attempts

    def _run(self, step: str, carrier: str, number: str, client: httpx.Client) -> TrackResult:
        if step == "correos":
            return correos.track(number, client)
        if step == "ups_api":
            key = (self.secret("UPS_CLIENT_ID"), self.secret("UPS_CLIENT_SECRET"))
            if self._ups_api is None or self._ups_key != key:
                self._ups_api, self._ups_key = ups.UpsApi(*key, client=client), key
            self._ups_api.client = client
            return self._ups_api.track(number)
        if step == "ups_web":
            return ups.track_web(number, self.browser)
        if step == "dhl_api":
            return dhl.track(number, self.secret("DHL_API_KEY"), client)
        if step == "track17":
            return Track17(self.secret("TRACK17_KEY"), client).track(number, carrier)
        return fail(step, "unknown source")

    def close(self) -> None:
        if self.browser is not None and hasattr(self.browser, "close"):
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["Carriers", "TrackResult", "MAIL_ONLY"]
