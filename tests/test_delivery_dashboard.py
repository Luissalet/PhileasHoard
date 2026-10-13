"""Delivery notes, consolidated notices and the manual receipt lifecycle."""
from datetime import date

from conftest import tool
from phileas_hoard.mail.parse import analyze, find_eta


def note(clock, mid="note"):
    return {"message_id": mid, "ts": clock(), "from_address": "orders@m.shop.example", "from_name": "Hardware Store",
            "subject": "Note added to your order from 09/10/2026",
            "text": "A note has been added to your order\nDPD Tracking number: 05700000001234\n"
                    "Order #51800\nProduct\nNetwork switch\nQuantity\n1\n958.00€\n"
                    "Estimated Arrival\n2026-10-20 - 2026-10-22",
            "links": [{"url": "https://www.dpdgroup.com/lv/mydpd/my-parcels/track?parcelNumber=05700000001234"}]}


def parcel(svc, clock, item, ref, sub=""):
    return svc.store.create_shipment(label=item, item=item, merchant="Amazon", order_ref=ref, sub_ref=sub,
                                     status="in_transit", shipped_ts=clock() - 3600, carrier="amazon")


def delivery(clock, items, ref="406-0000000-1111111", sub="CONSOLIDATED"):
    return {"message_id": "delivery", "ts": clock(), "from_address": "order-update@amazon.es", "from_name": "Amazon.es",
            "subject": f'Entregado: “{items[0]}...” y 2 productos más',
            "text": "¡Tu paquete se ha entregado!\nPedido n.º\n" + ref + "\n" + "\n".join(items),
            "links": [{"url": f"https://www.amazon.es/progress-tracker/package?orderId={ref}&shipmentId={sub}"}]}


def test_tracking_note_and_iso_window(clock):
    f = analyze(note(clock))
    assert f.kind == "shipping" and f.status == "label_created"
    assert f.carrier == "dpd" and f.numbers[0]["number"] == "05700000001234"
    assert f.item == "Network switch"
    assert (f.eta_from, f.eta_to) == ("2026-10-20", "2026-10-22")
    assert find_eta("Order 2026-10-09", date(2026, 10, 1))[:2] == (None, None)
    assert find_eta("Estimated arrival: 2026-02-30", date(2026, 10, 1))[:2] == (None, None)


def test_shop_order_with_colon_and_dispatch_with_domain_share_one_card(svc, clock):
    common = {"ts": clock(), "from_address": "updates@clientes.carrefour.com", "from_name": "Atención al Cliente", "links": []}
    ordered = {**common, "message_id": "shop-order", "subject": "Confirmación de pedido: 76510000", "text": "Hemos recibido tu pedido."}
    dispatched = {**common, "message_id": "shop-dispatch", "ts": clock() + 60,
                  "subject": "Tu pedido en Carrefour de Juego de cartas y 1 artículo más, ha sido enviado.",
                  "text": "Tu pedido de carrefour.es número 76510000 ha salido del almacén."}
    assert analyze(ordered).order_ref == analyze(dispatched).order_ref == "76510000"
    out = svc.engine.ingest([ordered, dispatched])
    assert out["created"] == 1 and out["linked"] == 1
    s = svc.dashboard()["active"][0]
    assert s["merchant"] == "Carrefour" and s["label"] == "Juego de cartas y 1 artículo más" and s["status"] == "in_transit"


def test_consolidated_delivery_closes_all_named_goods_only(svc, clock):
    names = ["Cable LAN Cat 6A rojo", "Estuche de viaje rigido", "Premium cable gris"]
    ships = [parcel(svc, clock, n, f"406-0000000-{i:07}", f"OLD{i}") for i, n in enumerate(names)]
    other = parcel(svc, clock, "Otra compra pendiente", "406-0000000-0000001", "OTHER")
    message = delivery(clock, names, ref=ships[1]["order_ref"], sub="NEW_ID")
    out = svc.engine.ingest([message])
    assert set(out["shipments"]) == {s["id"] for s in ships}
    assert out["created"] == 0
    assert [s["id"] for s in svc.dashboard()["active"]] == [other["id"]]
    assert all(svc.store.mails(shipment_id=s["id"])[0]["message_id"] == "delivery" for s in ships)
    assert all(svc.store.shipment(s["id"])["delivered_ts"] == clock() for s in ships)
    assert svc.engine.ingest([message], reprocess=True)["created"] == 0
    assert len(svc.store.shipments(archived=None, history_only=None)) == 4


def test_delivery_order_reference_without_tracking_is_shipping(clock):
    m = delivery(clock, ["Cable de red largo"])
    m["links"] = []
    assert analyze(m).kind == "shipping"


def test_delivery_named_goods_and_negative_delivery(clock):
    m = delivery(clock, ["Cable de red largo"])
    m.update(links=[], text="Tu paquete se ha entregado.")
    assert analyze(m).kind == "shipping"
    m["subject"] = "Tu paquete no se ha entregado"
    assert analyze(m).status == "failed_attempt"


def test_ambiguous_repeated_product_not_closed_by_title(svc, clock):
    a = parcel(svc, clock, "Cable ethernet repetido", "406-0000000-0000001", "A")
    b = parcel(svc, clock, "Cable ethernet repetido", "406-0000000-0000002", "B")
    m = delivery(clock, ["Cable ethernet repetido"], ref="406-0000000-0000001", sub="A")
    svc.engine.ingest([m])
    assert svc.store.shipment(a["id"])["status"] == "delivered"
    assert svc.store.shipment(b["id"])["status"] == "in_transit"


def test_named_specific_product_does_not_deliver_other_prefix(svc, clock):
    a = parcel(svc, clock, "Cable LAN Cat6A rojo", "406-0000000-0000001", "A")
    b = parcel(svc, clock, "Cable LAN Cat6A", "406-0000000-0000002", "B")
    m = delivery(clock, [a["item"]], ref=a["order_ref"], sub="NEW")
    svc.engine.ingest([m])
    assert svc.store.shipment(a["id"])["status"] == "delivered"
    assert svc.store.shipment(b["id"])["status"] == "in_transit"


def test_consolidated_delivery_naming_both_prefix_products_closes_both(svc, clock):
    a = parcel(svc, clock, "Cable LAN Cat6A rojo", "406-0000000-0000001", "A")
    b = parcel(svc, clock, "Cable LAN Cat6A", "406-0000000-0000002", "B")
    m = delivery(clock, [a["item"], b["item"]], ref=a["order_ref"], sub="NEW")
    svc.engine.ingest([m])
    assert svc.store.shipment(a["id"])["status"] == "delivered"
    assert svc.store.shipment(b["id"])["status"] == "delivered"


def test_received_clears_only_its_alerts_is_idempotent_and_reversible(svc, clock):
    a = parcel(svc, clock, "Tijeras de peluqueria", "406-0000000-0000001")
    b = parcel(svc, clock, "Cable de red largo", "406-0000000-0000002")
    for s in [a, b]:
        svc.store.add_notification(shipment_id=s["id"], type_="status_change", severity="low", title=s["label"], body="", results=[], dedupe=s["id"])
    out = tool(svc, "shipment_received", shipment=a["id"])
    received_at = out["shipment"]["received_ts"]
    assert out["changed"] and out["marked_seen"] == 1
    assert [n["shipment_id"] for n in svc.dashboard()["news"]] == [b["id"]]
    assert a["id"] not in {s["id"] for s in svc.dashboard()["active"]}
    assert a["id"] in {s["id"] for s in tool(svc, "shipments_list", filter="delivered")["shipments"]}
    clock.advance(60)
    assert not tool(svc, "shipment_received", shipment=a["id"])["changed"]
    assert svc.store.shipment(a["id"])["delivered_ts"] == received_at
    svc.engine.ingest([delivery(clock, [a["item"]], ref=a["order_ref"], sub="LATE")])
    assert svc.store.shipment(a["id"])["delivered_ts"] == received_at
    assert svc.engine.refresh(a["id"])["stopped"]
    assert not svc.engine.notify(a, "stale", "low", "stale", "", dedupe="late")
    tool(svc, "shipment_reopen", shipment=a["id"])
    assert svc.store.shipment(a["id"])["status"] == "in_transit"
    assert svc.store.shipment(a["id"])["extra"].get("received_ts") is None


def test_manual_legacy_update_uses_receipt_lifecycle(client):
    s = client.svc.store.create_shipment(label="Paquete de prueba", status="in_transit")
    r = client.post("/api/ui/call", json={"name": "shipment_update", "arguments": {"shipment": s["id"], "status": "delivered"}})
    assert r.status_code == 200 and r.json()["shipment"]["received_ts"]
    catalog = client.get("/api/agent/tools").json()["tools"]
    assert {"shipment_received", "shipment_reopen"} <= {t["name"] for t in catalog}


def test_reprocess_known_mail_repairs_existing_parcel_without_duplicates(svc, clock, fake_mail):
    s = parcel(svc, clock, "Cable de red largo", "406-0000000-1111111", "OLD")
    m = delivery(clock, [s["item"]], sub="NEW")
    svc.store.save_mail(m, kind="maybe", score=3, facts={}, shipment_id=None, state="new")
    fake_mail.messages = [m]
    svc.db.set_setting("mail.first_scan_done", "1")
    out = svc.engine.scan_mail(since_days=120, reprocess=True)
    assert out["created"] == 0 and svc.store.shipment(s["id"])["status"] == "delivered"
    assert fake_mail.calls[-1]["skip"] == 0
    assert fake_mail.calls[-1]["reprocess"] is True
    assert len(svc.store.shipments(archived=None, history_only=None)) == 1


def test_reconciliation_search_is_focused_ascii_and_preserves_explicit_queries():
    from phileas_hoard.mail.source import MailSource, RECONCILE_GMAIL, RECONCILE_TERMS
    calls = []
    source = MailSource(settings_get=lambda key, default=None: "faustus" if key == "mail.source" else default,
                        runner=lambda request, timeout: calls.append(request) or {"ok": True, "messages": [], "accounts": []})
    source.scan(since_days=120, limit=800, skip=[], deep=True, travel=True, reprocess=True)
    assert calls[-1]["gmail_query"] == RECONCILE_GMAIL and RECONCILE_GMAIL.isascii()
    assert calls[-1]["subject_terms"] == RECONCILE_TERMS
    assert all(term.isascii() for term in calls[-1]["subject_terms"])
    assert "reserva" not in calls[-1]["subject_terms"] and "order" not in calls[-1]["subject_terms"]
    source.scan(since_days=120, limit=800, skip=[], deep=True, query="Shop reference", reprocess=True)
    assert calls[-1]["query"] == "Shop reference"


def test_received_during_running_check_keeps_receipt(svc, clock, monkeypatch):
    from phileas_hoard.carriers.base import TrackResult
    s = svc.store.create_shipment(label="Paquete de prueba", tracking_number="05700000001234", carrier="dpd", status="in_transit")
    def track(*args, **kw):
        svc.engine.mark_received(s["id"])
        return TrackResult(ok=True, status="in_transit", source="test"), []
    monkeypatch.setattr(svc.carriers, "track", track)
    assert svc.engine.refresh(s["id"])["stopped"]
    saved = svc.store.shipment(s["id"])
    assert saved["status"] == "delivered" and saved["status_source"] == "manual"
    assert saved["extra"]["received_ts"] and saved["next_check_ts"] is None


def test_reprocessed_tracking_note_keeps_original_link_and_no_duplicate(svc, clock):
    m = note(clock)
    out = svc.engine.ingest([m])
    s = svc.store.shipment(out["shipments"][0])
    assert s["tracking_url"] == m["links"][0]["url"]
    assert svc.engine.ingest([m], reprocess=True)["created"] == 0
