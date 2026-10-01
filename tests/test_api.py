"""HTTP surface: health, dashboard, the UI bridge, the agent bridge and its token."""

from __future__ import annotations

import mails as M


def test_health_and_status(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["service"] == "phileas-hoard"
    assert client.get("/api/status").json()["counts"]["active"] == 0


def test_dashboard_lists_active_parcels(client):
    client.svc.engine.ingest([M.PCS_ORDER, M.PCS_SHIPPED, M.WALLAPOP])
    d = client.get("/api/dashboard").json()
    labels = {c["merchant"] for c in d["active"]}
    assert {"PCSpecialist", "Wallapop"} <= labels
    assert any(c["status"] == "available_for_pickup" for c in d["attention"])
    assert d["news"]
    assert client.post("/api/dashboard/visit").json()["marked_seen"] >= 1
    assert client.get("/api/dashboard").json()["news"] == []


def test_ui_call_and_detail(client):
    client.svc.engine.ingest([M.PCS_SHIPPED])
    rows = client.post("/api/ui/call", json={"name": "shipments_list", "arguments": {}}).json()["shipments"]
    sid = rows[0]["id"]
    detail = client.get(f"/api/shipments/{sid}").json()
    assert detail["shipment"]["tracking_number"] == M.UPS and detail["events"] and detail["mails"]
    r = client.post("/api/ui/call", json={"name": "shipment_update", "arguments": {"shipment": sid, "label": "Portátil", "muted": True}})
    assert r.json()["shipment"]["label"] == "Portátil" and r.json()["shipment"]["muted"]
    r = client.post("/api/ui/call", json={"name": "shipment_delete", "arguments": {"shipment": sid}})
    assert r.status_code == 400 and r.json()["code"] == "confirm_required"


def test_agent_needs_the_token(client):
    assert client.post("/api/agent/call", json={"name": "phileas_overview"}).status_code == 401
    r = client.post("/api/agent/call", json={"name": "phileas_overview"}, headers=client.bearer)
    assert r.status_code == 200 and "active" in r.json()
    tools = client.get("/api/agent/tools").json()["tools"]
    assert len(tools) >= 25
    assert all(len(t["description"].splitlines()[0]) <= 110 for t in tools)


def test_manual_add_and_settings(client):
    r = client.post("/api/ui/call", json={"name": "shipment_add", "arguments": {"tracking_number": M.S10, "label": "Libro", "check_now": False}})
    assert r.json()["created"] and r.json()["shipment"]["carrier"] == "correos"
    r = client.post("/api/ui/call", json={"name": "settings_set", "arguments": {"values": {"eta.region": "ES-CT", "mail.interval_min": 15}}})
    assert r.json()["settings"]["eta.region"] == "ES-CT"
    r = client.post("/api/ui/call", json={"name": "settings_set", "arguments": {"values": {"mail.interval_min": 1}}})
    assert r.status_code == 400
    r = client.post("/api/ui/call", json={"name": "secret_set", "arguments": {"name": "TRACK17_KEY", "value": "abcdefgh1234"}})
    assert r.json()["TRACK17_KEY"]["value"] == "…1234"
    assert client.svc.carriers.plan("gls") == ["track17"]


def test_guard_rejects_cross_site(client):
    r = client.post("/api/ui/call", json={"name": "phileas_status"}, headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
