"""The family hub side: notifications through the hub, mail through the hub, shipment events and the agenda."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import mails as M
import travel_mails as tm
from conftest import FakeHub, FakeMail, build, tool
from phileas_hoard.agenda import build_items
from phileas_hoard.engine import Engine
from phileas_hoard.errors import PhileasError
from phileas_hoard.mail.source import HUB_PAGE_MAX, MailSource, interest_spec
from phileas_hoard.notify import Notifier

ROOT = Path(__file__).resolve().parent.parent
EVENT = {"id": "s1:out_for_delivery", "type": "out_for_delivery", "severity": "high", "title": "Arriving today: Cable", "summary": "UPS: out for delivery.",
         "url": "https://www.ups.com/track?tracknum=1Z1", "shipment_id": "s1", "dedupe_key": "phileas:s1|out|2026-10-01"}


class Cfg:
    secrets: dict = {}

    def secret(self, name):
        return ""


class FakeHubNotify:
    """Stands in for hoard_link.fam_notify."""

    def __init__(self, up=True, answer=None):
        self.up, self.calls = up, []
        self.answer = answer if answer is not None else {"ok": True, "id": 7, "held": ""}

    def hub_available(self, timeout=1.0):
        return self.up

    def notify(self, title, body="", **kw):
        self.calls.append({"title": title, "body": body, **kw})
        return dict(self.answer)


def notifier(sett=None, hub=None):
    values = {"notify__email__faustus_dir": "/nonexistent/faustus", "ui__language": "en", **{k.replace(".", "__"): v for k, v in (sett or {}).items()}}
    shown = []
    n = Notifier(Cfg(), lambda key, default=None: values.get(key.replace(".", "__"), default), clock=lambda: 42.0, platform="win32",
                 toast_backend=lambda t, b, u, h: shown.append((t, b)), hub_notify=hub)
    n.shown = shown
    return n


# ============================================================================ 1. notifications through the hub
def test_auto_sends_one_hub_notification_instead_of_the_push_channels():
    hub = FakeHubNotify()
    n = notifier(hub=hub)
    results = n.send(EVENT, ["toast", "hub", "ntfy", "telegram", "email"])
    assert len(hub.calls) == 1 and n.shown == []
    call = hub.calls[0]
    assert call["priority"] == "high" and call["group"] == "parcel" and call["dedupe_key"] == "phileas:s1|out|2026-10-01"
    assert call["url"] == "https://www.ups.com/track?tracknum=1Z1" and call["title"] == "Arriving today: Cable"
    by = {r["channel"]: r for r in results}
    assert [by[c]["via"] for c in ("toast", "ntfy", "telegram", "email")] == ["hub"] * 4 and by["toast"]["ok"]
    assert "via" not in by["hub"]                              # the bus event is a separate channel and still runs on its own


def test_trip_notifications_use_their_own_group_and_severity_maps_to_priority():
    hub = FakeHubNotify()
    n = notifier(hub=hub)
    n.send({**EVENT, "trip_id": "t1", "severity": "low", "dedupe_key": "k1"}, ["toast"])
    assert hub.calls[-1]["group"] == "trip" and hub.calls[-1]["priority"] == "low"
    n.send({**EVENT, "severity": "medium", "dedupe_key": "k2"}, ["toast"])
    assert hub.calls[-1]["priority"] == "normal"


def test_a_held_notification_is_handled_not_failed():
    hub = FakeHubNotify(answer={"ok": True, "id": 9, "held": "quiet"})
    (res,) = notifier(hub=hub).send(EVENT, ["toast"])
    assert res["ok"] and res["via"] == "hub" and "quiet" in res["error"]


def test_auto_falls_back_to_the_own_channels_when_the_hub_is_away_or_refuses():
    for hub in (FakeHubNotify(up=False), FakeHubNotify(answer={"ok": False, "error": "hub unreachable"})):
        n = notifier(hub=hub)
        (res,) = n.send(EVENT, ["toast"])
        assert res["ok"] and "via" not in res and len(n.shown) == 1


def test_hub_mode_reports_the_failure_and_never_falls_back():
    hub = FakeHubNotify(answer={"ok": False, "error": "hub unreachable"})
    n = notifier({"notify.via": "hub"}, hub)
    (res,) = n.send(EVENT, ["toast"])
    assert not res["ok"] and res["via"] == "hub" and n.shown == []


def test_own_mode_never_calls_the_hub():
    hub = FakeHubNotify()
    n = notifier({"notify.via": "own"}, hub)
    n.send(EVENT, ["toast"])
    assert hub.calls == [] and len(n.shown) == 1


def test_a_raising_hub_never_raises_out_of_send():
    class Boom(FakeHubNotify):
        def notify(self, *a, **k):
            raise RuntimeError("down")
    n = notifier({"notify.via": "hub"}, Boom())
    (res,) = n.send(EVENT, ["toast"])
    assert not res["ok"] and "RuntimeError" in res["error"]


def test_via_status_and_the_test_button():
    hub = FakeHubNotify()
    assert notifier(hub=hub).via_status() == {"setting": "auto", "effective": "hub", "hub_available": True}
    assert notifier({"notify.via": "own"}, hub).via_status()["effective"] == "own"
    assert notifier(hub=FakeHubNotify(up=False)).via_status()["effective"] == "own"
    out = notifier({"notify.via": "own"}, hub).test_hub()
    assert out["ok"] and out["via"] == "hub" and hub.calls[-1]["group"] == "parcel"


def test_engine_notifications_carry_a_dedupe_key(svc):
    svc.engine.ingest([M.PCS_ORDER, M.PCS_SHIPPED])
    events = [e for e, _ in svc.notifier.sent]
    assert events and all(e["dedupe_key"].startswith("phileas:") and "|" in e["dedupe_key"] for e in events)


def test_notify_via_and_mail_source_are_validated_settings(svc):
    out = svc.set_settings({"notify.via": "hub", "mail.source": "faustus"})
    assert out["notify.via"] == "hub" and out["mail.source"] == "faustus"
    assert svc.settings()["notify.via"] == "hub"
    with pytest.raises(PhileasError):
        svc.set_settings({"notify.via": "carrier-pigeon"})
    with pytest.raises(PhileasError):
        svc.set_settings({"mail.source": "pigeon"})


# ============================================================================ 2. mail through the hub
class FakeHubMail:
    """Stands in for hoard_link.fam_mail: a list of gateway messages served by id, oldest first."""

    def __init__(self, rows=None, up=True):
        self.up, self.rows, self.interests, self.claims, self.asked = up, list(rows or []), [], [], []

    def available(self, timeout=1.0):
        return self.up

    def register_interest(self, spec, sphere=None, timeout=10.0):
        self.interests.append(spec)
        return {"ok": True}

    def messages(self, since_id=0, limit=100, full=True, interest=True, timeout=20.0):
        self.asked.append(since_id)
        rows = [r for r in self.rows if r["id"] > since_id][:limit]
        return {"ok": True, "messages": [dict(r) for r in rows], "last_id": rows[-1]["id"] if rows else since_id}

    def claim(self, ids, kind, ref, timeout=10.0):
        self.claims.append((list(ids), kind, ref))
        return {"ok": True}


def hub_row(hub_id: int, base: dict) -> dict:
    """A shipping test mail as the gateway returns it (Kafka-style keys next to the gateway's)."""
    return {"id": hub_id, "message_id": base["message_id"], "subject": base["subject"], "from_name": base.get("from_name", ""),
            "from_address": base["from_address"], "from_addr": base["from_address"], "ts": base["ts"], "text": base["text"],
            "links": base["links"], "account": "inbox"}


class FakeOwn:
    """Stands in for FaustusMail (the own helper)."""

    def __init__(self, messages=None, folder=None):
        self.messages, self.calls, self.folder = list(messages or []), [], folder

    def faustus_dir(self):
        return self.folder

    def status(self, refresh=False):
        return {"ok": True, "accounts": [{"account": "own"}]}

    def scan(self, **kw):
        self.calls.append(kw)
        return {"ok": True, "accounts": [{"account": "own"}], "messages": list(self.messages)}


def source(hub, own=None, sett=None, clock=lambda: M.T0):
    store = dict(sett or {})
    src = MailSource(own or FakeOwn(), lambda k, d=None: store.get(k, d), lambda k, v: store.__setitem__(k, v), hub_mail=hub, clock=clock)
    src.store = store
    return src


def test_interest_covers_what_phileas_reads_today():
    spec = interest_spec(False)
    assert "tracking" in spec["subject_terms"] and "seguimiento" in spec["subject_terms"] and "reserva" not in spec["subject_terms"]
    assert {"amazon.es", "ups.com", "inpost.es", "correos.es"} <= set(spec["from_domains"])
    travel = interest_spec(True)
    assert "reserva" in travel["subject_terms"] and "boarding pass" in travel["subject_terms"]


def test_hub_scan_registers_the_interest_reads_from_the_watermark_and_commits_after():
    hub = FakeHubMail([hub_row(1, M.PCS_ORDER), hub_row(2, M.PCS_SHIPPED)])
    src = source(hub, sett={"mail.hub.since_id": "1"})
    out = src.scan(since_days=14, limit=100, skip=[], travel=False)
    assert out["ok"] and out["via"] == "hub" and [m["hub_id"] for m in out["messages"]] == [2]
    assert hub.interests and hub.asked == [1]
    assert src.store["mail.hub.since_id"] == "1"                 # not moved until the engine stored the messages
    src.commit()
    assert src.store["mail.hub.since_id"] == "2"
    src.scan(since_days=14, limit=100, skip=[], travel=False)
    assert len(hub.interests) == 1                               # registered once


def test_hub_scan_skips_known_ids_and_mail_older_than_the_window():
    old = {**M.PCS_ORDER, "ts": M.T0 - 40 * M.D, "message_id": "<old@test>"}
    hub = FakeHubMail([hub_row(1, old), hub_row(2, M.PCS_ORDER), hub_row(3, M.PCS_SHIPPED)])
    out = source(hub).scan(since_days=14, limit=100, skip=[M.PCS_ORDER["message_id"]], travel=False)
    assert [m["message_id"] for m in out["messages"]] == [M.PCS_SHIPPED["message_id"]]


def test_hub_scan_follows_full_pages():
    rows = [hub_row(i, {**M.PCS_ORDER, "message_id": f"<m{i}@test>"}) for i in range(1, HUB_PAGE_MAX + 11)]
    hub = FakeHubMail(rows)
    out = source(hub).scan(since_days=14, limit=10000, skip=[], travel=False)
    assert len(out["messages"]) == HUB_PAGE_MAX + 10 and hub.asked == [0, HUB_PAGE_MAX]


def test_auto_uses_the_hub_when_it_answers_and_the_own_helper_otherwise():
    own = FakeOwn([M.PCS_ORDER])
    up = source(FakeHubMail([hub_row(1, M.PCS_SHIPPED)]), own)
    assert up.scan(since_days=14, limit=10, skip=[])["via"] == "hub" and own.calls == []
    down = source(FakeHubMail(up=False), own)
    assert down.scan(since_days=14, limit=10, skip=[])["messages"] == [M.PCS_ORDER] and len(own.calls) == 1


def test_auto_falls_back_when_the_hub_refuses_the_interest():
    class Refuses(FakeHubMail):
        def register_interest(self, spec, sphere=None, timeout=10.0):
            return {"ok": False, "error": "mailgate is off"}
    own = FakeOwn([M.PCS_ORDER])
    assert source(Refuses(), own).scan(since_days=14, limit=10, skip=[])["messages"] == [M.PCS_ORDER]
    hub_only = source(Refuses(), own, {"mail.source": "hub"}).scan(since_days=14, limit=10, skip=[])
    assert not hub_only["ok"] and "mailgate" in hub_only["error"]


def test_faustus_mode_never_touches_the_hub():
    hub = FakeHubMail([hub_row(1, M.PCS_SHIPPED)])
    own = FakeOwn([M.PCS_ORDER])
    out = source(hub, own, {"mail.source": "faustus"}).scan(since_days=14, limit=10, skip=[])
    assert out["messages"] == [M.PCS_ORDER] and hub.asked == [] and hub.interests == []


def test_a_deep_scan_goes_to_the_own_helper_when_there_is_one_else_reads_the_hub_from_the_start():
    hub = FakeHubMail([hub_row(1, M.PCS_ORDER), hub_row(2, M.PCS_SHIPPED)])
    own = FakeOwn([M.GOOGLE_READY], folder=Path("/faustus"))
    out = source(hub, own, {"mail.hub.since_id": "2"}).scan(since_days=365, limit=10, skip=[], deep=True)
    assert out["messages"] == [M.GOOGLE_READY] and hub.asked == []
    lone = source(hub, FakeOwn(), {"mail.hub.since_id": "2"})
    out = lone.scan(since_days=365, limit=10, skip=[], deep=True)
    assert len(out["messages"]) == 2 and hub.asked == [0]
    lone.commit()
    assert lone.store["mail.hub.since_id"] == "2"                # a deep read never moves the watermark


def test_a_query_filters_the_hub_mail_by_its_words():
    hub = FakeHubMail([hub_row(1, M.PCS_ORDER), hub_row(2, M.PCS_SHIPPED)])
    out = source(hub, sett={"mail.source": "hub"}).scan(since_days=30, limit=10, skip=[], query="enviado", deep=True)
    assert [m["message_id"] for m in out["messages"]] == [M.PCS_SHIPPED["message_id"]]


def test_status_reports_the_source():
    st = source(FakeHubMail()).status()
    assert st["ok"] and st["source"]["effective"] == "hub" and st["source"]["hub_available"]
    assert source(FakeHubMail(), sett={"mail.source": "faustus"}).source_status()["effective"] == "faustus"


def build_hub(config, clock, hub, own=None, hub_sett=None):
    src = MailSource(own or FakeOwn(), lambda k, d=None: None, lambda k, v: None, hub_mail=hub, clock=clock)
    svc = build(config, clock, src)
    src.get, src.put = svc.db.get_setting, svc.db.set_setting
    return svc


def test_the_engine_files_hub_mail_claims_it_and_remembers_the_watermark(config, clock):
    hub = FakeHubMail([hub_row(5, M.PCS_ORDER), hub_row(6, M.PCS_SHIPPED), hub_row(7, M.NOISE[0])])
    svc = build_hub(config, clock, hub)
    out = svc.engine.scan_mail()
    assert out["ok"] and out["created"] == 1 and out["messages"] == 3
    shipment = svc.store.by_number(M.UPS)
    ref = f"hoard://phileas/shipment/{shipment['id']}"
    assert ([5], "shipment", ref) in hub.claims and ([6], "shipment", ref) in hub.claims
    assert not any(c[0] == [7] for c in hub.claims)               # noise is not Phileas's mail
    assert svc.db.get_setting("mail.hub.since_id") == "7"
    again = svc.engine.scan_mail()
    assert again["messages"] == 0 and hub.asked[-1] == 7
    svc.stop()


def test_a_travel_mail_is_claimed_with_its_trip(config, clock):
    hub = FakeHubMail([hub_row(1, tm.IBERIA)])
    svc = build_hub(config, clock, hub)
    svc.set_settings({"travel.home_city": "Madrid"})
    svc.travel.chat = lambda messages, schema: {"ok": False, "error": "no_model"}
    svc.engine.scan_mail()
    trip = svc.tstore.trips()[0]
    assert ([1], "trip", f"hoard://phileas/trip/{trip['id']}") in hub.claims
    svc.stop()


def test_a_failing_claim_never_breaks_the_scan(config, clock):
    class BadClaims(FakeHubMail):
        def claim(self, *a, **k):
            raise OSError("hub gone")
    svc = build_hub(config, clock, BadClaims([hub_row(1, M.PCS_SHIPPED)]))
    assert svc.engine.scan_mail()["ok"]
    assert svc.db.get_setting("mail.hub.since_id") == "1"
    svc.stop()


# ============================================================================ 3. events on the family bus
@pytest.fixture
def bus(svc):
    seen: list[tuple[str, dict]] = []
    svc.engine.emit = lambda t, d: seen.append((t, d))
    svc.seen = seen
    return svc


def names(svc, prefix="phileas."):
    return [t for t, _ in svc.seen if t.startswith(prefix)]


def test_a_new_parcel_emits_shipment_new_with_ids_and_names_only(bus):
    bus.engine.ingest([M.PCS_ORDER, M.PCS_SHIPPED])
    new = [d for t, d in bus.seen if t == "phileas.shipment.new"]
    assert len(new) == 1
    s = bus.store.by_number(M.UPS)
    assert new[0] == {"shipment_id": s["id"], "merchant": "PCSpecialist", "order_ref": "", "message_id": M.PCS_ORDER["message_id"],
                      "items": [s["item"]] if s["item"] else [], "carrier": "", "tracking_number": ""}


def test_shipment_new_carries_the_carrier_and_number_when_the_first_mail_has_them(bus):
    bus.engine.ingest([M.PCS_SHIPPED])
    (new,) = [d for t, d in bus.seen if t == "phileas.shipment.new"]
    assert new["carrier"] == "ups" and new["tracking_number"] == M.UPS and new["message_id"] == M.PCS_SHIPPED["message_id"]
    assert set(new) == {"shipment_id", "merchant", "order_ref", "message_id", "items", "carrier", "tracking_number"}


def test_a_linked_mail_is_not_a_second_new_shipment(bus):
    bus.engine.ingest([M.PCS_ORDER])
    bus.engine.ingest([M.PCS_SHIPPED])
    assert names(bus).count("phileas.shipment.new") == 1


def test_the_first_import_and_old_mail_emit_no_events(bus, fake_mail):
    fake_mail.messages = [M.GOOGLE_READY, M.GOOGLE_DELIVERED, M.PCS_ORDER, M.PCS_SHIPPED]
    bus.engine.scan_mail()
    assert names(bus) == []
    old = {**M.amazon("old1", M.T0 - 60 * M.D, "enviado", "Libro viejo", "406-0000000-1111111", "TOLD1")}
    bus.engine.ingest([old])
    assert names(bus) == []


def test_status_is_emitted_only_for_a_real_change(bus):
    order = "406-1111111-2222222"
    bus.engine.ingest([M.amazon("a1", M.T0 - 2 * M.D, "pedido", "Cable", order)])
    assert "phileas.status" not in names(bus)                       # the first status of a new parcel is shipment.new, not a change
    bus.engine.ingest([M.amazon("a2", M.T0 - 1 * M.D, "enviado", "Cable", order, "TAAA111")])
    bus.engine.ingest([M.amazon("a2b", M.T0 - 1 * M.D + 60, "enviado", "Cable", order, "TAAA111")])   # same status again
    changes = [d for t, d in bus.seen if t == "phileas.status"]
    assert [(c["from"], c["to"]) for c in changes] == [("ordered", "in_transit")]


def test_no_status_event_for_parcels_in_the_history(bus):
    sid = bus.store.create_shipment(label="old", carrier="ups", tracking_number="1ZOLD", status="in_transit", history_only=True,
                                    status_ts=M.T0 - 5 * M.D, last_change_ts=M.T0 - 5 * M.D)["id"]
    bus.engine.apply_status(sid, "delivered", M.T0 - M.D, source="carrier")
    assert names(bus) == []


def test_delivery_emits_shipment_delivered_with_the_time_once(bus, clock):
    order = "406-5555555-6666666"
    bus.engine.ingest([M.amazon("c1", M.T0 - 3 * M.D, "enviado", "Libro", order, "TCCC1")])
    sid = bus.store.shipments(archived=None, history_only=None)[0]["id"]
    when = M.T0 - 600
    assert bus.engine.apply_status(sid, "delivered", when, source="carrier", text="Delivered")
    assert not bus.engine.apply_status(sid, "delivered", when + 5, source="carrier")
    (done,) = [d for t, d in bus.seen if t == "phileas.shipment.delivered"]
    assert done["shipment_id"] == sid and done["delivered_at"] == datetime.fromtimestamp(when).isoformat(timespec="seconds")
    assert done["merchant"] == "Amazon" and done["order_ref"] == order and done["message_id"] == "<c1@test>"
    assert [(d["from"], d["to"]) for t, d in bus.seen if t == "phileas.status"][-1] == ("in_transit", "delivered")


def test_events_never_break_the_engine_when_the_bus_raises(svc):
    def boom(t, d):
        raise RuntimeError("bus down")
    svc.engine.emit = boom
    svc.engine.ingest([M.PCS_SHIPPED])
    assert svc.store.by_number(M.UPS)


# ============================================================================ 4. the agenda
def agenda(svc, days=60, start=None):
    today = datetime.fromtimestamp(svc.clock()).date()
    return build_items(svc, start or today - timedelta(days=7), today + timedelta(days=days), base_url="http://127.0.0.1:5199")


def test_expected_deliveries_and_pickup_deadlines_are_listed(svc):
    today = datetime.fromtimestamp(M.T0).date()
    soon = svc.store.create_shipment(label="Monitor", carrier="ups", tracking_number="1ZA", status="in_transit", merchant="Shop",
                                     eta_likely=(today + timedelta(days=2)).isoformat(), eta_from=today.isoformat(),
                                     eta_to=(today + timedelta(days=3)).isoformat())["id"]
    out = svc.store.create_shipment(label="Libro", carrier="correos", tracking_number="RR1ES", status="out_for_delivery")["id"]
    pick = svc.store.create_shipment(label="Funda", carrier="inpost", tracking_number="IP1", status="available_for_pickup",
                                     pickup_deadline=(today + timedelta(days=3)).isoformat(), pickup_place="Locker 12", pickup_code="4821")["id"]
    items = {i["id"]: i for i in agenda(svc)}
    d = items[f"phileas:delivery:{soon}"]
    assert d["kind"] == "delivery" and d["start"] == (today + timedelta(days=2)).isoformat() and d["all_day"] and d["priority"] == "normal"
    assert d["url"] == f"http://127.0.0.1:5199/#/envio/{soon}" and "UPS" in d["detail"]
    o = items[f"phileas:delivery:{out}"]
    assert o["start"] == today.isoformat() and o["priority"] == "high"
    p = items[f"phileas:deadline:{pick}"]
    assert p["kind"] == "deadline" and p["priority"] == "high" and p["title"] == "Recoger: Funda"
    assert "Locker 12" in p["detail"] and f"phileas:delivery:{pick}" not in items


def test_finished_archived_history_and_dateless_parcels_are_not_listed(svc):
    today = datetime.fromtimestamp(M.T0).date()
    day = (today + timedelta(days=1)).isoformat()
    svc.store.create_shipment(label="done", status="delivered", eta_likely=day, tracking_number="1ZDONE")
    svc.store.create_shipment(label="back", status="returned", eta_likely=day, tracking_number="1ZBACK")
    svc.store.create_shipment(label="arch", status="in_transit", eta_likely=day, archived=True, tracking_number="1ZARCH")
    svc.store.create_shipment(label="hist", status="in_transit", eta_likely=day, history_only=True, tracking_number="1ZHIST")
    svc.store.create_shipment(label="nodate", status="in_transit", tracking_number="1ZNODATE")
    assert agenda(svc) == []


def test_a_late_parcel_stays_on_its_expected_day_as_high_priority(svc):
    today = datetime.fromtimestamp(M.T0).date()
    sid = svc.store.create_shipment(label="Late", status="in_transit", tracking_number="1ZLATE", eta_likely=(today - timedelta(days=2)).isoformat())["id"]
    (item,) = agenda(svc)
    assert item["id"] == f"phileas:delivery:{sid}" and item["start"] == (today - timedelta(days=2)).isoformat() and item["priority"] == "high"


def test_the_window_is_respected(svc):
    today = datetime.fromtimestamp(M.T0).date()
    svc.store.create_shipment(label="Far", status="in_transit", tracking_number="1ZFAR", eta_likely=(today + timedelta(days=30)).isoformat())
    assert agenda(svc, days=10) == [] and len(agenda(svc, days=40)) == 1


@pytest.fixture
def tsvc(config, clock, fake_mail):
    s = build(config, clock, fake_mail, travel_chat=lambda m, sch: {"ok": False, "error": "no_model"}, hub_call=FakeHub())
    s.set_settings({"travel.home_city": "Madrid"})
    yield s
    s.stop()


def test_trips_and_their_departures_are_listed(tsvc):
    tsvc.engine.ingest([tm.IBERIA])
    items = agenda(tsvc, days=90)
    (trip,) = [i for i in items if i["id"].startswith("phileas:trip:")]
    assert trip["start"] == "2026-11-12" and trip["end"] == "2026-11-15" and trip["all_day"] and trip["kind"] == "other"
    assert "/#/viaje/" in trip["url"]
    flights = [i for i in items if i["id"].startswith("phileas:segment:")]
    assert len(flights) == 2 and not flights[0]["all_day"]
    assert flights[0]["start"].startswith("2026-11-12T09:05:00") and "IB3166" in flights[0]["title"] and "MAD" in flights[0]["title"]
    assert [i["start"] for i in items] == sorted(i["start"] for i in items)


def test_a_cancelled_or_finished_trip_is_not_listed(tsvc, clock):
    tsvc.engine.ingest([tm.IBERIA])
    trip = tsvc.tstore.trips()[0]
    tsvc.tstore.update_trip(trip["id"], cancelled=True)
    assert agenda(tsvc, days=90) == []
    tsvc.tstore.update_trip(trip["id"], cancelled=False)
    clock.advance(60 * M.D)
    assert [i for i in agenda(tsvc, days=90)] == []


def test_the_travel_facet_off_hides_the_trips(tsvc):
    tsvc.engine.ingest([tm.IBERIA])
    tsvc.set_settings({"travel.enabled": "0"})
    assert [i for i in agenda(tsvc, days=90) if i["id"].startswith("phileas:trip")] == []


def test_the_agenda_route_answers_the_hub_and_needs_the_token(client):
    today = datetime.fromtimestamp(M.T0).date()
    client.svc.store.create_shipment(label="Monitor", carrier="ups", tracking_number="1ZA", status="in_transit",
                                     eta_likely=(today + timedelta(days=1)).isoformat())
    url = f"/api/family/agenda?from={today.isoformat()}&to={(today + timedelta(days=5)).isoformat()}"
    assert client.get(url).status_code == 401
    ok = client.get(url, headers=client.bearer)
    assert ok.status_code == 200
    body = ok.json()
    assert body["ok"] and [i["kind"] for i in body["items"]] == ["delivery"] and body["items"][0]["title"] == "Monitor"


def test_the_manifest_declares_the_agenda():
    manifest = json.loads((ROOT / "faustus-plugin.json").read_text(encoding="utf-8"))
    assert manifest["x-family"] == {"agenda": True}
