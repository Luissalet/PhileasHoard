"""The Faustus mail helper: HTML for reservation markup, and travel subjects in the search. Stdlib-only, loaded by path."""

from __future__ import annotations

import email
import importlib.util
import json
from pathlib import Path

from phileas_hoard.mail.source import FaustusMail
from phileas_hoard.travel import extract

HELPER = Path(__file__).resolve().parent.parent / "phileas_hoard" / "mail" / "faustus_mail.py"
spec = importlib.util.spec_from_file_location("faustus_mail_helper", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

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


def test_plain_html_is_not_shipped_back():
    record = helper.message_to_record(email.message_from_bytes(raw("<html><body><p>Hola, tu pedido va en camino</p></body></html>")))
    assert "html" not in record


class Conn:
    def __init__(self):
        self.searches: list[tuple] = []

    def uid(self, command, _charset, *criteria):
        self.searches.append(criteria)
        return "OK", [b""]


def test_travel_terms_are_searched_only_when_asked():
    plain, travel = Conn(), Conn()
    helper._search(plain, "imap.example.test", 30, "")
    helper._search(travel, "imap.example.test", 30, "", travel=True)
    subjects = lambda c: {x[3].strip('"') for x in c.searches if len(x) > 3 and x[2] == "SUBJECT"}
    assert "billete" not in subjects(plain) and "billete" in subjects(travel) and "enviado" in subjects(travel)


def test_gmail_query_gets_the_travel_words():
    seen = []

    class G(Conn):
        def uid(self, command, _charset, *criteria):
            seen.append(criteria)
            return "OK", [b"1"]
    helper._search(G(), "imap.gmail.com", 30, "", travel=True)
    assert "itinerary" in seen[0][1] and "tracking number" in seen[0][1] and seen[0][1].count("(") == seen[0][1].count(")")


def test_source_passes_the_travel_flag():
    sent = {}

    class Done:
        stdout, returncode = '{"ok": true, "messages": []}', 0

    def runner(cmd, input="", **kw):
        sent.update(json.loads(input))
        return Done()
    root = Path(__file__).parent
    src = FaustusMail(lambda k, d="": "", lambda k: "", runner=runner)
    src.faustus_dir = lambda: root
    src.python_of = staticmethod(lambda r: "python")
    src.scan(since_days=5, limit=5, skip=[], travel=True)
    assert sent["travel"] is True and sent["action"] == "scan"
