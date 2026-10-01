"""Mail → shipments → statuses → estimates → notifications, end to end with fakes."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import mails as M
from conftest import tool


def ingest(svc, *messages, bootstrap=False):
    return svc.engine.ingest(list(messages), bootstrap=bootstrap)


def test_pcspecialist_order_then_ups_shipment_become_one_parcel(svc):
    ingest(svc, M.PCS_ORDER, M.PCS_SHIPPED)
    rows = svc.store.shipments(archived=None, history_only=None)
    assert len(rows) == 1
    s = rows[0]
    assert s["merchant"] == "PCSpecialist" and s["carrier"] == "ups" and s["tracking_number"] == M.UPS
    assert s["order_ref"] == "3400001" and s["status"] == "in_transit"
    assert s["promise_min_days"] == 2 and s["promise_max_days"] == 6 and s["promise_business"]
    assert s["tracking_url"].endswith(M.UPS)
    assert s["eta_from"] and s["eta_to"] and s["eta_likely"]
    sources = [b["source"] for b in s["eta_basis"]]
    assert "promise" in sources
    # notified: new shipment and "on its way"
    assert "shipment_new" in svc.notifier.types()


def test_amazon_order_shipped_out_for_delivery_track_one_package(svc, clock):
    order = "406-1111111-2222222"
    ingest(svc, M.amazon("a1", M.T0 - 2 * M.D, "pedido", "Cable de prueba", order, eta="Llega el viernes"),
           M.amazon("a2", M.T0 - 1 * M.D, "enviado", "Cable de prueba", order, "TAAA111", eta="Llega mañana"),
           M.amazon("a3", M.T0 - 1 * M.H, "reparto", "Cable de prueba", order, "TAAA111", eta="Llega hoy"))
    rows = svc.store.shipments(archived=None, history_only=None)
    assert len(rows) == 1
    s = rows[0]
    assert s["carrier"] == "amazon" and s["sub_ref"] == "TAAA111" and s["status"] == "out_for_delivery"
    assert s["item"].startswith("Cable de prueba")
    assert s["eta_likely"] == datetime.fromtimestamp(M.T0).date().isoformat()
    assert "out_for_delivery" in svc.notifier.types()
    # next day without news: delivered (assumed) by housekeeping
    clock.advance(M.D)
    svc.engine.housekeeping()
    s = svc.store.shipment(s["id"])
    assert s["status"] == "delivered" and s["delivered_assumed"]


def test_amazon_two_packages_of_one_order_stay_apart(svc):
    order = "406-3333333-4444444"
    ingest(svc, M.amazon("b1", M.T0 - 3 * M.D, "pedido", "Tarjeta gráfica", order),
           M.amazon("b2", M.T0 - 2 * M.D, "enviado", "Tarjeta gráfica", order, "TBBB111"),
           M.amazon("b3", M.T0 - 2 * M.D + 60, "enviado", "Tarjeta de expansión", order, "TBBB222"))
    rows = svc.store.shipments(archived=None, history_only=None)
    assert sorted(r["sub_ref"] for r in rows) == ["TBBB111", "TBBB222"]


def test_carrier_pickup_mail_attaches_to_the_parcel_it_announces(svc):
    ingest(svc, M.WALLAPOP_INPOST, M.INPOST_READY)
    rows = svc.store.shipments(archived=None, history_only=None)
    assert len(rows) == 1
    s = rows[0]
    assert s["carrier"] == "inpost" and s["status"] == "available_for_pickup"
    assert s["pickup_code"] == "123456" and "papelería de prueba" in s["pickup_place"]
    assert s["merchant"] == "Wallapop"


def test_survey_after_delivery_closes_the_pickup(svc, clock):
    ingest(svc, M.WALLAPOP_INPOST, M.INPOST_READY)
    clock.advance(21 * M.H)
    ingest(svc, M.INPOST_SURVEY)
    s = svc.store.shipments(archived=None, history_only=None, active=None)[0]
    assert s["status"] == "delivered"


def test_wallapop_correos_code_is_the_tracking_number_and_pickup_has_a_deadline(svc):
    ingest(svc, M.WALLAPOP)
    s = svc.store.shipments(archived=None, history_only=None)[0]
    assert s["tracking_number"] == M.CORREOS_CODE and s["carrier"] == "correos"
    assert s["status"] == "available_for_pickup"
    assert s["pickup_deadline"] == (datetime.fromtimestamp(M.WALLAPOP["ts"]).date() + timedelta(days=15)).isoformat()


def test_noise_creates_nothing(svc):
    out = ingest(svc, *M.NOISE)
    assert out["created"] == 0 and out["shipping"] == 0
    assert svc.store.shipments(archived=None, history_only=None) == []
    kinds = {m["message_id"]: m["kind"] for m in svc.store.mails(limit=10)}
    assert set(kinds.values()) == {"noise"}


def test_first_scan_builds_quiet_history(svc, fake_mail):
    fake_mail.messages = [M.GOOGLE_READY, M.GOOGLE_DELIVERED, M.PCS_ORDER, M.PCS_SHIPPED]
    out = svc.engine.scan_mail()
    assert out["ok"] and out["created"] == 2
    google = svc.store.by_number(M.DHL)
    assert google["history_only"] and google["status"] == "delivered"
    assert google["merchant_eta_first"] == "2026-08-21"
    pcs = svc.store.by_number(M.UPS)
    assert not pcs["history_only"]
    assert svc.notifier.sent == []              # the first import never notifies
    # second scan: nothing new, skip list used
    out = svc.engine.scan_mail()
    assert out["messages"] == 0 and fake_mail.calls[-1]["skip"] == 4


def test_history_feeds_similar_parcels(svc):
    # three past UPS parcels from the Netherlands that took 2, 3 and 3 delivery days
    for i, (shipped, delivered) in enumerate([(date(2026, 9, 1), date(2026, 9, 3)), (date(2026, 9, 8), date(2026, 9, 11)),
                                              (date(2026, 9, 15), date(2026, 9, 18))]):
        ts = lambda d: datetime(d.year, d.month, d.day, 12).timestamp()  # noqa: E731
        svc.store.create_shipment(label=f"past {i}", carrier="ups", origin_country="NL", tracking_number=f"1ZPAST{i}", status="delivered",
                                  shipped_ts=ts(shipped), delivered_ts=ts(delivered), history_only=True, merchant="PCSpecialist")
    ingest(svc, M.PCS_SHIPPED)
    s = svc.store.by_number(M.UPS)
    svc.store.update_shipment(s["id"], origin_country="NL")
    est = tool(svc, "eta_explain", shipment=M.UPS)["estimate"]
    assert est["similar"] and {r["days"] for r in est["similar"]} == {2, 3}
    assert any(b["source"] == "history" for b in est["basis"])
    # shipped Thursday 1 Oct: 2-3 delivery days → Monday 5 or Tuesday 6 (Madrid: no holiday)
    assert est["eta_from"] >= "2026-10-05" and est["eta_to"] <= "2026-10-07"


def test_status_never_goes_back_on_stale_mail(svc):
    ingest(svc, M.amazon("c1", M.T0 - 1 * M.H, "reparto", "Libro", "406-5555555-6666666", "TCCC1"))
    ingest(svc, M.amazon("c2", M.T0 - 20 * M.H, "enviado", "Libro", "406-5555555-6666666", "TCCC1"))
    s = svc.store.shipments(archived=None, history_only=None)[0]
    assert s["status"] == "out_for_delivery"
    assert len(svc.store.events(s["id"])) == 2


def test_paste_and_detect(svc):
    out = tool(svc, "mail_paste", subject="Tu pedido ha sido enviado", text=f"Hola, tu pedido ha sido enviado con GLS. Número de seguimiento: 12345678901")
    assert out["created"] == 1
    s = svc.store.shipments()[0]
    assert s["carrier"] == "gls" and s["tracking_number"] == "12345678901"
    found = tool(svc, "detect_numbers", text=f"Tracking: {M.UPS} y {M.S10}")["numbers"]
    assert {f["number"] for f in found} == {M.UPS, M.S10}


def test_first_import_still_links_order_and_shipping_mail(svc):
    ingest(svc, M.PCS_ORDER, M.PCS_SHIPPED, bootstrap=True)
    svc.engine.finish_bootstrap()
    rows = svc.store.shipments(archived=None, history_only=None)
    assert len(rows) == 1 and rows[0]["tracking_number"] == M.UPS and rows[0]["ordered_ts"]
    assert not rows[0]["history_only"]


def test_order_confirmation_sets_ordered(svc):
    ingest(svc, M.amazon("o1", M.T0 - M.H, "pedido", "Libro", "406-7777777-8888888"))
    assert svc.store.shipments()[0]["status"] == "ordered"
