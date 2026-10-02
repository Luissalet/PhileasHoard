"""Background work in three lanes, one job at a time each.

* ``checks``: carrier checks of due shipments (the browser can only serve one page at a time anyway).
* ``mail``: the mail scan (every ``mail.interval_min``, default 10) and housekeeping (hourly).
* ``travel``: the travel reminders (check-in, departures, trips tomorrow), every minute, on their own lane so a long mail scan never delays them.

A job that raises is logged and never stops its lane. "Check now" and "Scan now" go through the same queues.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger("phileas.scheduler")

TICK_S = 20.0
HOUSEKEEPING_S = 3600.0
TRAVEL_EVERY_S = 60.0
LANES = ("checks", "mail", "travel")


@dataclass
class Job:
    kind: str                 # check | mail | housekeeping | travel
    ref: str = ""
    reason: str = "schedule"
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: str = ""


def lane_of(kind: str) -> str:
    return {"check": "checks", "travel": "travel"}.get(kind, "mail")


class Scheduler:
    def __init__(self, engine: Any, store: Any, *, clock: Callable[[], float] = time.time, enabled: bool = True,
                 paused: Callable[[], bool] = lambda: False, mail_interval_min: Callable[[], float] = lambda: 10.0,
                 mail_enabled: Callable[[], bool] = lambda: True, travel_tick: Optional[Callable[[], Any]] = None):
        self.engine = engine
        self.store = store
        self.clock = clock
        self.enabled = enabled
        self.paused = paused
        self.mail_interval_min = mail_interval_min
        self.mail_enabled = mail_enabled
        self.travel_tick = travel_tick
        self.last_travel_ts: Optional[float] = None
        self._queues: dict[str, "queue.Queue[Job]"] = {lane: queue.Queue() for lane in LANES}
        self._pending: set[tuple[str, str]] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._current: dict[str, Optional[Job]] = {lane: None for lane in LANES}
        self.last_tick_ts: Optional[float] = None
        self.last_mail_ts: Optional[float] = None
        self.last_housekeeping_ts: Optional[float] = None
        self.jobs_done = 0

    def _alive(self) -> bool:
        return any(t.is_alive() for t in self._threads.values())

    def start(self) -> None:
        if self._alive():
            return
        self._stop.clear()
        for lane in LANES:
            thread = threading.Thread(target=self._loop, args=(lane,), name=f"phileas-{lane}", daemon=True)
            self._threads[lane] = thread
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for thread in self._threads.values():
            thread.join(timeout)

    def status(self) -> dict[str, Any]:
        def view(job: Optional[Job]) -> Optional[dict[str, str]]:
            return {"kind": job.kind, "ref": job.ref, "reason": job.reason} if job else None
        return {"enabled": self.enabled, "running": self._alive(), "paused": bool(self.paused()),
                "lanes": {lane: {"queue": self._queues[lane].qsize(), "current": view(self._current[lane])} for lane in LANES},
                "last_tick_ts": self.last_tick_ts, "last_mail_ts": self.last_mail_ts, "last_housekeeping_ts": self.last_housekeeping_ts,
                "last_travel_ts": self.last_travel_ts, "jobs_done": self.jobs_done}

    def submit(self, kind: str, ref: str = "", reason: str = "manual") -> Optional[Job]:
        key = (kind, ref)
        with self._lock:
            if key in self._pending:
                return None
            self._pending.add(key)
        job = Job(kind, ref, reason)
        self._queues[lane_of(kind)].put(job)
        return job

    def run_now(self, kind: str, ref: str = "", timeout: float = 240.0) -> Any:
        if not self._alive():
            return self._execute(Job(kind, ref, "inline"))
        job = self.submit(kind, ref)
        if job is None:
            return {"queued": True, "note": "already queued"}
        if not job.done.wait(timeout):
            return {"queued": True, "note": "still running; the result will appear shortly"}
        if job.error:
            raise RuntimeError(job.error)
        return job.result

    def _execute(self, job: Job) -> Any:
        if job.kind == "check":
            return self.engine.refresh(job.ref, reason=job.reason)
        if job.kind == "mail":
            self.last_mail_ts = self.clock()
            return self.engine.scan_mail()
        if job.kind == "travel":
            self.last_travel_ts = self.clock()
            return self.travel_tick() if self.travel_tick else {}
        if job.kind == "housekeeping":
            self.last_housekeeping_ts = self.clock()
            return self.engine.housekeeping()
        raise ValueError(f"unknown job kind {job.kind}")

    def _loop(self, lane: str) -> None:
        while not self._stop.is_set():
            try:
                job = self._queues[lane].get(timeout=1.0)
            except queue.Empty:
                job = None
            if job is not None:
                self._run(job, lane)
                continue
            if lane == "travel":
                now = self.clock()
                if self.travel_tick and self.enabled and not self.paused() and (self.last_travel_ts is None or now - self.last_travel_ts >= TRAVEL_EVERY_S):
                    self.last_travel_ts = now
                    self._run(Job("travel", "", "schedule"), lane)
                continue
            if lane != "checks":
                continue
            now = self.clock()
            if self.last_tick_ts is None or now - self.last_tick_ts >= TICK_S:
                self.last_tick_ts = now
                if self.enabled and not self.paused():
                    try:
                        self.enqueue_due(now)
                    except Exception:  # noqa: BLE001
                        log.exception("scheduler tick failed")

    def _run(self, job: Job, lane: str) -> None:
        self._current[lane] = job
        try:
            job.result = self._execute(job)
        except Exception as error:  # noqa: BLE001
            job.error = f"{type(error).__name__}: {error}"
            log.warning("job %s %s failed: %s", job.kind, job.ref, job.error)
        finally:
            with self._lock:
                self._pending.discard((job.kind, job.ref))
            self._current[lane] = None
            self.jobs_done += 1
            job.done.set()

    def enqueue_due(self, now: float) -> int:
        n = 0
        if self.mail_enabled() and (self.last_mail_ts is None or now - self.last_mail_ts >= max(2.0, self.mail_interval_min()) * 60):
            n += bool(self.submit("mail", "", "schedule"))
            self.last_mail_ts = now
        if self.last_housekeeping_ts is None or now - self.last_housekeeping_ts >= HOUSEKEEPING_S:
            n += bool(self.submit("housekeeping", "", "schedule"))
            self.last_housekeeping_ts = now
        for s in self.store.due(now, limit=10):
            n += bool(self.submit("check", s["id"], "schedule"))
        return n
