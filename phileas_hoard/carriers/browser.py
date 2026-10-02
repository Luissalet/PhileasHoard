"""Browser rung for the carriers: the shared ``web.browser.BrowserRung`` behind the answers the carrier code expects.

UPS opens its public tracking page in a real window placed off-screen (UPS answers a download instead of the page to a
headless browser) and reads the JSON the page's own script loads: ``capture_json(..., offscreen=True)`` in the commons.
This wrapper only adds this app's switches (``PHILEAS_BROWSER=0``, offline) and the ``(ok, why)`` form of ``available()``.
Nothing here defeats a challenge: if the page shows one, the read fails and the shipment keeps its last status.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..hoard_link.web.browser import BrowserRung as _SharedRung, channel_order, playwright_installed  # noqa: F401


class BrowserRung:
    def __init__(self, config: Any, *, factory: Optional[Callable[[], Any]] = None):
        self.config = config
        self.rung = _SharedRung(config.browser_profile_dir, headless=False, locale="es-ES", playwright_factory=factory)

    @property
    def channel(self) -> str:
        return self.rung.channel_used

    @property
    def last_error(self) -> str:
        return getattr(self.rung, "last_error", "")

    def available(self) -> tuple[bool, str]:
        if not getattr(self.config, "browser", True):
            return False, "the browser rung is off (PHILEAS_BROWSER=0)"
        if getattr(self.config, "offline", False):
            return False, "offline"
        if not self.rung.available():
            return False, self.rung.unavailable_reason()
        return True, ""

    def capture_json(self, url: str, match: str, *, timeout_s: float = 45.0) -> tuple[Optional[Any], str]:
        """Open ``url`` and return the first JSON response whose URL contains ``match`` (and an error text on failure)."""
        ok, why = self.available()
        if not ok:
            return None, why
        return self.rung.capture_json(url, match, timeout_s=timeout_s, offscreen=True)

    def close(self) -> None:
        self.rung.close()
