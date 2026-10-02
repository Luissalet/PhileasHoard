"""Only mail with real booking evidence reaches travel or its review list: marketing, notices and event tickets stay out."""

from __future__ import annotations

import json

import pytest

import travel_mails as tm
from conftest import FakeHub, build, tool
from phileas_hoard.services import GATE_VERSION
from phileas_hoard.travel.analyze import analyze_travel

OFFER = "Oferta válida hasta el 15 nov 2026 a las 23:59. Madrid → Dublín desde 19,99 €. Consulta las condiciones."

MARKETING = [
    tm.mail("m1", 3, "news@ryanair.com", "How could AI make travel easier? Tell Ryanair", "Tell us what you think. It takes two minutes.\nBooking a flight should be simple."),
    tm.mail("m2", 3, "ofertas@ryanair.com", "Vuela a Shannon y déjate llevar por la costa oeste de Irlanda", OFFER),
    tm.mail("m3", 3, "info@vueling.com", "No esperes para reservar tu próximo viaje ⏰", "Reserva ya tu vuelo con descuento.\n" + OFFER),
    tm.mail("m4", 3, "info@vueling.com", "Hace tiempo desde tu último vuelo ✈️", "Te echamos de menos, Luis. Vuela de nuevo con nosotros.\nBarcelona (BCN) → Roma (FCO) 10 dic 2026 desde 24 €"),
    tm.mail("m5", 3, "promo@iberia.com", "Luis, solo quedan 6 días: consigue hasta € 100 de reembolso", "Cobra tu reembolso antes del 30 nov 2026 23:59."),
    tm.mail("m6", 3, "club@iberia.com", "¡Luis, has desbloqueado un premio!", "Tus puntos Avios te dan un premio. Canjéalo ya."),
    tm.mail("m7", 3, "ofertas@vueling.com", "FINALIZA HOY A MEDIANOCHE", "Última hora: vuelos desde 19 € hasta las 23:59 de hoy."),
    tm.mail("m8", 3, "ofertas@vueling.com", "¡Esta es tu última oportunidad!", "Reserva antes del 20 nov 2026 a las 10:00 con un 20% de descuento."),
    tm.mail("m9", 3, "ofertas@vueling.com", "¡No te lo pierdas!", "Escapadas de otoño. Madrid - Lisboa desde 29 €."),
    tm.mail("m10", 3, "no-reply@ryanair.com", "Actualizaciones de tus preferencias de comunicación", "Gestiona tus preferencias de comunicación. Darse de baja."),
    tm.mail("m11", 3, "email@mail.booking.com", "Luis, vive más experiencias con tus ventajas Genius ✨", "Nivel Genius 2. Ahorra un 10% en tu próxima reserva. Reservas en Lisboa 12 nov 2026."),
    tm.mail("m12", 3, "no-reply@ryanair.com", "Actualización importante para todos los pasajeros", "Estimado pasajero: cambiamos nuestras normas de equipaje de mano a partir del 1 dic 2026."),
]
CINEMA = tm.mail("c1", 3, "entradas@cines-example.test", "TUS ENTRADAS Y CONFIRMACION DE PRODUCTOS DE BAR",
                 "Gracias por tu compra.\nReferencia de reserva: 48213977\nPelícula: La noche larga\nCine Callao, Madrid\nSesión: 14 nov 2026 20:30\nButacas: F7, F8\nProductos de bar: 1 menú")
BOARDING = tm.mail("bp1", 1, "info@vueling.com", "Tu tarjeta de embarque VY8421",
                   "Tarjeta de embarque\nLocalizador: ZP4T9K\nPasajero: Marta RUIZ\nVuelo VY8421 Barcelona (BCN) - Palma de Mallorca (PMI)  Salida 03/12/2026 07:15  Llegada 03/12/2026 08:20\nPuerta B12 Asiento 14C")


def event_html(venue_city: str) -> str:
    data = {"@context": "http://schema.org", "@type": "EventReservation", "reservationNumber": "EV55231",
            "reservationFor": {"@type": "Event", "name": "Concierto de invierno", "startDate": "2026-12-05T20:30:00",
                               "location": {"@type": "Place", "name": "Auditorio Central", "address": {"@type": "PostalAddress", "streetAddress": "Calle Mayor 1", "addressLocality": venue_city}}}}
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body><p>Entradas</p></body></html>'


@pytest.fixture
def tsvc(config, clock, fake_mail):
    s = build(config, clock, fake_mail, hub_call=FakeHub(), travel_chat=lambda m, sc: {"ok": False, "error": "no_model"})
    s.set_settings({"travel.home_city": "Madrid"})
    yield s
    s.stop()


@pytest.mark.parametrize("mail", MARKETING, ids=lambda m: m["subject"][:30])
def test_marketing_and_notices_are_not_travel(mail):
    facts = analyze_travel(mail)
    assert not facts.candidate and not facts.drafts


def test_marketing_never_reaches_the_review_list(tsvc):
    out = tsvc.engine.ingest(list(MARKETING))
    assert out["travel"] == 0
    assert tsvc.travel.mails_list("all") == []
    assert not tsvc.tstore.segments() and not tsvc.travel.trips_list("all")
    again = tsvc.engine.ingest(list(MARKETING))            # the same ids are never listed again
    assert again["travel"] == 0 and tsvc.travel.mails_list("all") == []


def test_event_tickets_in_the_home_city_are_not_travel(tsvc):
    assert not analyze_travel(CINEMA).candidate
    assert tsvc.engine.ingest([CINEMA])["travel"] == 0 and tsvc.travel.mails_list("all") == []
    home = tm.mail("e1", 3, "tickets@events-example.test", "Tus entradas", "Entradas confirmadas.", html=event_html("Madrid"))
    assert analyze_travel(home).candidate                     # the markup is a real reservation ...
    assert tsvc.engine.ingest([home])["travel"] == 0         # ... but one in the home city is not travel
    assert not tsvc.tstore.segments()


def test_an_event_away_from_home_is_kept(tsvc):
    tsvc.set_settings({"travel.kinds": "flight,train,bus,ferry,car,lodging,event"})
    away = tm.mail("e2", 3, "tickets@events-example.test", "Tus entradas", "Entradas confirmadas.", html=event_html("Sevilla"))
    assert tsvc.engine.ingest([away])["travel"] == 1
    seg = tsvc.tstore.segments()[0]
    assert seg["kind"] == "event" and seg["start_date"] == "2026-12-05"


def test_an_event_pasted_by_hand_is_part_of_the_trip(tsvc):
    out = tsvc.travel.paste(subject="Entradas", text="Entradas", html=event_html("Madrid"))
    assert out["created"] == 1


def test_real_bookings_still_pass(tsvc):
    for m in (tm.IBERIA, tm.VUELING, tm.RENFE, tm.BOOKING, tm.HARD, tm.JSONLD_FLIGHT, tm.MICRODATA_TRAIN):
        assert analyze_travel(m).candidate, m["subject"]
    out = tsvc.engine.ingest([tm.IBERIA, tm.BOOKING])
    assert out["travel"] == 2 and len(tsvc.tstore.segments()) == 3


def test_a_boarding_pass_with_a_locator_and_flight_creates_a_segment(tsvc):
    facts = analyze_travel(BOARDING)
    assert facts.candidate and facts.ref == "ZP4T9K" and facts.drafts
    assert tsvc.engine.ingest([BOARDING])["travel"] == 1
    seg = tsvc.tstore.segments()[0]
    assert seg["number"] == "VY8421" and seg["booking_ref"] == "ZP4T9K" and seg["from_code"] == "BCN"


def test_a_locator_without_anything_to_travel_is_not_enough():
    mail = tm.mail("x1", 2, "info@vueling.com", "Tu reserva ZP4T9K", "Gracias por tu reserva.\nCódigo de reserva: ZP4T9K\nAcepta las nuevas condiciones.")
    assert not analyze_travel(mail).candidate


def test_a_cancellation_with_a_locator_still_passes():
    mail = tm.mail("x2", 2, "info@vueling.com", "Reserva cancelada ZP4T9K", "Hemos cancelado tu reserva.\nCódigo de reserva: ZP4T9K")
    assert analyze_travel(mail).candidate


def test_the_review_list_is_cleaned_once_on_start(tsvc):
    st = tsvc.store
    for m in MARKETING + [CINEMA]:
        st.save_mail(m, kind="travel", score=70, facts={"candidate": True, "text": m["text"], "drafts": []}, shipment_id=None, state="new")
    tsvc.engine.ingest([tm.HARD])                                                # a mail that does carry evidence waits for review
    pasted = tm.mail("p1", 1, "", "Pegado", "algo")
    pasted["message_id"] = "<pasted-abc123@phileas>"
    st.save_mail(pasted, kind="travel", score=0, facts={"text": "algo", "drafts": []}, shipment_id=None, state="new")
    assert len(tsvc.travel.mails_list("new")) == len(MARKETING) + 3
    tsvc.db.set_setting("travel.review_gate", "")
    tsvc._housekeeping()
    left = {m["message_id"] for m in tsvc.travel.mails_list("new")}
    assert left == {tm.HARD["message_id"], "<pasted-abc123@phileas>"}
    assert tsvc.db.get_setting("travel.review_gate") == GATE_VERSION
    row = st.mail(MARKETING[0]["message_id"])
    assert row["kind"] == "noise" and row["state"] == "skipped"
    assert tsvc.engine.ingest(list(MARKETING))["travel"] == 0                    # known ids are skipped


def test_recheck_is_a_tool(tsvc):
    st = tsvc.store
    st.save_mail(MARKETING[1], kind="travel", score=70, facts={"text": MARKETING[1]["text"], "drafts": []}, shipment_id=None, state="new")
    out = tool(tsvc, "travel_mail_recheck")
    assert out["dropped"] == 1 and tool(tsvc, "travel_mail_list", state="new")["mails"] == []
