"""The scheduler facade over the shared lane scheduler: same queues, same status, same due logic."""

import pytest

from phileas_hoard.scheduler import Scheduler


class FakeEngine:
    def __init__(self):
        self.calls = []

    def refresh(self, sid, *, reason="schedule"):
        self.calls.append(("check", sid, reason))
        return {"id": sid}

    def scan_mail(self):
        self.calls.append(("mail",))
        return {"scanned": 1}

    def housekeeping(self):
        self.calls.append(("housekeeping",))
        return {}


class FakeStore:
    def __init__(self, due=()):
        self.ids = list(due)

    def due(self, now, limit=10):
        return [{"id": i} for i in self.ids[:limit]]


def make(due=(), **kw):
    engine = FakeEngine()
    return engine, Scheduler(engine, FakeStore(due), **kw)


def test_run_now_runs_inline_when_the_loop_is_off():
    engine, sched = make()
    assert sched.run_now("check", "s1") == {"id": "s1"}
    assert sched.run_now("mail") == {"scanned": 1}
    assert engine.calls == [("check", "s1", "manual"), ("mail",)]
    assert sched.last_mail_ts is not None and sched.jobs_done == 0


def test_unknown_kind_is_an_error():
    _engine, sched = make()
    with pytest.raises(ValueError):
        sched.run_now("nonsense")


def test_status_keeps_its_shape():
    _engine, sched = make(travel_tick=lambda: {})
    status = sched.status()
    assert set(status) == {"enabled", "running", "paused", "lanes", "last_tick_ts", "last_mail_ts", "last_housekeeping_ts",
                           "last_travel_ts", "jobs_done"}
    assert set(status["lanes"]) == {"checks", "mail", "travel"}
    assert status["lanes"]["checks"] == {"queue": 0, "current": None} and status["running"] is False


def test_submit_dedupes_and_due_checks_are_queued():
    _engine, sched = make(due=["a", "b"])
    assert sched.submit("check", "a") is not None
    assert sched.submit("check", "a") is None
    assert sched.enqueue_due(0.0) == 1  # "a" is still queued, only "b" is new
    assert sched.status()["lanes"]["checks"]["queue"] == 2


def test_periodic_jobs_follow_the_settings():
    engine, sched = make(mail_enabled=lambda: False, mail_interval_min=lambda: 1)
    registered = sched.lanes._registered
    assert set(registered) == {"tick", "mail", "housekeeping"}  # no travel job without a travel tick
    assert registered["mail"].enabled() is False and registered["mail"].every_s() == 120.0  # floor of two minutes
    _engine, with_travel = make(travel_tick=lambda: {})
    assert "travel" in with_travel.lanes._registered


def test_the_loop_runs_mail_housekeeping_and_due_checks():
    engine, sched = make(due=["s9"])
    sched.lanes.tick_s = 0.05
    sched.start()
    try:
        import time
        deadline = time.time() + 5
        while time.time() < deadline and not {("mail",), ("housekeeping",), ("check", "s9", "schedule")} <= set(engine.calls):
            time.sleep(0.05)
    finally:
        sched.stop()
    assert {("mail",), ("housekeeping",), ("check", "s9", "schedule")} <= set(engine.calls)
    assert sched.last_housekeeping_ts is not None and sched.jobs_done >= 3

