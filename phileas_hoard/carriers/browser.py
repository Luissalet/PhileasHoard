"""Browser rung: open a carrier's public tracking page and read the JSON its own script loads.

* Playwright (optional dependency) drives Edge on Windows (always installed), then Chrome, then Playwright's Chromium.
* The window is a real one placed off-screen: carrier sites refuse headless browsers (UPS answers a download instead of
  the page), and an off-screen window looks like any visit. One persistent profile in ``data/browser-profile``.
* The sync API is bound to its thread, so every call runs on one worker thread; one page at a time.
* Nothing here defeats a challenge: if the page shows one, the read fails and the shipment keeps its last status.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import queue
import sys
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable, Optional

log = logging.getLogger("phileas.browser")

IDLE_CLOSE_S = 120.0
OFFSCREEN_ARGS = ["--window-position=-32000,-32000", "--window-size=1280,900", "--disable-features=CalculateNativeWinOcclusion",
                  "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding", "--no-first-run",
                  "--no-default-browser-check"]


def playwright_installed() -> bool:
    try:
        return importlib.util.find_spec("playwright") is not None
    except (ImportError, ValueError):
        return False


def channel_order(platform: Optional[str] = None) -> list[Optional[str]]:
    platform = platform or sys.platform
    if platform.startswith("win"):
        return ["msedge", "chrome", None]
    return ["chrome", None, "msedge"]


class BrowserRung:
    def __init__(self, config: Any, *, factory: Optional[Callable[[], Any]] = None):
        self.config = config
        self._factory = factory
        self._queue: "queue.Queue[tuple[Callable[[], Any], Future] | None]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._start_lock = threading.Lock()
        self._pw: Any = None
        self._ctx: Any = None
        self.channel = ""
        self.last_error = ""

    # ------------------------------------------------------------------ availability
    def available(self) -> tuple[bool, str]:
        if not getattr(self.config, "browser", True):
            return False, "the browser rung is off (PHILEAS_BROWSER=0)"
        if getattr(self.config, "offline", False):
            return False, "offline"
        if self._factory is None and not playwright_installed():
            return False, "Playwright is not installed (python -m pip install playwright)"
        return True, ""

    # ------------------------------------------------------------------ worker
    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="phileas-browser", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=IDLE_CLOSE_S)
            except queue.Empty:
                self._close_in_worker()
                continue
            if item is None:
                self._close_in_worker()
                return
            fn, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn())
            except BaseException as error:  # noqa: BLE001
                future.set_exception(error)

    def _call(self, fn: Callable[[], Any], timeout: float) -> Any:
        self._ensure_thread()
        future: Future = Future()
        self._queue.put((fn, future))
        return future.result(timeout=timeout)

    def _context(self) -> Any:
        if self._ctx is not None:
            return self._ctx
        if self._factory is not None:
            self._pw = self._factory()
        else:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
            self._pw = sync_playwright().start()
        errors = []
        profile = self.config.browser_profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        for channel in channel_order():
            kwargs: dict[str, Any] = dict(user_data_dir=str(profile), headless=False, locale="es-ES", args=OFFSCREEN_ARGS,
                                          accept_downloads=False, no_viewport=True)
            if channel:
                kwargs["channel"] = channel
            try:
                self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
                self.channel = channel or "chromium"
                return self._ctx
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{channel or 'chromium'}: {str(exc).strip().splitlines()[0][:120] if str(exc).strip() else type(exc).__name__}")
        raise RuntimeError("no browser could be started (" + "; ".join(errors) + ")")

    def _close_in_worker(self) -> None:
        for obj, method in ((self._ctx, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:  # noqa: BLE001
                    pass
        self._ctx = None
        self._pw = None

    # ------------------------------------------------------------------ public
    def capture_json(self, url: str, match: str, *, timeout_s: float = 45.0) -> tuple[Optional[Any], str]:
        """Open ``url`` and return the first JSON response whose URL contains ``match`` (and an error text on failure)."""
        ok, why = self.available()
        if not ok:
            return None, why

        def work() -> tuple[Optional[Any], str]:
            ctx = self._context()
            page = ctx.new_page()
            got: dict[str, Any] = {}

            def on_response(response: Any) -> None:
                if match in response.url and "data" not in got:
                    try:
                        got["data"] = response.json()
                    except Exception as exc:  # noqa: BLE001
                        try:
                            got["data"] = json.loads(response.text())
                        except Exception:  # noqa: BLE001
                            got["error"] = f"unreadable answer ({type(exc).__name__})"

            page.on("response", on_response)
            try:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
                except Exception as exc:  # noqa: BLE001 — a late navigation error after the data arrived is fine
                    if "data" not in got:
                        got.setdefault("error", f"navigation: {str(exc).strip().splitlines()[0][:160]}")
                deadline = time.monotonic() + timeout_s
                while "data" not in got and time.monotonic() < deadline:
                    page.wait_for_timeout(400)
                if "data" in got:
                    return got["data"], ""
                text = ""
                try:
                    text = page.inner_text("body")[:400]
                except Exception:  # noqa: BLE001
                    pass
                blocked = any(w in text.lower() for w in ("captcha", "access denied", "blocked", "robot"))
                return None, got.get("error") or ("the page asked for a human check" if blocked else "no tracking data within the time limit")
            finally:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

        try:
            data, error = self._call(work, timeout=timeout_s + 60)
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            try:
                self._call(self._close_in_worker, timeout=20)
            except Exception:  # noqa: BLE001
                pass
            return None, self.last_error
        self.last_error = error
        return data, error

    def close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=10)
