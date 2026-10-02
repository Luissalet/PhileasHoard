from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
for entry in (str(ROOT), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

warnings.filterwarnings("ignore", category=DeprecationWarning)

from fastapi.testclient import TestClient  # noqa: E402

from phileas_hoard.agent_tools import call_tool  # noqa: E402
from phileas_hoard.config import Config  # noqa: E402
from phileas_hoard.main import create_app  # noqa: E402
from phileas_hoard.services import Services  # noqa: E402

from mails import T0  # noqa: E402


def _no_network():
    import httpx

    def handler(request):
        raise httpx.ConnectError(f"network disabled in tests: {request.url}")
    return httpx.MockTransport(handler)


class FakeNotifier:
    def __init__(self):
        self.sent: list[tuple[dict, list[str]]] = []

    def send(self, event, channels):
        self.sent.append((event, list(channels)))
        return [{"channel": c, "ok": True, "error": ""} for c in channels if c in ("hub", "toast")]

    def test(self, channel):
        return {"channel": channel, "ok": True, "error": ""}

    def channels_status(self):
        return {"toast": {"configured": True, "enabled": True}, "hub": {"configured": True, "enabled": True}}

    def telegram_discover_chat_id(self):
        return {"ok": False}

    def types(self):
        return [e["type"] for e, _ in self.sent]


class FakeMail:
    """Stands in for the Faustus mail helper: hands back the messages it was given, minus the skipped ids."""

    def __init__(self, messages: list[dict[str, Any]] | None = None):
        self.messages = list(messages or [])
        self.calls: list[dict[str, Any]] = []

    def scan(self, *, since_days, limit, skip, query="", **extra):
        self.calls.append({"since_days": since_days, "limit": limit, "skip": len(skip), "query": query, **extra})
        skip = set(skip)
        return {"ok": True, "accounts": [{"account": "test", "folder": "INBOX", "matches": len(self.messages)}],
                "messages": [m for m in self.messages if m["message_id"] not in skip][:limit]}

    def status(self, refresh=False):
        return {"ok": True, "accounts": [{"account": "test"}]}

    def faustus_dir(self):
        return None


class Clock:
    def __init__(self, t: float = T0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class NoBrowser:
    channel = ""

    def available(self):
        return False, "off in tests"

    def capture_json(self, url, match, timeout_s=45):
        return None, "off in tests"

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_family_hub(monkeypatch):
    """No test talks to a real hub: the notification centre, the mail gateway and the reference graph answer "away" unless a test fakes them."""
    from phileas_hoard.hoard_link import fam_mail, fam_notify, fam_refs

    monkeypatch.setattr(fam_notify, "hub_available", lambda timeout=1.0: False)
    monkeypatch.setattr(fam_notify, "notify", lambda *a, **k: {"ok": False, "error": "hub unreachable"})
    monkeypatch.setattr(fam_mail, "available", lambda timeout=1.0: False)
    monkeypatch.setattr(fam_mail, "register_interest", lambda *a, **k: {"ok": False, "error": "hub unreachable"})
    monkeypatch.setattr(fam_mail, "claim", lambda *a, **k: {"ok": False, "error": "hub unreachable"})
    monkeypatch.setattr(fam_refs, "link", lambda *a, **k: {"ok": False, "error": "hub unreachable"})


def make_config(tmp_path: Path, **overrides) -> Config:
    base = dict(data_dir=tmp_path / "data", port=0, port_strict=False, data_dir_configured=True, scheduler=False,
                browser=False, offline=False, secrets={})
    base.update(overrides)
    return Config(**base)


@pytest.fixture
def config(tmp_path):
    return make_config(tmp_path)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def fake_mail():
    return FakeMail()


def build(config, clock, fake_mail, transport=None, browser=None, **extra):
    return Services(config, clock_fn=clock, http_transport=transport or _no_network(), notifier=FakeNotifier(), browser=browser or NoBrowser(),
                    mail_source=fake_mail, **extra)


@pytest.fixture
def svc(config, clock, fake_mail):
    s = build(config, clock, fake_mail)
    yield s
    s.stop()


@pytest.fixture
def client(config, clock, fake_mail):
    services = build(config, clock, fake_mail)
    app = create_app(config, services=services)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.svc = services
        c.bearer = {"Authorization": f"Bearer {services.token}"}
        yield c


def tool(svc: Services, tool_name: str, /, **arguments) -> Any:
    return call_tool(svc, tool_name, arguments)


class FakeHub:
    """Stands in for ``family.call``: answers per (app, tool) from a table; records what was asked."""

    def __init__(self, answers: dict | None = None):
        self.answers = dict(answers or {})
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, app, tool, arguments=None, **kw):
        self.calls.append((app, tool, dict(arguments or {})))
        answer = self.answers.get((app, tool))
        if callable(answer):
            answer = answer(arguments or {})
        if answer is None:
            return {"ok": False, "app": app, "tool": tool, "status": None, "error": "hub not reachable at http://127.0.0.1:0"}
        return {"ok": True, "app": app, "tool": tool, "status": 200, "result": answer}
