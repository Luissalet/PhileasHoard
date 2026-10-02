"""Deleting a trip deletes its bookings and remembers them; keep_segments detaches them instead."""

from __future__ import annotations

import pytest

import travel_mails as tm
from conftest import FakeHub, build, tool
from phileas_hoard.errors import PhileasError


@pytest.fixture
def svc2(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub(), travel_chat=lambda m, sc: {"ok": False, "error": "no_model"})
    s.set_settings({"travel.home_city": "Madrid"})
    yield s
    s.stop()


def only_trip(s):
    trips = s.travel.trips_list("all")
    assert len(trips) == 1
    return trips[0]


def test_delete_removes_the_trip_and_its_bookings_for_good(svc2):
    svc2.engine.ingest([tm.IBERIA])
    trip = only_trip(svc2)
    assert len(svc2.tstore.segments()) == 2
    with pytest.raises(PhileasError):
        tool(svc2, "trip_update", trip=trip["id"], delete=True)                           # still needs confirm
    out = tool(svc2, "trip_update", trip=trip["id"], delete=True, confirm=True)
    assert out["deleted"] == trip["id"] and out["segments_deleted"] == 2
    assert svc2.tstore.segments(include_cancelled=True) == [] and svc2.travel.trips_list("all") == []
    svc2.travel.regroup()
    assert svc2.travel.trips_list("all") == []                                            # regrouping brings nothing back


def test_reading_the_same_mail_again_does_not_resurrect_it(svc2):
    svc2.engine.ingest([tm.IBERIA])
    tool(svc2, "trip_update", trip=only_trip(svc2)["id"], delete=True, confirm=True)
    # a rescan of the same mail (the id is known, so it is skipped) ...
    assert svc2.engine.ingest([tm.IBERIA])["travel"] == 0
    # ... and a re-read by a new message id carrying the same booking
    again = tm.mail("ib-copy", 19, "no-reply@iberia.com", tm.IBERIA["subject"], tm.IBERIA["text"])
    out = svc2.engine.ingest([again])
    assert out["travel"] == 1 and svc2.tstore.segments() == [] and svc2.travel.trips_list("all") == []
    # the model-read mail or one accepted from review can still be restored on purpose, and so can a paste
    pasted = svc2.travel.paste(subject=tm.IBERIA["subject"], text=tm.IBERIA["text"], from_address="no-reply@iberia.com")
    assert pasted["created"] == 2 and len(svc2.travel.trips_list("all")) == 1


def test_other_bookings_are_not_affected(svc2):
    svc2.engine.ingest([tm.IBERIA, tm.VUELING])
    assert len(svc2.travel.trips_list("all")) == 2
    lisbon = next(t for t in svc2.travel.trips_list("all") if "Lisboa" in t["title"])
    tool(svc2, "trip_update", trip=lisbon["id"], delete=True, confirm=True)
    assert [t["title"] for t in svc2.travel.trips_list("all")] == ["Palma · 3–6 dic 2026"]
    assert svc2.engine.ingest([tm.IBERIA])["travel"] == 0


def test_a_cancellation_after_deleting_does_not_bring_it_back(svc2):
    svc2.engine.ingest([tm.VUELING])
    tool(svc2, "trip_update", trip=only_trip(svc2)["id"], delete=True, confirm=True)
    svc2.engine.ingest([tm.VUELING_CANCEL, tm.VUELING_CHANGE])
    assert svc2.tstore.segments(include_cancelled=True) == []


def test_keep_segments_detaches_them_and_regroup_leaves_them_alone(svc2):
    svc2.engine.ingest([tm.IBERIA])
    trip = only_trip(svc2)
    out = tool(svc2, "trip_update", trip=trip["id"], delete=True, keep_segments=True, confirm=True)
    assert out["segments_kept"] == 2 and out["segments_deleted"] == 0
    segs = svc2.tstore.segments()
    assert len(segs) == 2 and all(s["trip_id"] is None for s in segs)
    svc2.travel.regroup()
    assert svc2.travel.trips_list("all") == [] and all(s["trip_id"] is None for s in svc2.tstore.segments())
    assert tool(svc2, "travel_overview")["counts"]["unassigned_segments"] == 2
    assert svc2.engine.ingest([tm.IBERIA])["travel"] == 0
    # putting one back into a trip is an explicit decision and clears the mark
    sid = segs[0]["id"]
    moved = svc2.travel.move_segment(sid, "new")
    assert moved["trip"] and not (svc2.tstore.segment(sid).get("extra") or {}).get("no_trip")


def test_deleting_one_segment_is_remembered_too(svc2):
    svc2.engine.ingest([tm.IBERIA])
    back = next(s for s in svc2.tstore.segments() if s["number"] == "IB3167")
    tool(svc2, "segment_delete", segment=back["id"], confirm=True)
    svc2.engine.ingest([tm.mail("ib-copy2", 19, "no-reply@iberia.com", tm.IBERIA["subject"], tm.IBERIA["text"])])
    assert [s["number"] for s in svc2.tstore.segments()] == ["IB3166"]
    svc2.travel.add_segment(kind="flight", number="IB3167", from_code="LIS", to_code="MAD", dep_local="2026-11-15T20:30", arr_local="2026-11-15T23:15")
    assert len(svc2.tstore.segments()) == 2                                               # adding it by hand again works
