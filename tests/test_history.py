"""Old mail never makes an active parcel (deep scans too), the repair of parcels already stuck as active, surplus-food mail and price lines."""

from __future__ import annotations

import pytest

import mails as M
from conftest import tool
from mails import D, T0, msg
from phileas_hoard.mail import parse

DAYS = 86400.0


def ingest(svc, *messages):
    return svc.engine.ingest(list(messages))


def old_parcel_mails():
    """Shipping mail from long ago, as a scan with since_days=400 would return it."""
    return [
        msg("ali", T0 - 390 * D, "transaction@notice.aliexpress.com", "Tu pedido de AliExpress se ha enviado",
            "Tu pedido 8123456789012345 se ha enviado.\nNúmero de seguimiento: YT2600000000000011\nhttp://www.yuntrack.com/Track/Detail/YT2600000000000011"),
        M.amazon("blob", T0 - 380 * D, "enviado", "De Blob (Nintendo Switch)", "406-3333333-4444444", "TBBB222"),
        msg("ebay", T0 - 370 * D, "ebay@ebay.es", "Tu artículo de eBay se ha enviado", "Tu pedido se ha enviado con PostNL.\nNúmero de seguimiento: 3SABCD123456789\nPedido 12-34567-89012"),
        M.amazon("old-order", T0 - 360 * D, "pedido", "Libro de cocina", "406-5555555-6666666"),
    ]


def test_an_old_mail_found_by_a_deep_scan_goes_to_the_history(svc, clock):
    out = ingest(svc, *old_parcel_mails())
    assert out["shipping"] >= 3
    assert svc.store.shipments(archived=False, history_only=False, active=True) == []          # nothing active
    rows = svc.store.shipments(archived=None, history_only=None)
    assert rows and all(s["history_only"] for s in rows)
    assert not any(s["status"] not in ("delivered", "returned") and not s["archived"] for s in rows)
    assert svc.notifier.sent == []                                                             # and nobody was told


def test_a_deep_scan_through_the_tool_does_the_same(svc, fake_mail):
    svc.db.set_setting("mail.first_scan_done", "1")                                            # a deep scan after the first import
    fake_mail.messages = old_parcel_mails() + [M.PCS_SHIPPED]
    tool(svc, "mail_scan", since_days=400, query="envío")
    active = svc.store.shipments(archived=False, history_only=False, active=True)
    assert [s["merchant"] for s in active] == ["PCSpecialist"]                                  # only the fresh parcel stays live
    assert "shipment_new" in svc.notifier.types() and len([t for t in svc.notifier.types() if t == "shipment_new"]) == 1


def test_a_recent_mail_still_makes_an_active_parcel(svc):
    ingest(svc, M.PCS_SHIPPED, msg("fresh", T0 - 20 * D, "ebay@ebay.es", "Tu artículo de eBay se ha enviado",
                                     "Se ha enviado.\nNúmero de seguimiento: 3SABCD123456799\nPedido 12-34567-89099"))
    assert len(svc.store.shipments(archived=False, history_only=False, active=True)) == 2


def test_the_window_is_a_setting(svc):
    svc.set_settings({"mail.history_days": 10})
    ingest(svc, msg("mid", T0 - 20 * D, "ebay@ebay.es", "Tu artículo de eBay se ha enviado",
                    "Se ha enviado.\nNúmero de seguimiento: 3SABCD123456798\nPedido 12-34567-89098"))
    assert svc.store.shipments(archived=False, history_only=False, active=True) == []
    with pytest.raises(Exception):
        svc.set_settings({"mail.history_days": 0})


# ---------------------------------------------------------------------------------- the repair
LIVE_SIX = [  # label, carrier, status, merchant: what the deep scans left behind in Envíos
    ("AliExpress", "", "in_transit", "AliExpress"),
    ("De Blob (Nintendo Switch)", "amazon", "in_transit", "Amazon"),
    ("eBay", "postnl", "in_transit", "eBay"),
    ("Familiar = € 10.00", "", "ordered", "Familiar"),
    ("IberLibro.com · pedido 4455667", "cainiao", "unknown", "IberLibro.com"),
    ("Too Good To Go", "", "ordered", "Too Good To Go"),
]


@pytest.fixture
def stuck(svc, clock):
    ids = {}
    for i, (label, carrier, status, merchant) in enumerate(LIVE_SIX):
        old = T0 - (380 - 10 * i) * DAYS
        s = svc.store.create_shipment(label=label, merchant=merchant, carrier=carrier, status=status, source="mail", last_change_ts=old, status_ts=T0)
        svc.store.save_mail({"message_id": f"<old{i}@test>", "ts": old, "from_address": "x@example.test", "subject": label, "text": ""},
                            kind="shipping", score=5, facts={}, shipment_id=s["id"], state="linked")
        ids[label] = s["id"]
    pcs = svc.store.create_shipment(label="PCSpecialist", merchant="PCSpecialist", carrier="ups", status="in_transit", source="mail", last_change_ts=T0 - 2 * 3600)
    ids["PCSpecialist"] = pcs["id"]
    return ids


def test_repair_dry_run_lists_the_six_and_changes_nothing(svc, stuck):
    out = tool(svc, "shipments_history_repair")
    assert out["dry_run"] is True and out["count"] == 6 and out["window_days"] == 30
    assert [(s["label"], s["action"]) for s in sorted(out["shipments"], key=lambda s: s["label"])] == [
        ("AliExpress", "history, archived"), ("De Blob (Nintendo Switch)", "history, archived"), ("Familiar = € 10.00", "history, archived"),
        ("IberLibro.com · pedido 4455667", "history, archived"), ("Too Good To Go", "history, archived"), ("eBay", "history, archived")]
    assert all(s["days_idle"] > 300 for s in out["shipments"])
    assert len(svc.store.shipments(archived=False, history_only=False, active=True)) == 7             # untouched


def test_repair_moves_them_quietly_and_keeps_the_live_parcel(svc, stuck):
    out = tool(svc, "shipments_history_repair", dry_run=False)
    assert out["dry_run"] is False and out["count"] == 6
    active = svc.store.shipments(archived=False, history_only=False, active=True)
    assert [s["label"] for s in active] == ["PCSpecialist"]
    assert all(svc.store.shipment(stuck[label])["history_only"] for label, *_ in LIVE_SIX)
    assert svc.notifier.sent == []
    assert tool(svc, "shipments_history_repair")["count"] == 0                                         # idempotent


def test_repair_leaves_manual_and_recently_active_parcels(svc, stuck):
    manual = svc.store.create_shipment(label="Mine", source="manual", carrier="ups", status="in_transit", last_change_ts=T0 - 200 * DAYS)
    busy = svc.store.create_shipment(label="Slow boat", source="mail", carrier="cainiao", status="in_transit", last_change_ts=T0 - 200 * DAYS)
    svc.store.add_event(busy["id"], ts=T0 - 3 * DAYS, status="in_transit", description="Departed", location="", source="carrier", key="k1")
    out = tool(svc, "shipments_history_repair")
    assert out["count"] == 6 and {s["id"] for s in out["shipments"]}.isdisjoint({manual["id"], busy["id"]})


def test_repair_assumes_delivery_when_it_was_out_for_delivery(svc):
    s = svc.store.create_shipment(label="Almost", source="mail", carrier="ups", status="out_for_delivery", out_for_delivery_ts=T0 - 100 * DAYS,
                                  last_change_ts=T0 - 100 * DAYS)
    out = tool(svc, "shipments_history_repair", dry_run=False)
    assert out["shipments"][0]["action"] == "history, delivered (assumed)"
    row = svc.store.shipment(s["id"])
    assert row["status"] == "delivered" and row["delivered_assumed"] and row["history_only"]


def test_the_repair_runs_once_at_start(svc, stuck):
    svc.db.set_setting("housekeeping.history_repair", "")
    svc._housekeeping()
    assert [s["label"] for s in svc.store.shipments(archived=False, history_only=False, active=True)] == ["PCSpecialist"]
    assert svc.db.get_setting("housekeeping.history_repair") == "1"
    again = svc.store.create_shipment(label="Later", source="mail", status="in_transit", last_change_ts=T0 - 200 * DAYS)
    svc._housekeeping()                                                                                 # a flag says it already ran
    assert not svc.store.shipment(again["id"])["history_only"]


# ---------------------------------------------------------------------------------- surplus food and price lines
@pytest.mark.parametrize("sender,name,subject", [
    ("no-reply@toogoodtogo.com", "Too Good To Go", "Tu pedido de Sorpresa en Panadería Sol está confirmado"),
    ("hola@mail.tgtg-example.test", "Too Good To Go", "Recoge tu pedido hoy"),
    ("info@example.test", "Too Good To Go", "Pedido confirmado: tu Sorpresa se ha enviado"),
    ("no-reply@hellofresh.es", "HelloFresh", "Tu caja se ha enviado"),
])
def test_surplus_food_and_meal_apps_are_noise(sender, name, subject):
    facts = parse.analyze(msg("tg", T0 - D, sender, subject, "Gracias por tu pedido. Pedido confirmado 77881234. Tu caja está en camino.", name=name))
    assert facts.kind == "noise"


def test_surplus_food_mail_creates_no_parcel(svc):
    ingest(svc, msg("tg2", T0 - D, "no-reply@toogoodtogo.com", "Pedido confirmado", "Gracias por tu pedido 5566778. Recógelo hoy.", name="Too Good To Go"))
    assert svc.store.shipments(archived=None, history_only=None) == []


@pytest.mark.parametrize("line", ["Familiar = € 10.00", "Talla M x 2 = 20,00 €", "12,50 €", "€ 10.00", "Funda 9.99 EUR"])
def test_price_lines_are_prices(line):
    assert parse.has_price(line)


@pytest.mark.parametrize("line", ["Teclado mecánico 75%", "Cable USB-C 2 m", "De Blob (Nintendo Switch)"])
def test_product_names_are_not_prices(line):
    assert not parse.has_price(line)


def test_a_price_line_is_never_the_item_label():
    text = "Gracias por tu pedido.\n\nTeléfono de prueba 8 GB\n\nFamiliar = € 10.00\n\n10,00 €\n\nPedido 4455667"
    facts = parse.analyze(msg("fam", T0 - D, "pedidos@tienda-example.test", "Tu pedido se ha enviado", text))
    assert "=" not in facts.item and "€" not in facts.item
    only_price = "Gracias por tu pedido.\n\nFamiliar = € 10.00\n\n10,00 €\n\nPedido 4455667"
    assert "Familiar" not in parse.analyze(msg("fam2", T0 - D, "pedidos@tienda-example.test", "Tu pedido se ha enviado", only_price)).item
    assert parse.find_item('Pedido: "Familiar = € 10.00"', "", "") == ""
