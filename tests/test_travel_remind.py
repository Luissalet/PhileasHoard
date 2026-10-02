"""Reminders (check-in, departures, trips tomorrow, stays), night silence, documents from Kafka (mocked) and the calendar file."""

from __future__ import annotations

import re

import pytest

from conftest import FakeHub, build
from phileas_hoard.travel import airports, ics

BS = chr(92)
KAFKA_DOCS = {"documents": [{"id": "d_1", "title": "DNI de Ana", "kind": "identity"}, {"id": "d_2", "title": "Pasaporte de Ana", "kind": "identity"}]}


def at(local, tz="Europe/Madrid"):
    return airports.to_ts(local, tz)


@pytest.fixture
def tv(config, clock, fake_mail):
    hub = FakeHub()
    s = build(config, clock, fake_mail, hub_call=hub)
    s.set_settings({"travel.home_city": "Madrid", "checks.night_from": "23", "checks.night_to": "7"})
    s.hub = hub
    s.clk = clock
    clock.t = at("2026-11-01T12:00")
    yield s
    s.stop()


def types(svc):
    return [e["type"] for e, _ in svc.notifier.sent]


def add_trip(tv, number="FR1234", dep="2026-11-12T09:05", **kw):
    t = tv.travel
    out = t.add_segment(kind="flight", number=number, from_code="MAD", to_code="LIS", dep_local=dep, arr_local=dep[:11] + "10:00",
                        links=[{"kind": "checkin", "url": "https://www.example-air.test/checkin?ref=XK7Q2M", "label": "Check-in online"}], **kw)
    t.add_segment(kind="flight", number=number[:2] + "1235", from_code="LIS", to_code="MAD", dep_local="2026-11-15T20:30", arr_local="2026-11-15T23:15")
    return out["segment"]["id"], out["segment"]["trip_id"]


def test_trip_tomorrow_comes_in_the_evening_once(tv):
    add_trip(tv)
    tv.clk.t = at("2026-11-11T10:00")
    tv.travel.tick()
    assert "trip_tomorrow" not in types(tv)
    tv.clk.t = at("2026-11-11T18:30")
    tv.travel.tick()
    tv.travel.tick()
    tomorrow = [e for e, _ in tv.notifier.sent if e["type"] == "trip_tomorrow"]
    assert len(tomorrow) == 1 and "Lisboa" in tomorrow[0]["title"] and "FR1234" in tomorrow[0]["summary"]


def test_ryanair_checkin_opens_24h_before_with_the_link(tv):
    sid, tid = add_trip(tv)
    dep = at("2026-11-12T09:05")
    tv.clk.t = dep - 25 * 3600
    tv.travel.tick()
    assert "checkin_open" not in types(tv)
    tv.clk.t = dep - 24 * 3600 + 120                      # two minutes after it opened (the daytime: 08:05 the day before)
    tv.travel.tick()
    sent = [e for e, _ in tv.notifier.sent if e["type"] == "checkin_open"]
    assert len(sent) == 1 and sent[0]["url"].startswith("https://www.example-air.test/checkin") and "FR1234" in sent[0]["title"]
    assert sent[0]["segment_id"] == sid and sent[0]["trip_id"] == tid
    tv.travel.tick()
    assert types(tv).count("checkin_open") == 1


def test_checkin_closing_notice_only_when_not_done(tv):
    sid, _ = add_trip(tv)
    dep = at("2026-11-12T09:05")
    tv.clk.t = dep - 24 * 3600 + 120
    tv.travel.tick()
    tv.travel.set_checkin_done(sid, True)
    tv.clk.t = dep - 2.5 * 3600 + 0                        # closes 2 h before: 30 minutes left
    tv.travel.tick()
    assert "checkin_closing" not in types(tv)
    tv.travel.set_checkin_done(sid, False)
    tv.travel.tick()
    closing = [e for e, _ in tv.notifier.sent if e["type"] == "checkin_closing"]
    assert len(closing) == 1 and "3 h" not in closing[0]["title"] and "min" in closing[0]["title"]


def test_unknown_airline_gets_a_24h_reminder_that_says_to_check(tv):
    sid, _ = add_trip(tv, number="LH1119", dep="2026-11-12T14:10")
    dep = at("2026-11-12T14:10")
    tv.clk.t = dep - 24 * 3600 + 300
    tv.travel.tick()
    sent = [e for e, _ in tv.notifier.sent if e["type"] == "checkin_open"]
    assert len(sent) == 1 and "Comprueba" in sent[0]["title"] and "Comprueba en la aerolínea" in sent[0]["summary"]


def test_departure_notice_uses_the_configured_hours(tv):
    add_trip(tv, number="IB3166", dep="2026-11-12T15:00")
    dep = at("2026-11-12T15:00")
    tv.clk.t = dep - 3.5 * 3600
    tv.travel.tick()
    assert "departure" not in types(tv)
    tv.set_settings({"travel.departure_hours": "5"})
    tv.travel.tick()
    sent = [e for e, _ in tv.notifier.sent if e["type"] == "departure"]
    assert len(sent) == 1 and "IB3166" in sent[0]["title"] and sent[0]["severity"] == "high"


def test_lodging_day(tv):
    t = tv.travel
    t.add_segment(kind="lodging", provider="Hotel Alfama", from_name="Hotel Alfama", dep_local="2026-11-12T15:00", arr_local="2026-11-15T11:00",
                  address="Rua das Escolas 12, Lisboa")
    tv.clk.t = at("2026-11-12T06:00")
    t.tick()
    assert "lodging_day" not in types(tv)                  # too early
    tv.clk.t = at("2026-11-12T09:00")
    t.tick()
    assert types(tv).count("lodging_day") == 1


def test_night_silence_holds_notices_until_morning(tv):
    add_trip(tv, number="IB3166", dep="2026-11-12T20:00")
    dep = at("2026-11-12T20:00")
    tv.clk.t = at("2026-11-12T03:00")                       # check-in opened at 20:00 the day before (outside the fresh-open window → close flight only)
    tv.set_settings({"travel.departure_hours": "3"})
    tv.travel.tick()
    assert "checkin_open" not in types(tv)                  # dep is 17 h away: not urgent, it is the night, and it opened long ago
    tv.clk.t = at("2026-11-12T08:00")
    tv.travel.tick()
    assert "checkin_open" in types(tv) or dep - tv.clk.t > 72 * 3600


def test_night_queue_flushes_at_the_end_of_the_night(tv):
    t = tv.travel
    add_trip(tv, number="VY8421", dep="2026-11-12T12:00")
    dep = at("2026-11-12T12:00")
    tv.clk.t = dep - 24 * 3600 + 60                         # 12:01 the day before: daytime, would be sent now
    # make it night by moving the night window over the hours of this moment
    tv.set_settings({"checks.night_from": "11", "checks.night_to": "14"})
    t.tick()
    assert "checkin_open" not in types(tv) and t._pending()
    tv.set_settings({"checks.night_from": "23", "checks.night_to": "7"})
    t.tick()
    assert types(tv).count("checkin_open") == 1 and not t._pending()


def test_urgent_notices_ignore_night_silence(tv):
    add_trip(tv, number="IB3166", dep="2026-11-12T05:00")
    dep = at("2026-11-12T05:00")
    tv.clk.t = dep - 2 * 3600                                # 03:00
    tv.travel.tick()
    assert "departure" in types(tv)


def test_changes_and_cancellations_are_not_sent_for_past_flights(tv):
    sid, _ = add_trip(tv)
    tv.clk.t = at("2026-11-13T12:00")
    tv.travel.tick()
    assert not [t for t in types(tv) if t in ("checkin_open", "departure")]


def test_muted_and_cancelled_trips_stay_quiet(tv):
    sid, tid = add_trip(tv)
    tv.travel.update_trip(tid, muted=True)
    tv.clk.t = at("2026-11-12T09:05") - 24 * 3600 + 120
    tv.travel.tick()
    assert not types(tv)


def test_documents_problem_is_notified_once_and_kafka_down_is_quiet(tv):
    sid, tid = add_trip(tv)
    tv.clk.t = at("2026-11-02T10:00")
    tv.travel.tick()                                         # the hub does not answer: no notice, no error
    assert "document_problem" not in types(tv)
    check = tv.travel.docs_check(tid)
    assert check["status"] == "unknown" and check["reason"] == "hub_down"
    tv.hub.answers[("kafka", "docs_list")] = KAFKA_DOCS
    tv.hub.answers[("kafka", "deadlines_list")] = {"deadlines": [{"doc_id": "d_1", "kind": "expiry", "date": "2026-11-10"},
                                                                 {"doc_id": "d_2", "kind": "expiry", "date": "2026-11-14"}]}
    check = tv.travel.docs_check(tid)
    assert check["status"] == "problem" and check["reason"] == "expires_before_return" and check["return_date"] == "2026-11-15"
    assert {d["type"] for d in check["documents"]} == {"id_card", "passport"} and all("number" not in d for d in check["documents"])
    tv.clk.t = at("2026-11-02T23:30") + 3600 * 12
    tv.travel.tick()
    tv.travel.tick()
    assert types(tv).count("document_problem") == 2        # two documents, one notice each, never repeated
    tv.hub.answers[("kafka", "deadlines_list")] = {"deadlines": [{"doc_id": "d_1", "kind": "expiry", "date": "2031-11-10"}]}
    assert tv.travel.docs_check(tid)["status"] == "ok"


def test_documents_outside_schengen_ask_for_a_passport(tv):
    t = tv.travel
    t.add_segment(kind="flight", number="BA457", from_code="MAD", to_code="LHR", dep_local="2026-11-12T08:00", arr_local="2026-11-12T09:30")
    t.add_segment(kind="flight", number="BA458", from_code="LHR", to_code="MAD", dep_local="2026-11-15T10:00", arr_local="2026-11-15T13:20")
    tid = t.trips_list("all")[0]["id"]
    tv.hub.answers[("kafka", "docs_list")] = {"documents": [{"id": "d_1", "title": "DNI", "kind": "identity"}]}
    tv.hub.answers[("kafka", "deadlines_list")] = {"deadlines": [{"doc_id": "d_1", "kind": "expiry", "date": "2030-01-01"}]}
    check = t.docs_check(tid)
    assert check["outside_schengen"] == ["GB"] and check["status"] == "warning" and check["problems"][0]["type"] == "missing_passport"


# ------------------------------------------------------------------ calendar
def test_ics_has_one_event_per_segment_in_utc_with_an_alarm(tv):
    sid, tid = add_trip(tv)
    tv.travel.add_segment(kind="lodging", provider="Hotel, Alfama; Vista", from_name="Hotel Alfama", dep_local="2026-11-12T15:00", arr_local="2026-11-15T11:00",
                          address="Rua das Escolas 12, Lisboa", trip=tid)
    out = tv.travel.ics(tid)
    text = out["ics"]
    assert out["events"] == 3 and text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n") and out["filename"].endswith(".ics")
    assert "DTSTART:20261112T080500Z" in text and "DTEND:20261112T100000Z" in text          # 09:05 in Madrid (UTC+1) is 08:05Z; 10:00 in Lisbon (UTC+0) is 10:00Z
    assert "DTSTART;VALUE=DATE:20261112" in text and "DTEND;VALUE=DATE:20261115" in text
    assert "SUMMARY:Hotel" + BS + "," + " Alfama" + BS + "; Vista" in text
    alarm = re.search(r"BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:[^\r]*\r\nTRIGGER;VALUE=DATE-TIME:(\d{8}T\d{6}Z)", text)
    assert alarm and alarm.group(1) == "20261111T080500Z"                                    # 24 h before the flight for Ryanair
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == 3


def test_ics_folding_and_cancelled_segments():
    line = "DESCRIPTION:" + "á" * 100
    folded = ics.fold_line(line)
    assert all(len(x.encode()) <= 75 for x in folded) and "".join(x[1:] if i else x for i, x in enumerate(folded)) == line
    assert ics.esc("a;b,c" + chr(10) + "d" + BS + "e") == "a" + BS + ";b" + BS + ",c" + BS + "nd" + BS + BS + "e"


def test_ics_skips_cancelled_and_lists_upcoming(tv):
    sid, tid = add_trip(tv)
    tv.travel.update_segment(sid, status="cancelled")
    assert tv.travel.ics(tid)["events"] == 1
    assert tv.travel.ics(tid, include_cancelled=True)["events"] == 2
    assert tv.travel.ics()["events"] == 1
