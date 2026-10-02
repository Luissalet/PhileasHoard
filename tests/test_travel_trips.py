"""Grouping segments into trips, hand edits (rename, merge, split, move) and trip statuses."""

from __future__ import annotations

import pytest

from conftest import FakeHub, build
from phileas_hoard.errors import PhileasError
from phileas_hoard.travel import airports, trips as tripslib


@pytest.fixture
def tv(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub())
    s.set_settings({"travel.home_city": "Madrid", "travel.home_airports": "MAD"})
    clock.t = airports.to_ts("2026-10-01T12:00", "Europe/Madrid")
    s.clock_obj = clock
    yield s.travel
    s.stop()


def flight(tv, number, a, b, dep, arr="", **kw):
    return tv.add_segment(kind="flight", number=number, from_code=a, to_code=b, dep_local=dep, arr_local=arr or dep, **kw)["segment"]


def stay(tv, name, inn, out, **kw):
    return tv.add_segment(kind="lodging", provider=name, from_name=name, dep_local=inn, arr_local=out, **kw)["segment"]


def titles(tv, which="all"):
    return [(t["title"], t["segments"]) for t in tv.trips_list(which)]


def test_round_trip_with_a_stay_is_one_trip(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    stay(tv, "Hotel Alfama", "2026-11-12T15:00", "2026-11-15T11:00", address="Rua das Escolas 12, Lisboa")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    assert titles(tv) == [("Lisboa · 12–15 nov 2026", 3)]
    trip = tv.trips_list("all")[0]
    assert trip["destination"] == "Lisbon" and trip["destination_label"] == "Lisboa"


def test_outbound_and_return_with_a_quiet_spell_stay_together(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-30T20:30", "2026-11-30T23:15")
    assert titles(tv) == [("Lisboa · 12–30 nov 2026", 2)]


def test_a_new_trip_starts_where_the_last_one_ended_at_home(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-14T20:30", "2026-11-14T23:15")
    flight(tv, "VY1001", "MAD", "BCN", "2026-11-15T08:00", "2026-11-15T09:15")          # the day after getting back
    flight(tv, "VY1002", "BCN", "MAD", "2026-11-17T20:00", "2026-11-17T21:15")
    assert [t for t, n in titles(tv)] == ["Lisboa · 12–14 nov 2026", "Barcelona · 15–17 nov 2026"]


def test_round_trip_is_cut_without_a_home_setting_too(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub())
    try:
        tv = s.travel
        flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
        flight(tv, "IB3167", "LIS", "MAD", "2026-11-14T20:30", "2026-11-14T23:15")
        flight(tv, "VY1001", "MAD", "BCN", "2026-11-15T08:00", "2026-11-15T09:15")
        assert len(tv.trips_list("all")) == 2
    finally:
        s.stop()


def test_far_apart_segments_are_separate_trips(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-13T20:30", "2026-11-13T23:15")
    flight(tv, "VY1001", "MAD", "BCN", "2026-12-20T08:00", "2026-12-20T09:15")
    assert len(tv.trips_list("all")) == 2


def test_gap_days_setting(tv, config):
    tv._set("travel.gap_days", "0")
    stay(tv, "Hotel Uno", "2026-12-01T15:00", "2026-12-03T11:00", address="Calle Mayor 1, Sevilla")
    stay(tv, "Hotel Dos", "2026-12-05T15:00", "2026-12-06T11:00", address="Calle Sol 2, Granada")
    assert len(tv.trips_list("all")) == 2
    tv._set("travel.gap_days", "3")
    tv.regroup()
    assert len(tv.trips_list("all")) == 1


def test_destination_is_the_city_with_most_nights(tv):
    flight(tv, "IB1", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    stay(tv, "Hotel A", "2026-11-12T15:00", "2026-11-13T11:00", address="Rua 1, Lisboa")
    stay(tv, "Hotel B", "2026-11-13T15:00", "2026-11-17T11:00", address="Rua 2, Porto")
    flight(tv, "IB2", "OPO", "MAD", "2026-11-17T20:00", "2026-11-17T22:00")
    assert tv.trips_list("all")[0]["destination"] == "Porto"


def test_title_formats_and_languages():
    assert tripslib.date_range("2026-11-12", "2026-11-12") == "12 nov 2026"
    assert tripslib.date_range("2026-11-28", "2026-12-02") == "28 nov – 2 dic 2026"
    assert tripslib.date_range("2026-12-28", "2027-01-03", "en") == "28 Dec 2026 – 3 Jan 2027"
    assert tripslib.make_title("Lisbon", "2026-11-12", "2026-11-15", "es") == "Lisboa · 12–15 nov 2026"
    assert tripslib.make_title("Lisbon", "2026-11-12", "2026-11-15", "en") == "Lisbon · 12–15 Nov 2026"


def test_rename_survives_new_segments_and_regrouping(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    trip = tv.trips_list("all")[0]
    tv.update_trip(trip["id"], title="Escapada con Marta")
    stay(tv, "Hotel Alfama", "2026-11-12T15:00", "2026-11-15T11:00", address="Rua das Escolas 12, Lisboa")
    after = tv.trips_list("all")
    assert [(t["id"], t["title"], t["segments"]) for t in after] == [(trip["id"], "Escapada con Marta", 3)]
    tv.update_trip(trip["id"], title="")                      # empty: automatic title again
    assert tv.trips_list("all")[0]["title"] == "Lisboa · 12–15 nov 2026"


def test_trip_ids_are_stable_when_segments_arrive(tv):
    a = flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    first = tv.trips_list("all")[0]["id"]
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    assert [t["id"] for t in tv.trips_list("all")] == [first]


def test_move_split_and_merge_are_remembered(tv):
    a = flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    b = flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    h = stay(tv, "Hotel Alfama", "2026-11-12T15:00", "2026-11-15T11:00", address="Rua das Escolas 12, Lisboa")
    trip = tv.trips_list("all")[0]
    out = tv.split_trip(trip["id"], [h["id"]], "Solo el hotel")
    assert out["new"]["title"] == "Solo el hotel" and out["new"]["segments"] == 1 and out["original"]["segments"] == 2
    tv.regroup()                                              # the split holds
    assert sorted(t["segments"] for t in tv.trips_list("all")) == [1, 2]
    merged = tv.merge_trips(trip["id"], out["new"]["id"])
    assert merged["trip"]["segments"] == 3 and len(tv.trips_list("all")) == 1
    moved = tv.move_segment(a["id"], "new")
    assert moved["trip"]["segments"] == 1 and len(tv.trips_list("all")) == 2
    back = tv.move_segment(a["id"], trip["id"])
    assert back["trip"]["id"] == trip["id"] and len(tv.trips_list("all")) == 1
    free = tv.move_segment(a["id"], None)                      # let the grouping decide again
    assert len(tv.trips_list("all")) == 1 and free["segment"]["locked"] is False


def test_split_needs_a_proper_subset(tv):
    a = flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05")
    trip = tv.trips_list("all")[0]
    with pytest.raises(PhileasError):
        tv.split_trip(trip["id"], [a["id"]])


def test_a_segment_next_to_a_hand_made_trip_joins_it(tv):
    trip = tv.create_trip("Boda en Oporto", "2026-12-05", "2026-12-07")["trip"]
    flight(tv, "TP1", "MAD", "OPO", "2026-12-05T08:00", "2026-12-05T08:30", trip=trip["id"])
    stay(tv, "Casa da Ribeira", "2026-12-05T15:00", "2026-12-07T11:00", address="Rua 5, Porto")
    got = tv.trips_list("all")
    assert [(t["title"], t["segments"]) for t in got] == [("Boda en Oporto", 2)]


def test_manual_empty_trip_is_kept_when_pinned_only(tv):
    tv.create_trip("Pendiente", "2027-01-10")
    assert titles(tv) == [("Pendiente", 0)]
    tv.regroup()
    assert titles(tv) == [("Pendiente", 0)]


def test_deleting_a_trip_keeps_its_segments(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    trip = tv.trips_list("all")[0]
    out = tv.delete_trip(trip["id"])
    assert out["deleted"] == trip["id"]
    assert len(tv.t.segments()) == 2 and len(tv.trips_list("all")) == 1       # regrouped into a fresh trip


def test_statuses_follow_the_clock(tv):
    flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    flight(tv, "IB3167", "LIS", "MAD", "2026-11-15T20:30", "2026-11-15T23:15")
    trip_id = tv.trips_list("all")[0]["id"]
    status = lambda: tv.trip_card(tv.t.trip(trip_id))["status"]  # noqa: E731
    assert status() == "upcoming"
    tv.clock = lambda: airports.to_ts("2026-11-13T10:00", "Europe/Madrid")
    assert status() == "ongoing"
    tv.clock = lambda: airports.to_ts("2026-11-15T23:30", "Europe/Madrid")
    assert status() == "ongoing"                                # the last day still counts
    tv.clock = lambda: airports.to_ts("2026-11-16T08:00", "Europe/Madrid")
    assert status() == "past"
    tv.update_trip(trip_id, cancelled=True)
    assert status() == "cancelled"


def test_all_segments_cancelled_cancels_the_trip(tv):
    s = flight(tv, "IB3166", "MAD", "LIS", "2026-11-12T09:05", "2026-11-12T09:55")
    tv.update_segment(s["id"], status="cancelled")
    assert tv.trips_list("all")[0]["status"] == "cancelled"


def test_a_round_trip_that_never_touches_home_stays_together(tv):
    # someone based in Madrid flying Barcelona - Palma - Barcelona with a quiet spell between the legs
    flight(tv, "VY8421", "BCN", "PMI", "2026-12-03T07:15", "2026-12-03T08:20")
    flight(tv, "VY8422", "PMI", "BCN", "2026-12-07T21:10", "2026-12-07T22:15")
    assert titles(tv) == [("Palma · 3–7 dic 2026", 2)]


def test_an_activity_has_its_own_label_and_timeline_role(tv):
    seg = tv.add_segment(kind="event", provider="Visita guiada", dep_local="2026-11-13T17:00", arr_local="2026-11-13T19:00")["segment"]
    assert seg["label"] == "Visita guiada"
    day = next(d for d in tv.trip_detail(seg["trip_id"])["timeline"] if d["date"] == "2026-11-13")
    assert [(i["role"], i["time"]) for i in day["items"]] == [("event", "17:00")]
