"""Edits merge only the fields they carry: what another writer (the assistant, a second tab) changed meanwhile survives."""

from __future__ import annotations

import mails as M
import pytest

from conftest import FakeHub, build, tool
from phileas_hoard.travel import airports


@pytest.fixture
def tv(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub())
    clock.t = airports.to_ts("2026-11-01T12:00", "Europe/Madrid")
    yield s
    s.stop()


def test_shipment_update_touches_only_the_given_fields(svc):
    sid = tool(svc, "shipment_add", tracking_number=M.S10, label="Libro", merchant="Tienda", check_now=False)["shipment"]["id"]
    # the assistant renames the parcel, then a form that only changed the notes saves
    tool(svc, "shipment_update", shipment=sid, label="Libro de cocina")
    tool(svc, "shipment_update", shipment=sid, notes="Dejar en porteria")
    got = tool(svc, "shipment_get", shipment=sid)["shipment"]
    assert got["label"] == "Libro de cocina"
    assert got["notes"] == "Dejar en porteria"
    assert got["merchant"] == "Tienda"
    # an explicit empty string clears one field and still leaves the rest alone
    tool(svc, "shipment_update", shipment=sid, notes="")
    got = tool(svc, "shipment_get", shipment=sid)["shipment"]
    assert got["notes"] == "" and got["label"] == "Libro de cocina"


def test_trip_update_touches_only_the_given_fields(tv):
    a = tool(tv, "segment_add", kind="flight", number="FR1234", from_code="MAD", to_code="LIS", dep_local="2026-11-12T09:05", arr_local="2026-11-12T10:00")
    tid = a["segment"]["trip_id"]
    tool(tv, "trip_update", trip=tid, title="Escapada")
    tool(tv, "trip_update", trip=tid, notes="Llevar pasaporte")
    trip = tool(tv, "trip_get", trip=tid)["trip"]
    assert trip["title"] == "Escapada" and trip["notes"] == "Llevar pasaporte"


def test_segment_update_touches_only_the_given_fields(tv):
    a = tool(tv, "segment_add", kind="flight", number="FR1234", from_code="MAD", to_code="LIS", dep_local="2026-11-12T09:05", arr_local="2026-11-12T10:00")
    sid, tid = a["segment"]["id"], a["segment"]["trip_id"]
    tool(tv, "segment_update", segment=sid, seat="12A")
    tool(tv, "segment_update", segment=sid, terminal="T4")
    seg = next(s for s in tool(tv, "trip_get", trip=tid)["segments"] if s["id"] == sid)
    assert seg["seat"] == "12A" and seg["terminal"] == "T4" and seg["number"] == "FR1234"


def test_expense_update_touches_only_the_given_fields(tv):
    tid = tool(tv, "trip_create", title="Lisboa", start_date="2026-11-12", end_date="2026-11-15")["trip"]["id"]
    tool(tv, "trip_people", trip=tid)
    eid = tool(tv, "trip_expense_add", trip=tid, description="Taxi", amount=20, category="transport")["expense"]["id"]
    tool(tv, "trip_expense_update", expense=eid, category="food")      # the assistant
    tool(tv, "trip_expense_update", expense=eid, description="Taxi aeropuerto")   # the form: only the description changed
    row = next(e for e in tool(tv, "trip_expenses", trip=tid)["expenses"] if e["id"] == eid)
    assert row["description"] == "Taxi aeropuerto" and row["category"] == "food" and row["amount"] == 20
