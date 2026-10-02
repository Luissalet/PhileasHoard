"""Synthetic travel mails shaped like the real ones. Names, booking references and flight numbers are invented."""

from __future__ import annotations

import json

from mails import D, H, T0, msg

TRIP_DAY = "2026-11-12"


def mail(mid: str, days_ago: float, sender: str, subject: str, text: str, html: str = "", name: str = "", links: list[dict] | None = None) -> dict:
    return msg(mid, T0 - days_ago * D, sender, subject, text, links, name, html=html)


LINKS = [{"url": "https://www.example-air.test/manage?ref=XK7Q2M", "label": "Gestionar mi reserva"},
         {"url": "https://www.example-air.test/checkin?ref=XK7Q2M", "label": "Check-in online"},
         {"url": "https://www.example-air.test/unsubscribe", "label": "Darse de baja"}]

IBERIA = mail("ib1", 20, "no-reply@iberia.com", "Tu reserva Iberia XK7Q2M está confirmada",
              "Tu reserva está confirmada\n\nLocalizador: XK7Q2M\n\nPasajeros: Laura GARCIA LOPEZ, Pedro GARCIA LOPEZ\n\nVuelo de ida\nIB3166\n"
              "Madrid (MAD) → Lisboa (LIS)\nSalida: 12 nov 2026 09:05\nLlegada: 12 nov 2026 09:55\nTerminal 4\n\n"
              "Vuelo de vuelta\nIB3167\nLisboa (LIS) → Madrid (MAD)\nSalida: 15 nov 2026 20:30\nLlegada: 15 nov 2026 23:15\n\n"
              "Precio total: 212,40 €\n", links=LINKS)

VUELING = mail("vy1", 18, "info@vueling.com", "Vueling: confirmación de tu reserva ZP4T9K",
               "Gracias por volar con nosotros.\nCódigo de reserva: ZP4T9K\nPasajero: Marta RUIZ\n\n"
               "Vuelo VY8421 Barcelona (BCN) - Palma de Mallorca (PMI)  Salida 03/12/2026 07:15  Llegada 03/12/2026 08:20\n"
               "Vuelo VY8422 Palma de Mallorca (PMI) - Barcelona (BCN)  Salida 06/12/2026 21:10  Llegada 06/12/2026 22:15\n\nTotal 98,30 EUR\n")

AIR_EUROPA = mail("ux1", 17, "reservas@aireuropa.com", "Confirmación de reserva Air Europa QW3R7T",
                  "Código de reserva: QW3R7T\n\nVuelo UX1013\nOrigen\nMadrid MAD\nDestino\nBarcelona BCN\nFecha de salida\n20 de noviembre de 2026\n"
                  "Hora de salida\n18:40\nHora de llegada\n19:50\n")

RYANAIR = mail("fr1", 16, "no-reply@ryanair.com", "Ryanair Travel Itinerary - Booking Reference: R8TJ2P",
               "Booking reference: R8TJ2P\nPassenger: Mr Sean MURPHY\n\nOutbound\nFR1234\nDublin (DUB) to Madrid (MAD)\n"
               "Departure: Fri 06 Nov 2026 06:20\nArrival: Fri 06 Nov 2026 09:55\n\nReturn\nFR1235\nMadrid (MAD) to Dublin (DUB)\n"
               "Departure: Mon 09 Nov 2026 10:35\nArrival: Mon 09 Nov 2026 12:15\n")

EASYJET = mail("u21", 15, "info@easyjet.com", "easyJet booking confirmation K5N7PX2",
               "Your booking reference is K5N7PX2\n\nU2 8521\nMadrid (MAD) -> London Gatwick (LGW)\nDeparture: 14 Nov 2026 13:25\nArrival: 14 Nov 2026 14:50\n\n"
               "U2 8522\nLondon Gatwick (LGW) -> Madrid (MAD)\nDeparture: 17 Nov 2026 15:30\nArrival: 17 Nov 2026 18:55\n")

VOLOTEA = mail("v71", 14, "noreply@volotea.com", "Volotea: tu reserva WEN4Q8",
               "Código de reserva WEN4Q8\nV7 1234\nAsturias (OVD) → Palma de Mallorca (PMI)\nSalida: 22 nov 2026 11:00\nLlegada: 22 nov 2026 12:45\n")

BINTER = mail("nt1", 13, "reservas@bintercanarias.com", "Binter - Reserva confirmada BT5R2L",
              "Localizador: BT5R2L\nVuelo NT123\nGran Canaria (LPA) → Tenerife Norte (TFN)\nSalida: 05 dic 2026 08:15\nLlegada: 05 dic 2026 08:55\n")

TAP = mail("tp1", 12, "noreply@flytap.com", "TAP Air Portugal - Booking confirmation HX6M3V",
           "Booking code: HX6M3V\nTP1021\nLisbon (LIS) → Madrid (MAD)\nDeparture: 10 Dec 2026 07:20\nArrival: 10 Dec 2026 09:55\n")

LUFTHANSA = mail("lh1", 11, "no-reply@lufthansa.com", "Your Lufthansa booking: confirmation JD8F4N",
                 "Booking code: JD8F4N\nLH1119\nMadrid (MAD) → Frankfurt (FRA)\nDeparture: 02 Dec 2026 14:10\nArrival: 02 Dec 2026 16:55\n"
                 "LH1120\nFrankfurt (FRA) → Madrid (MAD)\nDeparture: 05 Dec 2026 11:00\nArrival: 05 Dec 2026 14:00\n")

BA = mail("ba1", 10, "ba@email.britishairways.com", "British Airways e-ticket receipt PL9C3Z",
          "Booking reference: PL9C3Z\nBA 457\nMadrid (MAD) → London Heathrow (LHR)\nDeparture: 28 Nov 2026 08:00\nArrival: 28 Nov 2026 09:30\n")

AIR_FRANCE = mail("af1", 9, "noreply@airfrance.es", "Air France: confirmación de su billete NB2K8Q",
                  "Código de reserva: NB2K8Q\nAF1301\nMadrid (MAD) → París Charles de Gaulle (CDG)\nSalida: 26 nov 2026 17:45\nLlegada: 26 nov 2026 19:50\n")

# train / bus / ferry
RENFE = mail("rf1", 8, "venta@renfe.com", "Renfe: tu billete Madrid - Barcelona, localizador 7HKQ2N",
             "Gracias por tu compra\nLocalizador: 7HKQ2N\n\nIda\nOrigen: Madrid-Puerta de Atocha\nDestino: Barcelona-Sants\n"
             "Fecha: 20/11/2026\nHora de salida: 07:00\nHora de llegada: 09:45\nTren AVE 3071\nCoche 5 Plaza 12A\nClase Turista\n\n"
             "Vuelta\nOrigen: Barcelona-Sants\nDestino: Madrid-Puerta de Atocha\nFecha: 22/11/2026\nHora de salida: 19:15\nHora de llegada: 21:55\n"
             "Tren AVE 3092\nCoche 2 Plaza 8C\n\nPrecio total: 87,40 €\n")

IRYO = mail("iy1", 8, "no-reply@iryo.eu", "Tu viaje con iryo: reserva IR4T7B",
            "Localizador: IR4T7B\nMadrid Puerta de Atocha → Sevilla Santa Justa\nSalida: 08 dic 2026 10:10\nLlegada: 08 dic 2026 12:35\n")

OUIGO = mail("ou1", 7, "info@ouigo.com", "OUIGO - Confirmación de tu reserva QR2M8P",
             "Número de reserva: QR2M8P\nOrigen: Madrid Chamartín\nDestino: Valencia Joaquín Sorolla\nFecha: 11/12/2026\nSalida: 09:30\nLlegada: 11:10\n")

ALSA = mail("al1", 7, "no-reply@alsa.es", "Alsa: tu billete de autobús Madrid - Oviedo",
            "Localizador: AL8X2K\nOrigen: Madrid Estación Sur\nDestino: Oviedo\nFecha de salida: 24/11/2026\nHora de salida: 23:00\nHora de llegada: 05:45\n")

FLIXBUS = mail("fx1", 6, "booking@flixbus.com", "Tu reserva de FlixBus se ha confirmado",
               "Número de reserva: 4938275610\n\nIda\nMadrid → Valencia\n27 nov 2026\nSalida 15:30\nLlegada 19:25\n")

BALEARIA = mail("bl1", 6, "reservas@balearia.com", "Baleària: confirmación de tu reserva BR7F2D",
                "Localizador: BR7F2D\nOrigen: Dénia\nDestino: Ibiza\nFecha: 13/12/2026\nSalida: 08:30\nLlegada: 12:00\n")

# stays, rentals, agencies
BOOKING = mail("bk1", 5, "customer.service@booking.com", "Reserva confirmada en Hotel Alfama Vista, Lisboa",
               "Tu reserva está confirmada\nNúmero de reserva: 3920481756\n\nAlojamiento: Hotel Alfama Vista\n"
               "Dirección: Rua das Escolas 12, 1100-001 Lisboa, Portugal\nCheck-in: 12 nov 2026 desde las 15:00\nCheck-out: 15 nov 2026 hasta las 11:00\n"
               "3 noches\nPrecio total: 285,00 €\n", links=[{"url": "https://secure.example-hotels.test/mytrip?b=3920481756", "label": "Ver reserva"}])

AIRBNB = mail("ab1", 5, "automated@airbnb.com", "Reserva confirmada: Apartamento luminoso en Gràcia",
              "Tu reserva está confirmada\nCódigo de confirmación: HMAB3KQ7ZP\nAlojamiento: Apartamento luminoso en Gràcia\n"
              "Dirección: Carrer de Verdi 30, 08012 Barcelona, España\nLlegada: 20 nov 2026 desde las 16:00\nSalida: 22 nov 2026 antes de las 11:00\n")

HERTZ = mail("hz1", 4, "reservations@hertz.com", "Hertz: confirmación de alquiler de coche",
             "Número de confirmación: Z4Y8R2K9\nAlquiler de coche\nRecogida: 12 nov 2026 10:30\nLugar de recogida: Lisboa Aeropuerto\n"
             "Devolución: 15 nov 2026 18:00\nLugar de devolución: Lisboa Aeropuerto\nVehículo: Fiat 500 o similar\n")

EDREAMS = mail("ed1", 4, "noreply@edreams.com", "Tu viaje a Roma está confirmado - eDreams T5R2W8",
               "Código de reserva: T5R2W8\nVuelo FR9876\nMadrid (MAD) → Roma Fiumicino (FCO)\nSalida: 18 dic 2026 06:45\nLlegada: 18 dic 2026 09:10\n")

# changes and cancellations
VUELING_CHANGE = mail("vy2", 2, "info@vueling.com", "Cambio de horario en tu vuelo VY8421",
                      "Tu vuelo ha sufrido un cambio de horario.\nCódigo de reserva: ZP4T9K\n\n"
                      "Vuelo VY8421 Barcelona (BCN) - Palma de Mallorca (PMI)  Salida 03/12/2026 08:00  Llegada 03/12/2026 09:05\n")
VUELING_CANCEL = mail("vy3", 1, "info@vueling.com", "Vuelo cancelado VY8422",
                      "Lamentamos informarte de que tu vuelo ha sido cancelado.\nCódigo de reserva: ZP4T9K\n\n"
                      "Vuelo VY8422 Palma de Mallorca (PMI) - Barcelona (BCN)  Salida 06/12/2026 21:10  Llegada 06/12/2026 22:15\n"
                      "Puedes cancelar sin coste hasta 24 horas antes.\n")

# schema.org
def _jsonld(data: dict) -> str:
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body><p>Reserva</p></body></html>'


JSONLD_FLIGHT = mail("js1", 3, "bookings@fly-example.test", "Your flight booking VKP3N7",
                     "Your flight booking VKP3N7. Madrid to Lisbon.",
                     html=_jsonld({"@context": "http://schema.org", "@type": "FlightReservation", "reservationNumber": "VKP3N7",
                                   "reservationStatus": "http://schema.org/Confirmed",
                                   "underName": {"@type": "Person", "name": "Elena Sanz"},
                                   "reservationFor": {"@type": "Flight", "flightNumber": "1234", "airline": {"@type": "Airline", "name": "Example Air", "iataCode": "XA"},
                                                      "departureAirport": {"@type": "Airport", "iataCode": "MAD", "name": "Adolfo Suarez Madrid-Barajas"},
                                                      "departureTime": "2026-12-20T10:00:00+01:00",
                                                      "arrivalAirport": {"@type": "Airport", "iataCode": "LIS"},
                                                      "arrivalTime": "2026-12-20T10:55:00+00:00"},
                                   "reservationFor_note": "invented",
                                   "url": "https://www.example-air.test/manage?ref=VKP3N7", "totalPrice": "120.50", "priceCurrency": "EUR"}))

JSONLD_LODGING = mail("js2", 3, "stay@hotels-example.test", "Booking confirmed",
                      "Your stay is confirmed.",
                      html=_jsonld({"@context": "http://schema.org", "@type": "LodgingReservation", "reservationNumber": "LDG4821",
                                    "reservationFor": {"@type": "LodgingBusiness", "name": "Casa Azul",
                                                       "address": {"@type": "PostalAddress", "streetAddress": "Rua Augusta 5", "addressLocality": "Lisboa", "addressCountry": "PT"}},
                                    "checkinTime": "2026-12-20T15:00:00", "checkoutTime": "2026-12-23T11:00:00"}))

MICRODATA_TRAIN = mail("mi1", 3, "tickets@rail-example.test", "Your train ticket",
                       "Your train ticket.",
                       html='<html><body><div itemscope itemtype="http://schema.org/TrainReservation"><meta itemprop="reservationNumber" content="TR8821K"/>'
                            '<div itemprop="reservationFor" itemscope itemtype="http://schema.org/TrainTrip"><meta itemprop="trainNumber" content="9712"/>'
                            '<div itemprop="departureStation" itemscope itemtype="http://schema.org/TrainStation"><meta itemprop="name" content="Madrid Atocha"/></div>'
                            '<meta itemprop="departureTime" content="2026-12-27T09:00:00+01:00"/>'
                            '<div itemprop="arrivalStation" itemscope itemtype="http://schema.org/TrainStation"><meta itemprop="name" content="Sevilla Santa Justa"/></div>'
                            '<meta itemprop="arrivalTime" content="2026-12-27T11:30:00+01:00"/></div></div></body></html>')

NOISE = mail("nz1", 2, "news@vueling.com", "Ofertas de invierno desde 19 euros",
             "Descubre nuestras ofertas. Vuela a Roma, París o Londres con descuento. Reserva ya tu próximo viaje.")

ALL_BY_SENDER = {"iberia": IBERIA, "vueling": VUELING, "air_europa": AIR_EUROPA, "ryanair": RYANAIR, "easyjet": EASYJET, "volotea": VOLOTEA,
                 "binter": BINTER, "tap": TAP, "lufthansa": LUFTHANSA, "ba": BA, "air_france": AIR_FRANCE, "renfe": RENFE, "iryo": IRYO,
                 "ouigo": OUIGO, "alsa": ALSA, "flixbus": FLIXBUS, "balearia": BALEARIA, "booking": BOOKING, "airbnb": AIRBNB, "hertz": HERTZ,
                 "edreams": EDREAMS}
