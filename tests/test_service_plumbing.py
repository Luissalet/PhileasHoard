"""The app shell on the shared service plumbing: error envelope, PWA, SPA fallback, agent router, entry point."""

import os

from phileas_hoard.__main__ import main

LOCAL = {"host": "localhost:5199"}


def test_health_probe_keeps_its_fields(client):
    body = client.get("/api/health", headers=LOCAL).json()
    assert body["service"] == "phileas-hoard"
    assert {"version", "dataDirConfigured", "offline", "counts", "scheduler", "hoard_link"} <= set(body)


def test_pwa_manifest_and_worker(client):
    manifest = client.get("/manifest.webmanifest", headers=LOCAL)
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    assert manifest.json()["short_name"] == "Phileas"
    worker = client.get("/sw.js", headers=LOCAL)
    assert "phileas-hoard-" in worker.text and worker.headers["service-worker-allowed"] == "/"


def test_unknown_api_path_is_a_json_404(client):
    response = client.get("/api/nothing-here", headers=LOCAL)
    assert response.status_code == 404 and response.json()["error"] == "Not found."


def test_validation_errors_are_400_json(client):
    response = client.post("/api/ui/call", json={"arguments": {}}, headers=LOCAL)
    assert response.status_code == 400 and "name" in response.json()["error"]


def test_agent_call_needs_the_token_and_reports_app_errors(client):
    denied = client.post("/api/agent/call", json={"name": "phileas_overview"}, headers=LOCAL)
    assert denied.status_code == 401
    auth = {**LOCAL, **client.bearer}
    ok = client.post("/api/agent/call", json={"name": "phileas_overview"}, headers=auth)
    assert ok.status_code == 200
    unknown = client.post("/api/agent/call", json={"name": "no_such_tool"}, headers=auth)
    assert unknown.status_code == 404
    bad = client.post("/api/agent/call", json={"name": "shipment_get", "arguments": {}}, headers=auth)
    assert bad.status_code == 400


def test_entry_point_passes_the_app_identity(monkeypatch):
    seen = {}
    monkeypatch.setattr("phileas_hoard.__main__.run_main", lambda **kw: seen.update(kw) or 0)
    monkeypatch.delenv("PHILEAS_PORT", raising=False)
    monkeypatch.setenv("PORT", "5300")
    assert main([]) == 0
    assert seen["service"] == "phileas-hoard" and seen["default_port"] == 5199 and seen["open_browser_default"] is False
    assert seen["app_factory"] == "phileas_hoard.main:create_app" and seen["data_dir_env"] == "PHILEAS_DATA_DIR"
    assert os.environ["PHILEAS_PORT"] == "5300"
    monkeypatch.delenv("PHILEAS_PORT")
