"""Delivery days and the explained estimate."""

from __future__ import annotations

from datetime import date, datetime

from phileas_hoard import eta
from phileas_hoard.bizdays import Calendar, easter, holidays


def ts(d: date, hour: int = 12) -> float:
    return datetime(d.year, d.month, d.day, hour).timestamp()


def test_calendar():
    assert easter(2026) == date(2026, 4, 5)
    assert date(2026, 4, 3) in holidays(2026) and date(2026, 4, 2) in holidays(2026, "ES-MD") and date(2026, 5, 2) in holidays(2026, "ES-MD")
    cal = Calendar("ES-MD")
    assert cal.add(date(2026, 10, 9), 1, "ups") == date(2026, 10, 13)       # Friday + 1 skips the weekend and 12 Oct
    assert cal.add(date(2026, 10, 9), 1, "amazon") == date(2026, 10, 10)    # Amazon delivers on Saturday
    assert cal.count(date(2026, 10, 1), date(2026, 10, 6), "ups") == 3


def test_delivered_is_final():
    s = {"id": "s", "status": "delivered", "delivered_ts": ts(date(2026, 9, 3))}
    e = eta.estimate(s, [], Calendar(), date(2026, 10, 1))
    assert e.eta_likely == "2026-09-03" and e.confidence == 100


def test_carrier_date_corrected_by_track_record():
    cal = Calendar("ES-MD")
    history = [{"id": f"h{i}", "carrier": "ups", "status": "delivered", "carrier_eta_first": p.isoformat(), "delivered_ts": ts(r),
                "shipped_ts": ts(date(2026, 9, 1))}
               for i, (p, r) in enumerate([(date(2026, 9, 2), date(2026, 9, 3)), (date(2026, 9, 9), date(2026, 9, 10)),
                                           (date(2026, 9, 16), date(2026, 9, 17))])]
    s = {"id": "s", "status": "in_transit", "carrier": "ups", "carrier_eta_from": "2026-10-05", "carrier_eta_to": "2026-10-05",
         "shipped_ts": ts(date(2026, 10, 1))}
    e = eta.estimate(s, history, cal, date(2026, 10, 2))
    assert e.eta_from == "2026-10-06"                       # one day later than UPS says, as usual
    assert "más tarde" in e.basis[0].text


def test_late_parcel_moves_forward():
    s = {"id": "s", "status": "in_transit", "carrier": "ups", "carrier_eta_from": "2026-09-28", "carrier_eta_to": "2026-09-28",
         "shipped_ts": ts(date(2026, 9, 24))}
    e = eta.estimate(s, [], Calendar("ES-MD"), date(2026, 10, 1))
    assert e.late and e.eta_from >= "2026-10-01" and e.basis[0].source == "late"


def test_pickup_waiting_with_deadline():
    s = {"id": "s", "status": "available_for_pickup", "status_ts": ts(date(2026, 10, 1)), "pickup_deadline": "2026-10-16"}
    e = eta.estimate(s, [], Calendar(), date(2026, 10, 1))
    assert e.days_left == 0 and "16 oct" in e.basis[0].text


def test_typical_when_nothing_else():
    s = {"id": "s", "status": "in_transit", "carrier": "correos", "shipped_ts": ts(date(2026, 10, 1))}
    e = eta.estimate(s, [], Calendar("ES-MD"), date(2026, 10, 1))
    assert e.eta_from and e.basis[0].source == "typical" and e.confidence <= 30


def test_promise_and_agreement_raise_confidence():
    s = {"id": "s", "status": "in_transit", "carrier": "ups", "shipped_ts": ts(date(2026, 10, 1)), "origin_country": "NL",
         "promise_min_days": 2, "promise_max_days": 6, "promise_business": True, "promise_base_ts": ts(date(2026, 10, 1)),
         "merchant_eta_from": "2026-10-05", "merchant_eta_to": "2026-10-05"}
    e = eta.estimate(s, [], Calendar("ES-MD"), date(2026, 10, 1))
    used = [b.source for b in e.basis if b.used]
    assert "shop" in used and "promise" in used and e.confidence > 68
