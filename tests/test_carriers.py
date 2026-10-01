"""Carrier adapters on recorded answers, and the source order per carrier."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

import mails as M
from conftest import NoBrowser, make_config
from phileas_hoard.carriers import Carriers, correos, dhl, track17, ups

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_correos_phases_and_pickup():
    r = correos.parse(load("correos_delivered.json"))
    assert r.ok and r.found and r.status == "delivered"
    statuses = [e.status for e in sorted(r.events, key=lambda e: e.ts)]
    assert statuses == ["label_created", "in_transit", "in_transit", "in_transit", "available_for_pickup", "delivered"]
    assert r.delivered_ts == max(e.ts for e in r.events)


def test_correos_unknown_code_is_not_found():
    transport = httpx.MockTransport(lambda req: httpx.Response(204))
    with httpx.Client(transport=transport) as client:
        r = correos.track("PXXX", client)
    assert r.ok and r.status == "not_found" and not r.found


def test_ups_web_not_scanned_yet():
    r = ups.parse_web(load("ups_web_not_found.json"))
    assert r.ok and r.status == "not_found" and not r.found


def test_ups_web_in_transit_with_date_and_origin():
    r = ups.parse_web(load("ups_web_in_transit.json"))
    assert r.found and r.status == "in_transit"
    assert r.eta_from == "2026-10-05" and r.origin_country == "NL" and r.dest_country == "ES"
    ordered = sorted(r.events, key=lambda e: e.ts)
    assert ordered[0].status == "label_created" and ordered[-1].location.startswith("Köln")


def test_dhl_api_delivered():
    r = dhl.parse(load("dhl_api.json"))
    assert r.found and r.status == "delivered" and r.origin_country == "DE" and r.eta_from == "2026-08-21"
    assert any(e.status == "out_for_delivery" for e in r.events)


def test_17track_customs_and_window():
    item = load("track17.json")["data"]["accepted"][0]
    r = track17.parse(item)
    assert r.status == "customs" and r.eta_from == "2026-07-15" and r.eta_to == "2026-07-18" and r.origin_country == "CN"
    assert len(r.events) == 3


def test_17track_registers_unknown_numbers():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("gettrackinfo"):
            return httpx.Response(200, json={"code": 0, "data": {"accepted": [], "rejected": [{"number": "X", "error": {"code": -18019902}}]}})
        return httpx.Response(200, json={"code": 0, "data": {"accepted": [{"number": "X"}], "rejected": []}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        r = track17.Track17("k", client).track("YT2600000000000001")
    assert r.ok and r.status == "not_found" and calls[-1].endswith("register")


def test_plans(tmp_path):
    c = Carriers(make_config(tmp_path), lambda name: "", browser=NoBrowser())
    assert c.plan("correos") == ["correos"]
    assert c.plan("ups") == [] and c.plan("amazon") == []
    keys = {"TRACK17_KEY": "x", "UPS_CLIENT_ID": "a", "UPS_CLIENT_SECRET": "b", "DHL_API_KEY": "d"}
    c = Carriers(make_config(tmp_path), lambda name: keys.get(name, ""), browser=NoBrowser())
    assert c.plan("ups") == ["ups_api", "track17"]
    assert c.plan("dhl") == ["dhl_api", "track17"]
    assert c.plan("gls") == ["track17"]
    assert c.plan("amazon") == []
    result, attempts = c.track("amazon", "TBA000000000")
    assert not result.ok and "Amazon" in result.error


def test_refresh_applies_carrier_events(svc, clock):
    from conftest import build, FakeMail
    data = load("correos_delivered.json")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
    s2 = build(svc.config, clock, FakeMail(), transport=transport)
    try:
        s2.engine.ingest([M.WALLAPOP])
        s = s2.store.by_number(M.CORREOS_CODE)
        out = s2.engine.refresh(s["id"])
        assert out["ok"] and out["status"] == "delivered"
        s = s2.store.shipment(s["id"])
        assert s["status"] == "delivered" and s["delivered_ts"] and s["next_check_ts"] is None
        assert len(s2.store.events(s["id"])) >= 6
        assert (s2.config.raw_dir / f"{s['id']}.json").is_file()
    finally:
        s2.stop()


def test_ups_web_through_the_browser_rung(tmp_path, clock):
    from conftest import build, FakeMail

    class FakeBrowser(NoBrowser):
        channel = "msedge"

        def available(self):
            return True, ""

        def capture_json(self, url, match, timeout_s=45):
            assert M.UPS in url and match == ups.WEB_MATCH
            return load("ups_web_in_transit.json"), ""

    s2 = build(make_config(tmp_path), clock, FakeMail(), browser=FakeBrowser())
    try:
        s2.engine.ingest([M.PCS_SHIPPED])
        s = s2.store.by_number(M.UPS)
        out = s2.engine.refresh(s["id"])
        assert out["source"] == "ups_web" and out["status"] == "in_transit"
        s = s2.store.shipment(s["id"])
        assert s["carrier_eta_from"] == "2026-10-05" and s["origin_country"] == "NL" and s["first_scan_ts"]
        assert s["eta_likely"] == "2026-10-05"
        assert s["next_check_ts"] and s["next_check_ts"] > clock()
        titles = [e["title"] for e, _ in s2.notifier.sent]
        assert any(t.startswith("UPS ya lo tiene") for t in titles)
    finally:
        s2.stop()
