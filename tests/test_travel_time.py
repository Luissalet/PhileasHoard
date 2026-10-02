"""Time zones and DST: local times, UTC instants, overnight arrivals and the check-in windows that depend on them."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from phileas_hoard.travel import airports, checkin, rules, segments as seglib
from phileas_hoard.travel.draft import SegmentDraft


def utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def test_summer_and_winter_offsets_in_madrid_and_london():
    assert utc(airports.to_ts("2026-07-01T12:00", "Europe/Madrid")) == "2026-07-01T10:00"       # CEST, UTC+2
    assert utc(airports.to_ts("2026-12-01T12:00", "Europe/Madrid")) == "2026-12-01T11:00"       # CET, UTC+1
    assert utc(airports.to_ts("2026-07-01T12:00", "Europe/London")) == "2026-07-01T11:00"
    assert utc(airports.to_ts("2026-12-01T12:00", "Atlantic/Canary")) == "2026-12-01T12:00"


def test_the_week_europe_changes_clocks():
    # spring forward on 2026-03-29 at 02:00 → 03:00; autumn back on 2026-10-25 at 03:00 → 02:00
    assert utc(airports.to_ts("2026-03-28T23:00", "Europe/Madrid")) == "2026-03-28T22:00"
    assert utc(airports.to_ts("2026-03-29T08:00", "Europe/Madrid")) == "2026-03-29T06:00"
    assert utc(airports.to_ts("2026-10-24T23:00", "Europe/Madrid")) == "2026-10-24T21:00"
    assert utc(airports.to_ts("2026-10-25T08:00", "Europe/Madrid")) == "2026-10-25T07:00"
    # the UK and the EU change on the same Sundays, the US earlier: the offset between New York and Madrid shrinks for three weeks
    gap = lambda day: (airports.to_ts(f"{day}T12:00", "Europe/Madrid") - airports.to_ts(f"{day}T12:00", "America/New_York")) / 3600  # noqa: E731
    assert gap("2026-03-01") == -6 and gap("2026-03-15") == -5 and gap("2026-04-15") == -6


def test_offsets_from_a_mail_become_the_airports_wall_clock():
    d = SegmentDraft(kind="flight", from_code="MAD", to_code="JFK", dep_local="2026-07-01T10:00", dep_offset=120, arr_local="2026-07-01T12:30",
                     arr_offset=-240).enrich()
    assert (d.dep_local, d.dep_tz, d.arr_local, d.arr_tz) == ("2026-07-01T10:00", "Europe/Madrid", "2026-07-01T12:30", "America/New_York")
    # a mail that gives the time in UTC+1 for a summer flight from Madrid: the airport's clock is one hour later
    d = SegmentDraft(kind="flight", from_code="MAD", to_code="LIS", dep_local="2026-07-01T09:00", dep_offset=60, arr_local="2026-07-01T10:00", arr_offset=60).enrich()
    assert d.dep_local == "2026-07-01T10:00" and d.arr_local == "2026-07-01T10:00" and d.arr_tz == "Europe/Lisbon"


def test_real_flight_duration_across_zones():
    seg = seglib.derive({"dep_local": "2026-07-01T10:00", "dep_tz": "Europe/Madrid", "arr_local": "2026-07-01T12:30", "arr_tz": "America/New_York"})
    assert (seg["arr_ts"] - seg["dep_ts"]) / 3600 == 8.5                    # 10:00 CEST → 12:30 EDT
    seg = seglib.derive({"dep_local": "2026-12-01T10:00", "dep_tz": "Europe/Madrid", "arr_local": "2026-12-01T10:55", "arr_tz": "Europe/Lisbon"})
    assert (seg["arr_ts"] - seg["dep_ts"]) / 60 == 115                      # Lisbon is one hour behind


def test_overnight_arrival_without_a_date_means_the_next_day():
    mail = {"subject": "Billete Alsa", "from_address": "no-reply@alsa.es", "text": "Localizador: AL8X2K\nOrigen: Madrid Estación Sur\nDestino: Oviedo\n"
            "Fecha de salida: 24/11/2026\nHora de salida: 23:00\nHora de llegada: 05:45\n"}
    from datetime import date
    d = rules.read(mail, date(2026, 10, 1)).drafts[0]
    assert (d.dep_local, d.arr_local) == ("2026-11-24T23:00", "2026-11-25T05:45")


def test_overnight_across_the_autumn_change():
    mail = {"subject": "Billete Alsa", "from_address": "no-reply@alsa.es", "text": "Localizador: AL8X2K\nOrigen: Madrid Estación Sur\nDestino: Oviedo\n"
            "Fecha de salida: 24/10/2026\nHora de salida: 23:00\nHora de llegada: 05:45\n"}
    from datetime import date
    d = rules.read(mail, date(2026, 10, 1)).drafts[0]
    seg = seglib.derive(d.to_dict())
    assert d.arr_local == "2026-10-25T05:45" and (seg["arr_ts"] - seg["dep_ts"]) / 3600 == 7.75    # an extra hour: the night lasts 25 hours


def test_nonexistent_and_repeated_local_times_do_not_crash():
    assert airports.to_ts("2026-03-29T02:30", "Europe/Madrid") is not None        # does not exist: pushed forward
    assert airports.to_ts("2026-10-25T02:30", "Europe/Madrid") is not None        # happens twice: first occurrence
    assert airports.to_ts("2026-11-12", "Europe/Madrid") is not None              # a date alone is midnight
    assert airports.to_ts("garbage", "Europe/Madrid") is None


def test_checkin_opening_is_24_real_hours_across_a_clock_change():
    seg = {"kind": "flight", "number": "FR1234", "carrier_code": "FR", "dep_local": "2026-03-29T08:00", "dep_tz": "Europe/Madrid"}
    seg["dep_ts"] = airports.to_ts(seg["dep_local"], seg["dep_tz"])
    w = checkin.window(seg)
    assert utc(w["opens_ts"]) == utc(seg["dep_ts"] - 24 * 3600) == "2026-03-28T06:00"       # 07:00 in Madrid the day before (CET)
    assert utc(w["closes_ts"]) == "2026-03-29T04:00"


def seg_of(code, number, dep_local, tz="Europe/Madrid", **extra):
    seg = {"kind": "flight", "number": number, "carrier_code": code, "dep_local": dep_local, "dep_tz": tz, "status": "confirmed", **extra}
    seg["dep_ts"] = airports.to_ts(dep_local, tz)
    return seg


@pytest.mark.parametrize("code,opens_h,closes_min", [("FR", 24, 120), ("U2", 720, 120), ("IB", 24, 60), ("UX", 48, 60)])
def test_table_windows(code, opens_h, closes_min):
    seg = seg_of(code, f"{code}1234", "2026-12-10T12:00", to_country="GB")
    w = checkin.window(seg)
    assert w["known"] and w["opens_ts"] == seg["dep_ts"] - opens_h * 3600 and w["closes_ts"] == seg["dep_ts"] - closes_min * 60
    assert w["source"] and w["checked"] == "2026-10-02"


def test_vueling_closing_depends_on_schengen():
    inside = checkin.window(seg_of("VY", "VY8421", "2026-12-10T12:00", from_country="ES", to_country="PT"))
    assert inside["opens_h"] == 24 and inside["closes_ts"] == inside["opens_ts"] + (24 * 3600 - 50 * 60)
    outside = checkin.window(seg_of("VY", "VY6001", "2026-12-10T12:00", from_country="ES", to_country="GB"))
    assert outside["closes_ts"] is None and outside["known"]


def test_air_europa_to_the_us_opens_24h_before():
    us = checkin.window(seg_of("UX", "UX91", "2026-12-10T12:00", to_country="US"))
    eu = checkin.window(seg_of("UX", "UX1013", "2026-12-10T12:00", to_country="ES"))
    assert us["opens_h"] == 24 and eu["opens_h"] == 48


def test_other_airlines_are_unknown_with_a_24h_reminder():
    seg = seg_of("LH", "LH1119", "2026-12-10T12:00")
    w = checkin.window(seg)
    assert not w["known"] and w["opens_ts"] == seg["dep_ts"] - 24 * 3600 and w["closes_ts"] is None
    assert "Comprueba en la aerolínea" in w["note_es"] and "Check with the airline" in w["note_en"]


def test_checkin_states():
    seg = seg_of("FR", "FR1234", "2026-12-10T12:00")
    dep = seg["dep_ts"]
    assert checkin.state(seg, dep - 30 * 3600)["state"] == "not_open"
    assert checkin.state(seg, dep - 10 * 3600)["state"] == "open"
    assert checkin.state(seg, dep - 1.5 * 3600)["state"] == "closed"
    assert checkin.state({**seg, "checkin_done": True}, dep - 10 * 3600)["state"] == "done"
    assert checkin.state(seg_of("LH", "LH1", "2026-12-10T12:00"), dep - 10 * 3600)["state"] == "unknown_open"
    assert checkin.window({"kind": "train"}) == {"applies": False}


def test_the_table_lists_what_the_airlines_publish():
    rows = {r["code"]: r for r in checkin.table()}
    assert set(rows) == {"FR", "U2", "VY", "IB", "UX"} and all(r["checked"] == "2026-10-02" and r["source"] for r in rows.values())
