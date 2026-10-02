"""The notification channels on the shared channel code: ntfy, Telegram, SMTP, the Faustus mail helper, the bus event and the toast."""

from __future__ import annotations

import json
import smtplib
from types import SimpleNamespace

from phileas_hoard.hoard_link import family
from phileas_hoard.notify import Notifier, build_toast_ps1, telegram_discover_chat_id, xml_escape

EVENT = {"id": "s1:out_for_delivery", "type": "out_for_delivery", "severity": "high", "title": "Llega hoy: Cable <USB> & más",
         "summary": "UPS: en reparto.", "url": "https://www.ups.com/track?tracknum=1Z1&x=2", "shipment_id": "s1", "status": "out_for_delivery",
         "label": "Cable", "carrier": "ups", "tracking_number": "1Z1"}
TRIP = {"id": "t1:checkin", "type": "checkin_open", "severity": "medium", "title": "Check-in abierto", "summary": "Madrid → Lisboa",
        "url": "https://example.com/checkin", "trip_id": "t1", "segment_id": "g1", "trip_title": "Lisboa", "start_date": "2026-11-12", "end_date": "2026-11-15"}


class Cfg:
    def __init__(self, **secrets):
        self.secrets = dict(secrets)

    def secret(self, name):
        return self.secrets.get(name, "")


def make(cfg=None, sett=None, **kw):
    values = {"mail__faustus_dir": "/nonexistent/faustus", **(sett or {})}
    return Notifier(cfg or Cfg(), lambda key, default=None: values.get(key.replace(".", "__"), default), clock=lambda: 42.0,
                    platform=kw.pop("platform", "win32"), **kw)


class Http:
    def __init__(self, status=200, data=None, error=None, fn=None):
        self.status, self.data, self.error, self.fn, self.calls = status, data, error, fn, []

    def __call__(self, url, payload=None, headers=None, timeout=10.0):
        self.calls.append({"url": url, "payload": payload, "headers": headers or {}})
        if self.fn is not None:
            return self.fn(url, payload)
        return (None, self.error) if self.error else (self.status, self.data)


def test_bus_event_uses_one_topic_for_parcels_and_another_for_trips(monkeypatch):
    got = []
    monkeypatch.setattr(family, "emit", lambda type, data=None, **kw: got.append((type, data)) or True)
    n = make(Cfg(), {"notify__hub__enabled": "1"})
    assert n.send(EVENT, ["hub"])[0]["ok"] and n.send(TRIP, ["hub"])[0]["ok"]
    assert got[0][0] == "phileas.update" and got[0][1]["shipment_id"] == "s1" and got[0][1]["tracking_number"] == "1Z1"
    assert got[1][0] == "phileas.trip.update" and got[1][1]["trip_id"] == "t1" and "shipment_id" not in got[1][1]
    monkeypatch.setattr(family, "emit", lambda *a, **k: False)
    assert make().send(EVENT, ["hub"])[0]["error"] == "hub not configured"


def test_ntfy_json_publish_has_a_priority_per_severity():
    http = Http(data={"id": "x"})
    n = make(Cfg(NTFY_TOPIC="topic-1", NTFY_TOKEN="tk_secret"), {"notify__ntfy__enabled": "1", "notify__ntfy__server": "https://ntfy.example/",
                                                                  "notify__via": "own"}, http=http)
    assert n.send(EVENT, ["ntfy"])[0]["ok"]
    call = http.calls[0]
    assert call["headers"]["Authorization"] == "Bearer tk_secret" and call["payload"]["topic"] == "topic-1"
    assert call["payload"]["priority"] == 4 and call["payload"]["click"] == EVENT["url"]
    medium = Http()
    make(Cfg(NTFY_TOPIC="t"), {"notify__ntfy__enabled": "1", "notify__via": "own"}, http=medium).send({**EVENT, "severity": "medium"}, ["ntfy"])
    assert medium.calls[0]["payload"]["priority"] == 3
    down = Http(error="ConnectError")
    res = make(Cfg(NTFY_TOPIC="from-secret"), {"notify__ntfy__enabled": "1", "notify__via": "own"}, http=down).send(EVENT, ["ntfy"])
    assert res[0]["error"] == "ConnectError" and "from-secret" not in json.dumps(res)


def test_telegram_escapes_html_labels_trips_and_never_leaks_the_token():
    http = Http(data={"ok": True})
    n = make(Cfg(TELEGRAM_TOKEN="123:ABC", TELEGRAM_CHAT_ID="-1001"), {"notify__telegram__enabled": "1", "notify__via": "own"}, http=http)
    assert n.send(EVENT, ["telegram"])[0]["ok"] and n.send(TRIP, ["telegram"])[0]["ok"]
    parcel, trip = http.calls[0]["payload"], http.calls[1]["payload"]
    assert http.calls[0]["url"] == "https://api.telegram.org/bot123:ABC/sendMessage" and parcel["parse_mode"] == "HTML"
    assert "&lt;USB&gt; &amp;" in parcel["text"] and "Ver seguimiento" in parcel["text"] and "Abrir enlace" in trip["text"]
    bad = Http(status=401, data={"ok": False, "description": "Unauthorized bot123:ABC"})
    res = make(Cfg(TELEGRAM_TOKEN="123:ABC", TELEGRAM_CHAT_ID="99"), {"notify__telegram__enabled": "1", "notify__via": "own"}, http=bad).send(EVENT, ["telegram"])
    assert res[0]["ok"] is False and "123:ABC" not in json.dumps(res)


def test_telegram_chat_id_discovery():
    def answer(url, payload):
        return 200, {"ok": True, "result": [{"update_id": 2, "message": {"chat": {"id": 777, "first_name": "Ana", "last_name": "M", "type": "private"}}}]}

    assert telegram_discover_chat_id("123:ABC", http=Http(fn=answer)) == {"ok": True, "chat_id": "777", "name": "Ana M", "error": ""}
    assert telegram_discover_chat_id("")["error"] == "missing PHILEAS_TELEGRAM_TOKEN"
    assert make(Cfg(TELEGRAM_TOKEN="123:ABC"), http=Http(fn=answer)).telegram_discover_chat_id()["chat_id"] == "777"


class FakeSMTP:
    instances: list = []

    def __init__(self, cfg, fail=None):
        self.host, self.port, self.use_ssl, self.fail = cfg["host"], cfg["port"], cfg["port"] == 465, fail
        self.sent, self.logged, self.quit_called = [], None, False
        FakeSMTP.instances.append(self)

    def login(self, user, password):
        self.logged = (user, password)
        if self.fail == "auth":
            raise smtplib.SMTPAuthenticationError(535, b"bad password hunter2")

    def send_message(self, msg):
        self.sent.append(msg)

    def quit(self):
        self.quit_called = True


def test_email_over_smtp_is_multipart_and_reports_errors_without_secrets():
    FakeSMTP.instances = []
    secrets = {"SMTP_USER": "me@gmail.com", "SMTP_PASSWORD": "hunter2"}
    n = make(Cfg(**secrets), {"notify__email__enabled": "1", "notify__via": "own"}, smtp_factory=FakeSMTP)
    assert n.channels_status()["email"]["detail"] == "SMTP smtp.gmail.com:465"
    assert n.send(EVENT, ["email"])[0]["ok"]
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.use_ssl, smtp.quit_called) == ("smtp.gmail.com", 465, True, True)
    msg = smtp.sent[0]
    assert msg["To"] == "me@gmail.com" and "https://www.ups.com/track?tracknum=1Z1&x=2" in msg.get_body(("plain",)).get_content()
    html_part = msg.get_body(("html",)).get_content()
    assert "&lt;USB&gt;" in html_part and "<USB>" not in html_part
    bad = make(Cfg(**secrets), {"notify__email__enabled": "1", "notify__via": "own"}, smtp_factory=lambda cfg: FakeSMTP(cfg, fail="auth"))
    res = bad.send(EVENT, ["email"])
    assert res[0]["error"] == "authentication failed" and "hunter2" not in json.dumps(res)


def fake_faustus(tmp_path):
    root = tmp_path / "faustus"
    (root / "mcp_servers").mkdir(parents=True)
    (root / "mcp_servers" / "email_server.py").write_text("# stub\n")
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "python").write_text("")
    return root


class Runner:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, argv, **kw):
        self.calls.append((argv, json.loads(kw["input"]), kw))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return SimpleNamespace(returncode=0, stdout="noise from an import\n" + json.dumps(answer), stderr="")


def test_email_through_faustus_runs_the_shared_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("PHILEAS_TELEGRAM_TOKEN", "leak-me-not")
    root = fake_faustus(tmp_path)
    ok = {"ok": True, "error": "", "account": "Main", "from": "abc***@example.org", "to": ["abc***@example.org"]}
    runner = Runner([ok])
    n = make(Cfg(), {"notify__email__enabled": "1", "mail__faustus_dir": str(root), "notify__via": "own"}, faustus_runner=runner)
    assert n.email_backend() == "faustus" and n.faustus_dir() == root.resolve()
    st = n.channels_status()["email"]
    assert st["configured"] and st["detail"] == "Faustus account Main <abc***@example.org> → abc***@example.org"
    argv, request, kw = runner.calls[0]
    assert argv[1].endswith("mail_helper.py") and request["action"] == "status" and not any(k.startswith("PHILEAS_") for k in kw["env"])
    assert n.send(EVENT, ["email"])[0]["ok"] and len(runner.calls) == 2
    _, sent, _ = runner.calls[1]
    assert sent["action"] == "send" and "&lt;USB&gt;" in sent["html"] and "to" not in sent
    failing = make(Cfg(), {"notify__email__enabled": "1", "mail__faustus_dir": str(root), "notify__via": "own"},
                   faustus_runner=Runner([ok, {"ok": False, "error": "authentication failed"}]))
    assert failing.send(EVENT, ["email"])[0]["error"] == "authentication failed" and failing._faustus_status is None


def test_toast_script_and_escaping():
    assert xml_escape("<a & b>") == "&lt;a &amp; b&gt;"
    script = build_toast_ps1("Llega hoy", "Cable <USB>", "https://x.example/t")
    assert "Windows.UI.Notifications" in script and "&lt;USB&gt;" in script
