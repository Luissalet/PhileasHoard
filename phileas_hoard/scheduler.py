"""Background work in three lanes, one job at a time each.

* ``checks``: carrier checks of due shipments (the browser can only serve one page at a time anyway).
* ``mail``: the mail scan (every ``mail.interval_min``, default 10) and housekeeping (hourly).
* ``travel``: the travel reminders (check-in, departures, trips tomorrow), every minute, on their own lane so a long mail scan never delays them.

The lanes, the periodic jobs, the de-duplication, ``run_now`` and the worker threads are the commons' ``hoard_link.lanes.LaneScheduler``;
what stays here is what is Phileas's own: which shipments are due (read from the store on every tick) and how a job kind runs in the
engine. A job that raises is logged and never stops its lane. "Check now" and "Scan now" go through the same queues.
"""

from __future__ import annotations

import logging
import time
from functools import partial
from typing import Any, Callable, Optional

from .hoard_link.lanes import Job as _LaneJob, LaneScheduler

log = logging.getLogger("phileas.scheduler")

TICK_S = 20.0
HOUSEKEEPING_S = 3600.0
TRAVEL_EVERY_S = 60.0
LANES = ("checks", "mail", "travel")


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
        self.lanes = LaneScheduler({lane: 1 for lane in LANES}, enabled=enabled, paused=paused, clock=clock, tick_s=10.0, name="phileas")
        reg = self.lanes.register
        # the tick: one registered job that asks the store which shipments are due (the due logic is Phileas's own)
        reg(_LaneJob("tick", key="tick", fn=lambda: self.enqueue_due(self.clock()), lane="checks", every_s=TICK_S))
        reg(_LaneJob("mail", key="mail:", fn=partial(self._execute, "mail", ""), lane="mail",
                     every_s=lambda: max(2.0, float(self.mail_interval_min())) * 60, enabled=self.mail_enabled))
        reg(_LaneJob("housekeeping", key="housekeeping:", fn=partial(self._execute, "housekeeping", ""), lane="mail", every_s=HOUSEKEEPING_S))
        if travel_tick is not None:
            reg(_LaneJob("travel", key="travel:", fn=partial(self._execute, "travel", ""), lane="travel", every_s=TRAVEL_EVERY_S))

    # ------------------------------------------------------------------ times of the last runs
    @property
    def last_tick_ts(self) -> Optional[float]:
        return self.lanes.last_tick_ts

    @property
    def last_mail_ts(self) -> Optional[float]:
        return self.lanes.last.get("mail")

    @property
    def last_housekeeping_ts(self) -> Optional[float]:
        return self.lanes.last.get("housekeeping")

    @property
    def last_travel_ts(self) -> Optional[float]:
        return self.lanes.last.get("travel")

    @property
    def jobs_done(self) -> int:
        return self.lanes.jobs_done - int(self.lanes._stats.get("tick", {}).get("runs", 0))

    # ------------------------------------------------------------------ lifecycle
    def _alive(self) -> bool:
        return self.lanes._alive()

    def start(self) -> None:
        self.lanes.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.lanes.stop(timeout)

    def status(self) -> dict[str, Any]:
        raw = self.lanes.status()

        def view(job: dict[str, str]) -> dict[str, str]:
            return {"kind": job["kind"], "ref": job["key"][len(job["kind"]) + 1:], "reason": job["reason"]}

        def current(lane: str) -> Optional[dict[str, str]]:
            running = [j for j in raw["lanes"][lane]["current"] if j["kind"] != "tick"]
            return view(running[0]) if running else None

        return {"enabled": self.enabled, "running": raw["running"], "paused": bool(self.paused()),
                "lanes": {lane: {"queue": raw["lanes"][lane]["queue"], "current": current(lane)} for lane in LANES},
                "last_tick_ts": self.last_tick_ts, "last_mail_ts": self.last_mail_ts, "last_housekeeping_ts": self.last_housekeeping_ts,
                "last_travel_ts": self.last_travel_ts, "jobs_done": self.jobs_done}

    # ------------------------------------------------------------------ queue
    def _job(self, kind: str, ref: str, reason: str) -> _LaneJob:
        return _LaneJob(kind, key=f"{kind}:{ref}", fn=partial(self._execute, kind, ref, reason), lane=lane_of(kind), reason=reason)

    def submit(self, kind: str, ref: str = "", reason: str = "manual") -> Optional[_LaneJob]:
        return self.lanes.submit(self._job(kind, ref, reason))

    def run_now(self, kind: str, ref: str = "", timeout: float = 240.0) -> Any:
        """Queue a job and wait for it (used by 'check now' and 'scan now'). Without a running loop, run inline."""
        return self.lanes.run_now(self._job(kind, ref, "manual"), timeout)

    def _execute(self, kind: str, ref: str, reason: str = "schedule") -> Any:
        if kind == "check":
            return self.engine.refresh(ref, reason=reason)
        if kind == "mail":
            return self.engine.scan_mail()
        if kind == "travel":
            return self.travel_tick() if self.travel_tick else {}
        if kind == "housekeeping":
            return self.engine.housekeeping()
        raise ValueError(f"unknown job kind {kind}")

    def enqueue_due(self, now: float) -> int:
        """Queue the carrier check of every shipment that is due (mail, housekeeping and travel are the lanes' periodic jobs)."""
        n = 0
        for s in self.store.due(now, limit=10):
            n += bool(self.submit("check", s["id"], "schedule"))
        return n
