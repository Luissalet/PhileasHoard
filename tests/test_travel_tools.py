"""The travel tools through the tool catalogue, the agent route, the UI bridge and the calendar download."""

from __future__ import annotations

import pytest

import travel_mails as tm
from conftest import FakeHub, build, tool
from phileas_hoard.agent_tools import TOOLS_BY_NAME
from phileas_hoard.hoard_link.agentkit import AppError  # confirm_required comes from the commons' AppError
from phileas_hoard.travel import airports

TRAVEL = ["travel_overview", "trips_list", "trip_get", "trip_create", "trip_update", "segment_add", "segment_update", "segment_delete",
          "checkin_status", "checkin_done", "trip_documents_check", "trip_people", "trip_expenses", "trip_expense_add", "trip_expense_update",
          "trip_expense_delete", "trip_settle", "trip_to_ledger", "trip_ics", "trip_paste", "travel_mail_list", "travel_mail_read_again", "travel_mail_recheck"]
READ_ONLY = {"travel_overview", "trips_list", "trip_get", "checkin_status", "trip_documents_check", "trip_expenses", "trip_settle", "travel_mail_list"}


@pytest.fixture
def tv(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub())
    s.set_settings({"travel.home_city": "Madrid"})
    clock.t = airports.to_ts("2026-11-01T12:00", "Europe/Madrid")
    yield s
    s.stop()


def two_flights(tv):
    a = tool(tv, "segment_add", kind="flight", number="FR1234", from_code="MAD", to_code="LIS", dep_local="2026-11-12T09:05", arr_local="2026-11-12T10:00")
    b = tool(tv, "segment_add", kind="flight", number="FR1235", from_code="LIS", to_code="MAD", dep_local="2026-11-15T20:30", arr_local="2026-11-15T23:15")
    return a["segment"]["id"], b["segment"]["id"], a["segment"]["trip_id"]


def test_catalogue_has_every_travel_tool_with_good_descriptions():
    for name in TRAVEL:
        t = TOOLS_BY_NAME[name]
        first = t.description.splitlines()[0]
        assert len(first) <= 110, name
        assert ("readOnlyHint" in t.annotations and t.annotations["readOnlyHint"]) == (name in READ_ONLY), name
        if name not in ("trip_expense_update", "segment_delete", "trip_expense_delete", "travel_mail_read_again"):
            assert "Sinónimos:" in t.description, name


def test_trip_lifecycle_through_tools(tv):
    sid, rid, tid = two_flights(tv)
    listing = tool(tv, "trips_list", filter="upcoming")
    assert [t["id"] for t in listing["trips"]] == [tid] and "Lisboa" in listing["trips"][0]["title"]
    got = tool(tv, "trip_get", trip=tid)
    assert len(got["segments"]) == 2 and got["timeline"]
    renamed = tool(tv, "trip_update", trip=tid, title="Escapada")
    assert renamed["trip"]["title"] == "Escapada"
    # the title can also address the trip
    assert tool(tv, "trip_get", trip="Escapada")["trip"]["id"] == tid
    ov = tool(tv, "travel_overview")
    assert ov["next_trip"]["id"] == tid and ov["next_trip"]["days_to_go"] == 11


def test_split_move_merge_delete_need_confirmation(tv):
    sid, rid, tid = two_flights(tv)
    out = tool(tv, "trip_update", trip=tid, split_segments=[rid], split_title="Vuelta")
    new = out["new"]["id"]
    assert new != tid and out["original"]["id"] == tid
    assert len(tool(tv, "trips_list", filter="all")["trips"]) == 2
    with pytest.raises(AppError) as e:
        tool(tv, "trip_update", trip=tid, merge_from=new)
    assert e.value.code == "confirm_required"
    tool(tv, "trip_update", trip=tid, merge_from=new, confirm=True)
    assert len(tool(tv, "trips_list", filter="all")["trips"]) == 1
    with pytest.raises(AppError):
        tool(tv, "trip_update", trip=tid, delete=True)
    with pytest.raises(AppError):
        tool(tv, "trip_update", trip=tid)


def test_segment_edit_delete_and_checkin(tv):
    sid, rid, tid = two_flights(tv)
    upd = tool(tv, "segment_update", segment=sid, seat="14C", terminal="T4")
    assert upd["segment"]["seat"] == "14C"
    st = tool(tv, "checkin_status", trip=tid)
    assert [c["segment_id"] for c in st["flights"]] == [sid, rid] and st["flights"][0]["state"] == "not_open" and not st["flights"][0]["done"]
    done = tool(tv, "checkin_done", segment=sid)
    assert done["segment"]["id"] == sid
    assert tool(tv, "checkin_status", trip=tid)["flights"][0]["state"] == "done"
    tool(tv, "checkin_done", segment=sid, done=False)
    assert tool(tv, "checkin_status", trip=tid)["flights"][0]["state"] == "not_open"
    with pytest.raises(AppError) as e:
        tool(tv, "segment_delete", segment=rid)
    assert e.value.code == "confirm_required"
    tool(tv, "segment_delete", segment=rid, confirm=True)
    assert len(tool(tv, "trip_get", trip=tid)["segments"]) == 1


def test_expenses_through_tools(tv):
    sid, rid, tid = two_flights(tv)
    tool(tv, "trip_people", trip=tid, add=["Ana", "Luis"], me="Ana")
    tool(tv, "trip_expense_add", trip=tid, description="Cena", amount=60, payer="Ana", split_mode="equal")
    ex = tool(tv, "trip_expense_add", trip=tid, description="Taxi", amount=10, payer="Luis", split_mode="equal")
    view = tool(tv, "trip_expenses", trip=tid)
    assert len(view["expenses"]) == 2
    settle = tool(tv, "trip_settle", trip=tid)
    assert settle["people"] == ["Ana", "Luis"] and settle["total"] == 70.0
    assert [(t["from_name"], t["to_name"], t["amount"]) for t in settle["transfers"]] == [("Luis", "Ana", 25.0)]
    xid = view["expenses"][-1]["id"]
    tool(tv, "trip_expense_update", expense=xid, amount=20)
    with pytest.raises(AppError):
        tool(tv, "trip_expense_delete", expense=xid)
    tool(tv, "trip_expense_delete", expense=xid, confirm=True)
    assert len(tool(tv, "trip_expenses", trip=tid)["expenses"]) == 1
    with pytest.raises(AppError):
        tool(tv, "trip_expense_add", trip=tid, description="", amount=0)


def test_ics_tool_writes_the_file_and_the_route_serves_it(client):
    svc = client.svc
    out = client.post("/api/ui/call", json={"name": "segment_add", "arguments": {"kind": "flight", "number": "FR1234", "from_code": "MAD", "to_code": "LIS",
                                                                              "dep_local": "2099-11-12T09:05", "arr_local": "2099-11-12T10:00"}}).json()
    tid = out["segment"]["trip_id"]
    r = client.get(f"/api/trips/{tid}/ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert "BEGIN:VEVENT" in r.text and "DTSTART:20991112T080500Z" in r.text and "BEGIN:VALARM" in r.text
    allr = client.get("/api/trips/ics")
    assert allr.status_code == 200 and "BEGIN:VCALENDAR" in allr.text
    saved = client.post("/api/agent/call", json={"name": "trip_ics", "arguments": {"trip": tid}}, headers=client.bearer).json()
    assert saved["events"] == 1 and saved["saved_to"].endswith(".ics")
    assert (svc.config.data_dir / "exports" / saved["filename"]).exists()


def test_agent_route_needs_token_for_travel_tools(client):
    assert client.post("/api/agent/call", json={"name": "trips_list"}).status_code == 401
    r = client.post("/api/agent/call", json={"name": "trips_list", "arguments": {}}, headers=client.bearer)
    assert r.status_code == 200 and r.json()["trips"] == []
    names = {t["name"] for t in client.get("/api/agent/tools", headers=client.bearer).json()["tools"]}
    assert set(TRAVEL) <= names


def test_paste_and_mail_list_tools(tv):
    out = tool(tv, "trip_paste", subject=tm.VUELING["subject"], text=tm.VUELING["text"], from_address=tm.VUELING["from_address"])
    assert out["state"] == "linked" and len(out["segments"]) == 2 and out["trips"]
    listing = tool(tv, "travel_mail_list", state="all")
    assert listing["count"] == 1


def test_documents_tool_degrades_without_kafka(tv):
    sid, rid, tid = two_flights(tv)
    out = tool(tv, "trip_documents_check", trip=tid)
    assert out["status"] == "unknown" and out["reason"] == "hub_down" and out["documents"] == []


def test_dashboard_and_status_carry_travel(client):
    d = client.get("/api/dashboard").json()
    assert "travel" in d
    assert "travel" in client.get("/api/status").json()


def test_settings_validation(tv):
    with pytest.raises(AppError):
        tv.set_settings({"travel.home_tz": "Mars/Olympus"})
    with pytest.raises(AppError):
        tv.set_settings({"travel.kinds": "flight,teleport"})
    tv.set_settings({"travel.home_airports": "MAD, bcn", "travel.departure_hours": 5})
    assert tv.setting("travel.departure_hours") == "5" and tv.setting("travel.home_airports").upper() == "MAD,BCN"
