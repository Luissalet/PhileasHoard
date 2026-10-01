"""Notifications are deduplicated; checks are paced by status and paused at night."""

from __future__ import annotations

from datetime import datetime

import mails as M


def test_notifications_are_not_repeated(svc):
    svc.engine.ingest([M.WALLAPOP])
    n = len(svc.notifier.sent)
    s = svc.store.by_number(M.CORREOS_CODE)
    svc.engine.apply_status(s["id"], "available_for_pickup", M.T0, source="correos")
    svc.engine.housekeeping()
    assert len([e for e, _ in svc.notifier.sent if e["type"] == "pickup_ready"]) == 1
    assert len(svc.notifier.sent) >= n


def test_pickup_deadline_reminder(svc, clock):
    svc.engine.ingest([M.WALLAPOP])
    clock.advance(14 * M.D)
    svc.engine.housekeeping()
    assert "pickup_deadline" in svc.notifier.types()


def test_next_check_by_status_and_night(svc, clock):
    svc.engine.ingest([M.PCS_SHIPPED])
    s = svc.store.by_number(M.UPS)
    due = svc.engine.next_check(s)
    assert due - clock() >= 3600                                         # in transit: every two hours
    clock.t = datetime(2026, 10, 1, 22, 30).timestamp()
    due = svc.engine.next_check(svc.store.shipment(s["id"]))
    assert datetime.fromtimestamp(due).hour == 7                       # never at night


def test_stale_parcel_is_flagged(svc, clock):
    svc.engine.ingest([M.PCS_SHIPPED])
    clock.advance(8 * M.D)
    svc.engine.housekeeping()
    assert "stale" in svc.notifier.types()


def test_muted_parcels_stay_quiet(svc):
    svc.engine.ingest([M.PCS_SHIPPED])
    s = svc.store.by_number(M.UPS)
    svc.store.update_shipment(s["id"], muted=True)
    before = len(svc.notifier.sent)
    svc.engine.apply_status(s["id"], "out_for_delivery", M.T0 + 60, source="ups_web")
    assert len(svc.notifier.sent) == before
