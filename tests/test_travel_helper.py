"""The shared Faustus mail helper: HTML for reservation markup, and the travel words Phileas adds to its search."""

from __future__ import annotations

import email
import json

from phileas_hoard.hoard_link import mail_helper as helper
from phileas_hoard.mail.source import MailSource
from phileas_hoard.travel import extract

LD = json.dumps({"@context": "http://schema.org", "@type": "FlightReservation", "reservationNumber": "VKP3N7",
                 "reservationFor": {"@type": "Flight", "flightNumber": "123", "airline": {"@type": "Airline", "iataCode": "XX"},
                                    "departureAirport": {"@type": "Airport", "iataCode": "MAD"}, "arrivalAirport": {"@type": "Airport", "iataCode": "LIS"},
                                    "departureTime": "2026-11-12T09:05:00+01:00", "arrivalTime": "2026-11-12T09:55:00+00:00"}})


def raw(html: str, plain: str = "Reserva confirmada") -> bytes:
    return (f"From: Agencia <bookings@fly-example.test>\nTo: a@example.test\nSubject: Your flight booking\nMessage-ID: <x1@test>\n"
            f"Date: Mon, 02 Nov 2026 10:00:00 +0000\nMIME-Version: 1.0\nContent-Type: multipart/alternative; boundary=B\n\n"
            f"--B\nContent-Type: text/plain; charset=utf-8\n\n{plain}\n--B\nContent-Type: text/html; charset=utf-8\n\n{html}\n--B--\n").encode()


def test_reservation_markup_comes_back_as_html_and_is_readable():
    html = f'<html><head><script type="application/ld+json">{LD}</script></head><body><p>Reserva confirmada VKP3N7</p></body></html>'
    record = helper.message_to_record(email.message_from_bytes(raw(html)))
    assert "html" in record and "FlightReservation" in record["html"]
    assert "ld+json" not in record["text"] and "VKP3N7" in record["text"]
    drafts = extract.drafts_from_html(record["html"])
    assert drafts and drafts[0].from_code == "MAD" and drafts[0].to_code == "LIS"


def test_markup_with_template_slips_is_still_read():
    """Trailing commas and a CDATA wrapper are common in booking templates; the shared reader copes with both."""
    sloppy = LD[:-1] + ",}"
    html = f'<script type="application/ld+json">//<![CDATA[\n{sloppy}\n//]]></script>'
    drafts = extract.drafts_from_html(html)
    assert drafts and drafts[0].from_code == "MAD"


def test_plain_html_is_not_shipped_back():
    record = helper.message_to_record(email.message_from_bytes(raw("<html><body><p>Hola, tu pedido va en camino</p></body></html>")))
    assert "html" not in record


def scan_request(travel: bool) -> dict:
    """The request the mail source sends to the helper for one scan."""
    sent = {}

    def runner(request, timeout):
        sent.update(request)
        return {"ok": True, "accounts": [], "messages": []}

    MailSource(None, lambda k, d=None: "faustus" if k == "mail.source" else d, lambda k, v: None, runner=runner).scan(
        since_days=5, limit=5, skip=[], travel=travel)
    return sent


def test_travel_terms_are_searched_only_when_asked():
    plain, travel = scan_request(False), scan_request(True)
    assert plain["action"] == "scan" and "billete" not in plain["subject_terms"] and "enviado" in plain["subject_terms"]
    assert "billete" in travel["subject_terms"] and "enviado" in travel["subject_terms"]


def test_gmail_query_gets_the_travel_words():
    plain, travel = scan_request(False), scan_request(True)
    assert "itinerary" not in plain["gmail_query"] and "tracking number" in plain["gmail_query"]
    assert "itinerary" in travel["gmail_query"] and travel["gmail_query"].count('"') % 2 == 0


def test_hub_mail_is_asked_for_the_reservation_markup():
    class Hub:
        fields = None

        def available(self, timeout=1.0):
            return True

        def register_interest(self, spec, sphere=None, timeout=10.0):
            return {"ok": True}

        def messages(self, since_id=0, limit=100, full=True, interest=True, timeout=20.0, fields=None):
            Hub.fields = fields
            return {"ok": True, "messages": [], "last_id": since_id}

    MailSource(None, lambda k, d=None: d, lambda k, v: None, runner=lambda r, t: {"ok": True, "messages": []}, hub_mail=Hub()).scan(
        since_days=5, limit=5, skip=[], travel=True)
    assert "html" in Hub.fields
