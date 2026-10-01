"""Shipping mail classification and extraction."""

from __future__ import annotations

from datetime import date

import mails as M
from phileas_hoard import numbers
from phileas_hoard.mail import parse


def test_shipping_vs_noise():
    kinds = {m["message_id"]: parse.analyze(m).kind for m in [M.PCS_SHIPPED, M.WALLAPOP, M.SHOPIFY, M.INPOST_READY, *M.NOISE]}
    assert kinds[M.PCS_SHIPPED["message_id"]] == "shipping"
    assert kinds[M.WALLAPOP["message_id"]] == "shipping"
    assert kinds[M.SHOPIFY["message_id"]] == "shipping"
    assert kinds[M.INPOST_READY["message_id"]] == "shipping"
    assert all(kinds[n["message_id"]] == "noise" for n in M.NOISE)


def test_pcspecialist_facts():
    f = parse.analyze(M.PCS_SHIPPED)
    assert f.merchant == "PCSpecialist" and f.carrier == "ups" and f.status == "in_transit" and f.order_ref == "3400001"
    assert f.numbers[0]["number"] == M.UPS and f.promise_min_days == 2 and f.promise_max_days == 6 and f.promise_business


def test_amazon_facts_ignore_progress_bar_and_padding():
    f = parse.analyze(M.amazon("x", M.T0, "enviado", "Funda", "406-0000000-1111111", "TXYZ12", eta="Llega el domingo"))
    assert f.status == "in_transit" and f.order_ref == "406-0000000-1111111" and f.sub_ref == "TXYZ12"
    assert f.eta_from == "2026-10-04" and f.item == "Funda" and f.carrier == "amazon"
    f = parse.analyze(M.amazon("y", M.T0, "pedido", "Funda", "406-0000000-1111111", eta="Llega mañana"))
    assert f.status == "ordered" and f.eta_from == "2026-10-02"


def test_google_store_window_and_item():
    f = parse.analyze(M.GOOGLE_READY)
    assert f.status == "label_created" and f.carrier == "dhl" and f.numbers[0]["number"] == M.DHL
    assert (f.eta_from, f.eta_to) == ("2026-08-21", "2026-08-24")
    assert f.item == "Teléfono de prueba 8 GB"           # not the numeric ID right above the price
    assert f.order_ref == "GS.1111-2222-3333"


def test_eta_phrases():
    ref = date(2026, 10, 1)        # Thursday
    assert parse.find_eta("Llega hoy", ref)[:2] == (ref, ref)
    assert parse.find_eta("Llega el lunes", ref)[0] == date(2026, 10, 5)
    assert parse.find_eta("Entrega estimada: 7 de octubre", ref)[0] == date(2026, 10, 7)
    assert parse.find_eta("Estimated delivery: Oct 6 - Oct 8", ref)[:2] == (date(2026, 10, 6), date(2026, 10, 8))
    assert parse.find_eta("Recibirás tu pedido entre el 3 y el 5 de octubre", ref)[:2] == (date(2026, 10, 3), date(2026, 10, 5))
    assert parse.find_eta("Se entrega: 30 de dic - 2 de ene", date(2026, 12, 20))[:2] == (date(2026, 12, 30), date(2027, 1, 2))
    assert parse.find_eta("Nada que ver", ref)[0] is None


def test_promises():
    assert parse.find_promise("entrega en 24-48 horas") == (1.0, 2.0, False)
    assert parse.find_promise("entre 3 y 5 días laborables") == (3.0, 5.0, True)
    assert parse.find_promise("delivery in 2-4 business days") == (2.0, 4.0, True)


def test_pickup():
    code, place, deadline = parse.find_pickup(M.INPOST_READY["text"], date(2026, 10, 1))
    assert code == "123456" and place.startswith("papelería de prueba")
    code, place, deadline = parse.find_pickup(M.WALLAPOP["text"], date(2026, 10, 1))
    assert deadline == "2026-10-16"


def test_carrier_phrase_needs_a_real_phrase():
    assert parse.carrier_from_phrases("Se ha enviado su pedido con UPS.") == "ups"
    assert parse.carrier_from_phrases("Recibirá correos electrónicos de nosotros") == ""


def test_numbers_formats_and_links():
    assert numbers.ups_valid(M.UPS) and not numbers.ups_valid(M.UPS[:-1] + "0")
    assert numbers.s10_valid(M.S10) and numbers.classify(M.S10) == ("correos", 92)
    assert numbers.classify(M.DHL)[0] == "dhl" and numbers.classify(M.YUN)[0] == "yunexpress"
    wrapped = "http://x.r.eu-west-1.awstrack.me/L0/https:%2F%2Fwww.ups.com%2Ftrack%3Ftracknum=" + M.UPS + "/1/0102-abcdef-000000/xyz=473"
    found = numbers.from_url(wrapped)
    assert found and found.number == M.UPS and found.carrier == "ups"
    assert numbers.find("Llámanos al 917 890 111 o al 900 10 24 10", []) == []
    assert numbers.tracking_url("correos", M.CORREOS_CODE).endswith(M.CORREOS_CODE)


def test_prices_with_thousands():
    assert parse.find_price("y el precio total es 17.198,55 €, incluyendo entrega") == (17198.55, "EUR")
    assert parse.find_price("Total\n125.69€") == (125.69, "EUR")
    assert parse.find_price("sin importes") == (None, "")
