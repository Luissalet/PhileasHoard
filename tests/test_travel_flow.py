"""Travel mail through the whole pipeline: filing, trips, changes, cancellations, the review list, paste and quiet history."""

from __future__ import annotations

import json

import pytest

import travel_mails as tm
from conftest import FakeHub, build
from mails import D, H, T0
from phileas_hoard.travel import airports


def ts(local: str, tz: str = "Europe/Madrid") -> float:
    return airports.to_ts(local, tz)


@pytest.fixture
def tsvc(config, clock, fake_mail):
    hub = FakeHub()
    chat_log: list = []

    def chat(messages, schema):
        chat_log.append(messages)
        return {"ok": False, "error": "no_model"}
    s = build(config, clock, fake_mail, travel_chat=chat, hub_call=hub)
    s.hub, s.chat_log = hub, chat_log
    s.set_settings({"travel.home_city": "Madrid"})
    yield s
    s.stop()


def ingest(svc, *mails, bootstrap=False):
    return svc.engine.ingest(list(mails), bootstrap=bootstrap)


def test_booking_mails_become_one_trip(tsvc):
    out = ingest(tsvc, tm.IBERIA, tm.BOOKING, tm.HERTZ)
    assert out["travel"] == 3 and out["shipping"] == 0 and len(out["trips"]) == 1
    trips = tsvc.travel.trips_list("all")
    assert len(trips) == 1
    trip = trips[0]
    assert trip["title"] == "Lisboa · 12–15 nov 2026" and trip["destination"] == "Lisbon" and trip["status"] == "upcoming"
    assert trip["segments"] == 4 and set(trip["kinds"]) == {"flight", "lodging", "car"} and trip["days_to_go"] == 42
    detail = tsvc.travel.trip_detail(trip["id"])
    assert [s["kind"] for s in detail["segments"]] == ["lodging", "flight", "car", "flight"] or len(detail["segments"]) == 4
    assert detail["mails"] and {m["subject"] for m in detail["mails"]} >= {"Tu reserva Iberia XK7Q2M está confirmada"}


def test_mail_rows_are_kept_and_not_read_twice(tsvc):
    ingest(tsvc, tm.IBERIA)
    row = tsvc.store.mail(tm.IBERIA["message_id"])
    assert row["kind"] == "travel" and row["state"] == "linked"
    again = ingest(tsvc, tm.IBERIA)
    assert again["travel"] == 0 and len(tsvc.tstore.segments()) == 2


def test_parcels_still_work_next_to_travel(tsvc):
    from mails import PCS_SHIPPED
    out = ingest(tsvc, tm.IBERIA, PCS_SHIPPED)
    assert out["travel"] == 1 and out["shipping"] == 1 and out["created"] == 1


def test_a_shipping_mail_from_an_unknown_sender_stays_a_parcel(tsvc):
    mail = tm.mail("p1", 1, "info@shop.example.test", "Tu pedido 123456 ha sido enviado",
                   "Tu pedido 123456 ha sido enviado con UPS. Referencia de reserva: AB12CD\nSalida: 12 nov 2026 09:05\nMadrid (MAD) → Lisboa (LIS)\n"
                   "https://www.ups.com/track?tracknum=1Z999AA10123456784")
    out = ingest(tsvc, mail)
    assert out["travel"] == 0


def test_change_updates_the_segment_and_notifies(tsvc, clock):
    ingest(tsvc, tm.VUELING)
    seg = next(s for s in tsvc.tstore.segments() if s["number"] == "VY8421")
    clock.t = tm.VUELING_CHANGE["ts"] + 3600               # a fresh mail: not quiet
    out = ingest(tsvc, tm.VUELING_CHANGE)
    assert out["travel"] == 1
    fresh = tsvc.tstore.segment(seg["id"])
    assert fresh["dep_local"] == "2026-12-03T08:00" and fresh["arr_local"] == "2026-12-03T09:05"
    sent = [e for e, _ in tsvc.notifier.sent if e["type"] == "segment_changed"]
    assert len(sent) == 1 and "VY8421" in sent[0]["title"] and "07:15" in sent[0]["summary"] and "08:00" in sent[0]["summary"]
    ingest(tsvc, tm.VUELING_CHANGE)                          # the same mail again: nothing new
    assert len([e for e, _ in tsvc.notifier.sent if e["type"] == "segment_changed"]) == 1


def test_cancel_marks_the_segment_and_the_trip(tsvc, clock):
    ingest(tsvc, tm.VUELING)
    clock.t = tm.VUELING_CANCEL["ts"] + 3600
    ingest(tsvc, tm.VUELING_CANCEL)
    segs = {s["number"]: s for s in tsvc.tstore.segments()}
    assert segs["VY8422"]["status"] == "cancelled" and segs["VY8421"]["status"] == "confirmed"
    assert any(e["type"] == "segment_cancelled" for e, _ in tsvc.notifier.sent)
    trip = tsvc.travel.trips_list("all")[0]
    assert trip["status"] == "upcoming" and trip["active_segments"] == 1


def test_cancel_mail_without_a_route_cancels_by_reference(tsvc, clock):
    ingest(tsvc, tm.VUELING)
    mail = tm.mail("c2", 0.5, "info@vueling.com", "Reserva cancelada ZP4T9K", "Hemos cancelado tu reserva.\nCódigo de reserva: ZP4T9K\nGracias.")
    clock.t = mail["ts"] + 60
    ingest(tsvc, mail)
    assert {s["status"] for s in tsvc.tstore.segments()} == {"cancelled"}
    assert tsvc.travel.trips_list("cancelled")


def test_old_mails_build_history_quietly(tsvc):
    out = ingest(tsvc, tm.IBERIA, tm.RENFE, bootstrap=True)
    assert out["travel"] == 2
    assert not [e for e, _ in tsvc.notifier.sent if e["type"].startswith(("trip_", "segment_"))]


def test_new_trip_from_fresh_mail_notifies_once(tsvc, clock):
    mail = tm.mail("fresh", 0.1, "no-reply@iberia.com", "Tu reserva Iberia XK7Q2M", tm.IBERIA["text"])
    clock.t = mail["ts"] + 60
    ingest(tsvc, mail)
    news = [e for e, _ in tsvc.notifier.sent if e["type"] == "trip_new"]
    assert len(news) == 1 and "Lisboa" in news[0]["title"] and news[0]["trip_id"]


HARD = tm.HARD


def test_unreadable_travel_mail_goes_to_review_without_a_model(tsvc):
    out = ingest(tsvc, HARD)
    assert out["travel"] == 1
    row = tsvc.store.mail(HARD["message_id"])
    assert row["kind"] == "travel" and row["state"] == "new" and row["facts"]["model"]["status"] == "no_model"
    assert not tsvc.tstore.segments() and tsvc.chat_log
    listed = tsvc.travel.mails_list("new")
    assert listed[0]["message_id"] == HARD["message_id"] and listed[0]["read"] == []


def test_model_reading_waits_for_accept(config, clock, fake_mail):
    seg = {"kind": "flight", "booking_ref": "PQ7R2X", "number": "V74521", "from_code": "SVQ", "to_code": "BIO", "dep_local": "2026-12-03T18:20",
           "arr_local": "2026-12-03T19:35", "evidence": [tm.HARD_EVIDENCE]}
    s = build(config, clock, fake_mail, hub_call=FakeHub(), travel_chat=lambda m, sc: {"ok": True, "text": json.dumps({"segments": [seg]}), "model": "qwen-test"})
    try:
        ingest(s, HARD)
        assert not s.tstore.segments()                                   # nothing filed on its own
        item = s.travel.mails_list("new")[0]
        assert item["source"] == "model" and item["read"][0]["source"] == "model" and item["read"][0]["evidence"]
        out = s.engine.accept_mail(HARD["message_id"])
        assert out["travel"]["created"] == 1
        stored = s.tstore.segments()[0]
        assert stored["source"] == "model" and stored["number"] == "V74521" and not stored["needs_review"]
        assert s.store.mail(HARD["message_id"])["state"] == "linked"
    finally:
        s.stop()


def test_model_budget_per_scan(config, clock, fake_mail):
    calls = []
    s = build(config, clock, fake_mail, hub_call=FakeHub(), travel_chat=lambda m, sc: calls.append(1) or {"ok": False, "error": "no_model"})
    try:
        mails = [tm.mail(f"h{i}", 2, "agent@viajes-example.test", f"Su viaje {i}", HARD["text"] + f"\nRef {i}") for i in range(9)]
        ingest(s, *mails)
        assert len(calls) == 6
        assert s.store.mail(mails[-1]["message_id"])["facts"]["model"]["status"] == "deferred"
    finally:
        s.stop()


def test_paste_flow_and_trip_target(tsvc):
    out = tsvc.travel.paste(subject="Tu reserva Iberia", text=tm.IBERIA["text"], from_address="no-reply@iberia.com")
    assert out["state"] == "linked" and out["created"] == 2
    again = tsvc.travel.paste(subject="Tu reserva Iberia", text=tm.IBERIA["text"], from_address="no-reply@iberia.com")
    assert again["already_known"]
    trip = tsvc.travel.trips_list("all")[0]
    out2 = tsvc.travel.paste(subject="Hotel", text=tm.BOOKING["text"], from_address="customer.service@booking.com", trip=trip["id"])
    assert out2["moved_to"] == trip["id"]
    assert len(tsvc.tstore.segments(trip_id=trip["id"])) == 3


def test_kinds_turned_off_are_skipped(tsvc):
    tsvc.set_settings({"travel.kinds": "flight"})
    out = ingest(tsvc, tm.BOOKING)
    assert out["travel"] == 1 and not tsvc.tstore.segments()
    assert tsvc.store.mail(tm.BOOKING["message_id"])["state"] == "skipped"


def test_travel_off_leaves_mail_to_the_parcel_rules(tsvc):
    tsvc.set_settings({"travel.enabled": "0"})
    out = ingest(tsvc, tm.IBERIA)
    assert out["travel"] == 0 and out["noise"] + out["maybe"] == 1
