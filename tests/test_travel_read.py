"""Reading travel mail: schema.org markup, the sender rules, changes and cancellations, the model pass."""

from __future__ import annotations

import json
from datetime import date

import pytest

import travel_mails as tm
from phileas_hoard.travel import airports, extract, llm, rules
from phileas_hoard.travel.analyze import analyze_travel
from phileas_hoard.travel.draft import SegmentDraft

REF = date(2026, 10, 1)

# sender -> (kind, segments, first number, first route, first dep, first dep tz, first arr, reference)
EXPECTED = {
    "iberia": ("flight", 2, "IB3166", ("MAD", "LIS"), "2026-11-12T09:05", "Europe/Madrid", "2026-11-12T09:55", "XK7Q2M"),
    "vueling": ("flight", 2, "VY8421", ("BCN", "PMI"), "2026-12-03T07:15", "Europe/Madrid", "2026-12-03T08:20", "ZP4T9K"),
    "air_europa": ("flight", 1, "UX1013", ("MAD", "BCN"), "2026-11-20T18:40", "Europe/Madrid", "2026-11-20T19:50", "QW3R7T"),
    "ryanair": ("flight", 2, "FR1234", ("DUB", "MAD"), "2026-11-06T06:20", "Europe/Dublin", "2026-11-06T09:55", "R8TJ2P"),
    "easyjet": ("flight", 2, "U28521", ("MAD", "LGW"), "2026-11-14T13:25", "Europe/Madrid", "2026-11-14T14:50", "K5N7PX2"),
    "volotea": ("flight", 1, "V71234", ("OVD", "PMI"), "2026-11-22T11:00", "Europe/Madrid", "2026-11-22T12:45", "WEN4Q8"),
    "binter": ("flight", 1, "NT123", ("LPA", "TFN"), "2026-12-05T08:15", "Atlantic/Canary", "2026-12-05T08:55", "BT5R2L"),
    "tap": ("flight", 1, "TP1021", ("LIS", "MAD"), "2026-12-10T07:20", "Europe/Lisbon", "2026-12-10T09:55", "HX6M3V"),
    "lufthansa": ("flight", 2, "LH1119", ("MAD", "FRA"), "2026-12-02T14:10", "Europe/Madrid", "2026-12-02T16:55", "JD8F4N"),
    "ba": ("flight", 1, "BA457", ("MAD", "LHR"), "2026-11-28T08:00", "Europe/Madrid", "2026-11-28T09:30", "PL9C3Z"),
    "air_france": ("flight", 1, "AF1301", ("MAD", "CDG"), "2026-11-26T17:45", "Europe/Madrid", "2026-11-26T19:50", "NB2K8Q"),
    "edreams": ("flight", 1, "FR9876", ("MAD", "FCO"), "2026-12-18T06:45", "Europe/Madrid", "2026-12-18T09:10", "T5R2W8"),
}
GROUND = {
    "renfe": ("train", 2, ("Madrid-Puerta de Atocha", "Barcelona-Sants"), "2026-11-20T07:00", "2026-11-20T09:45", "7HKQ2N"),
    "iryo": ("train", 1, ("Madrid Puerta de Atocha", "Sevilla Santa Justa"), "2026-12-08T10:10", "2026-12-08T12:35", "IR4T7B"),
    "ouigo": ("train", 1, ("Madrid Chamartín", "Valencia Joaquín Sorolla"), "2026-12-11T09:30", "2026-12-11T11:10", "QR2M8P"),
    "alsa": ("bus", 1, ("Madrid Estación Sur", "Oviedo"), "2026-11-24T23:00", "2026-11-25T05:45", "AL8X2K"),
    "flixbus": ("bus", 1, ("Madrid", "Valencia"), "2026-11-27T15:30", "2026-11-27T19:25", "4938275610"),
    "balearia": ("ferry", 1, ("Dénia", "Ibiza"), "2026-12-13T08:30", "2026-12-13T12:00", "BR7F2D"),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_airline_rules(name):
    kind, count, number, (a, b), dep, tz, arr, ref = EXPECTED[name]
    res = analyze_travel(tm.ALL_BY_SENDER[name], ref=REF)
    assert res.candidate and res.source == "rules"
    assert len(res.drafts) == count
    d = res.drafts[0]
    assert (d.kind, d.number, d.from_code, d.to_code, d.dep_local, d.dep_tz, d.arr_local, d.booking_ref) == (kind, number, a, b, dep, tz, arr, ref)
    assert d.from_city and d.to_city and d.from_country and d.carrier


@pytest.mark.parametrize("name", sorted(GROUND))
def test_ground_rules(name):
    kind, count, (a, b), dep, arr, ref = GROUND[name]
    res = analyze_travel(tm.ALL_BY_SENDER[name], ref=REF)
    assert res.candidate and len(res.drafts) == count
    d = res.drafts[0]
    assert (d.kind, d.from_name, d.to_name, d.dep_local, d.arr_local, d.booking_ref) == (kind, a, b, dep, arr, ref)
    assert d.dep_tz == "Europe/Madrid" and d.from_city


def test_train_details_per_leg():
    d1, d2 = analyze_travel(tm.RENFE, ref=REF).drafts
    assert (d1.number, d1.coach, d1.seat, d1.travel_class) == ("AVE3071", "5", "12A", "Turista")
    assert (d2.number, d2.coach, d2.seat) == ("AVE3092", "2", "8C")
    assert d1.price == 87.4 and d2.price is None          # the booking total sits on the first segment only


def test_flight_terminal_passengers_price_links():
    res = analyze_travel(tm.IBERIA, ref=REF)
    first, second = res.drafts
    assert first.terminal == "4" and not second.terminal
    assert first.passengers == ["Laura", "Pedro"]          # first names only
    assert first.price == 212.4 and first.currency == "EUR"
    kinds = [x["kind"] for x in first.links]
    assert kinds[:2] == ["checkin", "manage"] and all("unsubscribe" not in x["url"] for x in first.links)


def test_lodging_booking_and_rental():
    stay = analyze_travel(tm.BOOKING, ref=REF).drafts[0]
    assert stay.kind == "lodging" and stay.provider == "Hotel Alfama Vista" and stay.booking_ref == "3920481756"
    assert (stay.dep_local, stay.arr_local, stay.dep_tz) == ("2026-11-12T15:00", "2026-11-15T11:00", "Europe/Lisbon")
    assert stay.from_city == "Lisbon" and stay.from_country == "PT" and stay.price == 285.0
    home = analyze_travel(tm.AIRBNB, ref=REF).drafts[0]
    assert home.kind == "lodging" and home.from_city == "Barcelona" and home.dep_local == "2026-11-20T16:00"
    car = analyze_travel(tm.HERTZ, ref=REF).drafts[0]
    assert car.kind == "car" and car.provider == "Hertz" and car.from_name == "Lisboa Aeropuerto"
    assert (car.dep_local, car.arr_local) == ("2026-11-12T10:30", "2026-11-15T18:00")


def test_promotions_are_not_bookings():
    res = analyze_travel(tm.NOISE, ref=REF)
    assert not res.candidate and not res.drafts


def test_non_travel_mail_is_ignored():
    mail = tm.mail("x1", 1, "shop@example.test", "Tu pedido ha sido enviado", "Tu paquete sale mañana con UPS. Pedido 123456.")
    res = analyze_travel(mail, ref=REF)
    assert not res.candidate and not res.drafts


def test_change_and_cancel_are_read():
    change = analyze_travel(tm.VUELING_CHANGE, ref=REF)
    assert change.change == "change" and change.drafts[0].dep_local == "2026-12-03T08:00" and change.drafts[0].status == "confirmed"
    cancel = analyze_travel(tm.VUELING_CANCEL, ref=REF)
    assert cancel.change == "cancel" and cancel.drafts[0].status == "cancelled"
    assert cancel.drafts[0].booking_ref == "ZP4T9K"


def test_cancellation_policy_text_is_not_a_cancellation():
    res = analyze_travel(tm.VUELING, ref=REF)
    assert res.change == "new"
    mail = tm.mail("pol", 1, "info@vueling.com", "Confirmación de reserva ZP4T9K", "Puedes cancelar sin coste hasta 24 horas antes.\nCódigo de reserva: ZP4T9K\n"
                   "Vuelo VY8421 Barcelona (BCN) - Palma de Mallorca (PMI)  Salida 03/12/2026 07:15  Llegada 03/12/2026 08:20")
    assert analyze_travel(mail, ref=REF).change == "new"


# ------------------------------------------------------------------ schema.org
def test_jsonld_flight_reservation():
    res = analyze_travel(tm.JSONLD_FLIGHT, ref=REF)
    assert res.source == "schema" and len(res.drafts) == 1
    d = res.drafts[0]
    assert (d.kind, d.number, d.booking_ref, d.from_code, d.to_code) == ("flight", "XA1234", "VKP3N7", "MAD", "LIS")
    assert (d.dep_local, d.dep_tz, d.arr_local, d.arr_tz) == ("2026-12-20T10:00", "Europe/Madrid", "2026-12-20T10:55", "Europe/Lisbon")
    assert d.price == 120.5 and d.currency == "EUR" and d.passengers == ["Elena"]
    assert d.confidence >= 90 and d.source == "schema"


def test_jsonld_lodging_and_microdata_train():
    stay = analyze_travel(tm.JSONLD_LODGING, ref=REF).drafts[0]
    assert (stay.kind, stay.provider, stay.dep_local, stay.arr_local, stay.from_city) == ("lodging", "Casa Azul", "2026-12-20T15:00", "2026-12-23T11:00", "Lisbon")
    train = analyze_travel(tm.MICRODATA_TRAIN, ref=REF)
    assert train.source == "schema"
    d = train.drafts[0]
    assert (d.kind, d.number, d.booking_ref, d.from_name, d.to_name, d.dep_local, d.arr_local) == (
        "train", "9712", "TR8821K", "Madrid Atocha", "Sevilla Santa Justa", "2026-12-27T09:00", "2026-12-27T11:30")


def test_jsonld_nested_package_and_cancelled_status():
    flight = {"@type": "FlightReservation", "reservationNumber": "PKG123", "reservationStatus": "http://schema.org/ReservationCancelled",
              "reservationFor": {"@type": "Flight", "flightNumber": "77", "airline": {"iataCode": "KL"}, "departureAirport": {"iataCode": "AMS"},
                                 "arrivalAirport": {"iataCode": "MAD"}, "departureTime": "2026-12-01T07:00:00+01:00", "arrivalTime": "2026-12-01T09:40:00+01:00"}}
    html = '<script type="application/ld+json">' + json.dumps({"@context": "http://schema.org", "@type": "ReservationPackage", "reservationNumber": "PKG123",
                                                               "subReservation": [flight]}) + "</script>"
    mail = tm.mail("pk", 1, "x@trips.test", "Your trip", "trip", html=html)
    res = analyze_travel(mail, ref=REF)
    assert len(res.drafts) == 1 and res.drafts[0].status == "cancelled" and res.drafts[0].number == "KL77"
    assert res.drafts[0].dep_tz == "Europe/Amsterdam" and res.drafts[0].dep_local == "2026-12-01T07:00"


def test_schema_never_exposes_ticket_numbers():
    html = tm.JSONLD_FLIGHT["html"].replace('"reservationStatus"', '"ticketNumber": "0571234567890", "reservationStatus"')
    res = analyze_travel(tm.mail("t", 1, "b@x.test", "booking VKP3N7", "x", html=html), ref=REF)
    assert "0571234567890" not in json.dumps(res.to_dict())


# ------------------------------------------------------------------ model pass
def fake_chat(payload):
    def chat(messages, schema):
        return {"ok": True, "text": json.dumps(payload), "model": "test-model"}
    return chat


HARD = tm.mail("hard", 2, "agent@viajes-example.test", "Su viaje está listo",
               "Estimado cliente:\nSu reserva con localizador PQ7R2X incluye el vuelo de Sevilla a Bilbao.\n"
               "El vuelo sale el 3 de diciembre de 2026 a las 18:20 desde el aeropuerto de Sevilla (SVQ) y llega a Bilbao (BIO) a las 19:35.\nNumero de vuelo: V7 4521")


def test_model_pass_keeps_evidence_and_flags_source():
    seg = {"kind": "flight", "booking_ref": "PQ7R2X", "number": "V74521", "from_code": "SVQ", "to_code": "BIO", "dep_local": "2026-12-03T18:20",
           "arr_local": "2026-12-03T19:35", "change": "new", "evidence": ["El vuelo sale el 3 de diciembre de 2026 a las 18:20 desde el aeropuerto de Sevilla (SVQ)"]}
    out = llm.read_with_model(HARD, fake_chat({"segments": [seg]}))
    assert out["status"] == "ok" and out["model"] == "test-model" and len(out["drafts"]) == 1
    d = out["drafts"][0]
    assert d.source == "model" and d.confidence < 60 and d.evidence and d.from_code == "SVQ" and d.dep_tz == "Europe/Madrid" and d.booking_ref == "PQ7R2X"


def test_model_pass_drops_invented_segments():
    invented = {"kind": "flight", "from_code": "MAD", "to_code": "LHR", "dep_local": "2026-12-03T18:20", "evidence": ["Su vuelo a Londres sale a las 18:20 del Terminal 4"]}
    badtime = {"kind": "flight", "from_code": "SVQ", "to_code": "BIO", "dep_local": "tomorrow evening", "evidence": ["El vuelo sale el 3 de diciembre de 2026 a las 18:20"]}
    out = llm.read_with_model(HARD, fake_chat({"segments": [invented, badtime]}))
    assert out["status"] == "ok" and out["drafts"] == []


def test_model_pass_without_model_is_explicit():
    def none(messages, schema):
        return {"ok": False, "error": "no_model"}
    out = llm.read_with_model(HARD, none)
    assert out["status"] == "no_model" and out["drafts"] == []
    out = llm.read_with_model(HARD, lambda m, s: {"ok": True, "text": "not json"})
    assert out["status"] == "error"


def test_airport_table_and_cities():
    assert airports.lookup("MAD")["tz"] == "Europe/Madrid" and airports.lookup("LPA")["tz"] == "Atlantic/Canary"
    assert airports.city_of("Madrid Puerta de Atocha") == ("Madrid", "ES") and airports.city_of("Sevilla-Santa Justa")[0] == "Sevilla" and airports.city_of("Seville")[1] == "ES"
    assert airports.city_name("Lisbon") == "Lisboa" and airports.known("FCO") and not airports.known("XXX")


def test_segment_draft_round_trip_and_first_names():
    d = SegmentDraft(kind="flight", from_code="MAD", to_code="LIS", dep_local="2026-11-12T09:05", passengers=["Pérez/Ana Ms", "JOSE LUIS RUIZ"]).enrich()
    assert d.passengers == ["Ana", "Jose"] and d.dep_tz == "Europe/Madrid" and d.arr_tz == "Europe/Lisbon"
    assert SegmentDraft.from_dict(d.to_dict()) == d
