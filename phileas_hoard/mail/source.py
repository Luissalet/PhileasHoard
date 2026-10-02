"""Where the engine's mail comes from: the family hub's mail gateway when it is ready, Faustus's own helper otherwise.

Both halves are the commons': ``hoard_link.fam_mail.MailRouter`` chooses the source (``mail.source``: ``auto``, ``hub`` or
``faustus``), registers Phileas's interest at the hub, keeps the watermark and claims what Phileas filed, and ``FaustusHelper`` runs
the vendored ``mail_helper.py`` under Faustus's own Python so the mail password never reaches Phileas. This class only holds what is
Phileas's: the subject words that shipping (and, with the travel facet on, booking) mail carries, the sender domains registered at the
hub, and the shape of the answers the engine expects. The mailbox is read-only on the other side (the helper opens folders with
EXAMINE and fetches with BODY.PEEK); the only write action is the notification mail of the notifier.

Messages that carry schema.org reservation markup arrive with their raw ``html`` (the helper adds it by itself; from the hub it is
asked for with ``fields=["html"]``), which the travel facet reads.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Optional

from ..hoard_link.fam_mail import FaustusHelper, MailRouter

SOURCE_MODES = ("auto", "hub", "faustus")      # mail.source: the family hub's mail gateway, Faustus's own helper, or the hub with a fallback
HUB_PAGE_MAX = 500
HUB_MAX_PAGES = 6                               # pages read in one scan: a long backlog is finished by the next scans
WATERMARK_KEY = "mail.hub.since_id"             # the hub's message id up to which Phileas has read
HUB_FIELDS = ["html", "images"]                 # what the gateway adds on request: reservation markup (travel) and image alt texts
SCAN_TIMEOUT_S = 180
CARRIER_DOMAINS_EXTRA = ("paack.co", "correosexpress.com", "zeleris.com", "cainiao.com", "dpd.com", "dpd.es", "fedex.com", "tnt.com", "postnl.nl")

# Words that shipping mail carries in its subject (ES, EN, FR, DE, IT, PT, NL).
SUBJECT_TERMS = [
    "enviado", "envío", "envio", "seguimiento", "pedido", "entrega", "reparto", "paquete", "recogida", "en camino",
    "shipped", "shipment", "tracking", "delivery", "delivered", "dispatched", "order", "parcel", "on its way", "out for",
    "expédié", "livraison", "colis", "versandt", "sendung", "lieferung", "spedito", "spedizione", "consegna",
    "enviada", "encomenda", "verzonden", "bezorging",
]
# Words that booking mail carries in its subject (ES, EN, FR, DE, IT, PT). Added when the travel facet is on.
TRAVEL_TERMS = [
    "reserva", "reservation", "booking", "billete", "ticket", "vuelo", "flight", "tarjeta de embarque", "boarding pass", "check-in",
    "itinerario", "itinerary", "localizador", "confirmación", "confirmation", "e-ticket", "viaje", "tren", "autobús", "ferry",
    "hotel", "alojamiento", "alquiler de coche", "car rental", "cancelación", "cancelled", "billet", "réservation", "buchung", "prenotazione",
    "voo", "bilhete",
]
GMAIL_QUERY = ("seguimiento OR enviado OR envío OR \"en camino\" OR reparto OR entrega OR paquete OR tracking OR shipped "
               "OR shipment OR dispatched OR \"out for delivery\" OR delivered OR expédié OR versandt OR spedito "
               "OR 1Z OR \"número de seguimiento\" OR \"tracking number\"")
TRAVEL_GMAIL = ("OR reserva OR reservation OR booking OR billete OR itinerary OR itinerario OR localizador OR \"tarjeta de embarque\" "
                "OR \"boarding pass\" OR vuelo OR flight OR hotel OR e-ticket")


class _RunnerHelper:
    """A helper that answers through ``runner(request, timeout) -> dict`` (tests use a fake mailbox)."""

    def __init__(self, runner: Callable[[dict[str, Any], int], dict[str, Any]]):
        self.runner = runner

    def available(self) -> bool:
        return True

    def faustus_dir(self) -> Optional[Path]:
        return None

    def run(self, action: str, payload: Optional[dict[str, Any]] = None, timeout: float = 0) -> dict[str, Any]:
        return self.runner({**(payload or {}), "action": action}, int(timeout))

    def status(self, refresh: bool = False) -> dict[str, Any]:
        return self.run("status", None, 60)


def interest_spec(travel: bool) -> dict[str, Any]:
    """What Phileas reads, as a hub interest: the subject words shipping mail carries (plus booking words when the travel facet is on) and
    the sender domains of the shops and carriers it knows."""
    from .parse import CARRIER_SENDERS, MERCHANTS
    domains = sorted({*MERCHANTS, *CARRIER_SENDERS, *CARRIER_DOMAINS_EXTRA})
    return {"subject_terms": list(SUBJECT_TERMS) + (list(TRAVEL_TERMS) if travel else []), "from_domains": domains}


def _normalise(message: dict[str, Any]) -> dict[str, Any]:
    """The shape the parser reads: lower-case ``from_address``, ``text`` and ``links`` always present."""
    message["from_address"] = str(message.get("from_address") or message.get("from_addr") or "").lower()
    message.setdefault("links", [])
    message.setdefault("text", "")
    return message


class MailSource:
    """Where the engine's mail comes from (see the module docstring); the messages reach the SAME parsing code either way.

    * a normal scan reads the hub from a stored watermark (``mail.hub.since_id``), oldest first, and only mail that matches the interest
      registered by :func:`interest_spec`; the watermark moves when the engine has stored the messages (:meth:`commit`);
    * a deep scan (an explicit ``since_days`` or a ``query``) goes to Faustus's helper in ``auto`` (it can look further back than the hub
      stored); in ``hub`` it re-reads the hub's stored mail from the start, filtered by the query, without touching the watermark;
    * after the engine files a message, :meth:`claim` tells the hub "this mail is mine" (a hint, never an error).

    ``helper`` (anything with ``available/faustus_dir/run/status``) or ``runner(request, timeout) -> dict`` are injectable (a fake mailbox); ``process_runner`` replaces ``subprocess.run`` under the helper;
    ``notifier`` (when it has a ``helper``) shares its helper, so the notifier and the mail scan share one status cache."""

    def __init__(self, notifier: Any = None, settings_get: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
                 settings_set: Optional[Callable[[str, str], None]] = None, *, runner: Optional[Callable[[dict[str, Any], int], dict[str, Any]]] = None,
                 process_runner: Optional[Callable[..., Any]] = None, hub_mail: Any = None, secret: Optional[Callable[[str], str]] = None,
                 helper: Any = None, clock: Callable[[], float] = time.time):
        self.get = settings_get or (lambda key, default=None: default)
        self.put = settings_set or (lambda key, value: None)
        self.clock = clock
        self._secret = secret or (lambda name: "")
        if helper is not None:
            self.helper: Any = helper
        elif runner is not None:
            self.helper = _RunnerHelper(runner)
        elif notifier is not None and getattr(notifier, "helper", None) is not None and process_runner is None:
            self.helper = notifier.helper
        else:
            self.helper = FaustusHelper(lambda: self.get("mail.faustus_dir", None) or self._secret("FAUSTUS_DIR"),
                                        owner=lambda: self.get("mail.faustus_owner", None), runner=process_runner,
                                        env_drop_prefixes=("PHILEAS_",), ask_hub=False, clock=clock)
        self._travel = False
        self.router = MailRouter(self.helper, source_getter=self.source_setting, interest=lambda criteria: interest_spec(self._travel),
                                 claim_kind="shipment", watermark_get=lambda: int(self.get(WATERMARK_KEY, "0") or 0),
                                 watermark_set=lambda value: self.put(WATERMARK_KEY, str(value)), page=HUB_PAGE_MAX, max_pages=HUB_MAX_PAGES,
                                 hub=hub_mail, clock=clock, deep_uses_helper=True)

    # ------------------------------------------------------------------ the pieces the engine and the API already use
    def faustus_dir(self) -> Optional[Path]:
        return self.helper.faustus_dir()

    def status(self, refresh: bool = False) -> dict[str, Any]:
        answer = dict(self.helper.status(refresh=refresh))
        answer["source"] = self.source_status()
        return answer

    # ------------------------------------------------------------------ the family hub's mail gateway
    def source_setting(self) -> str:
        """``mail.source``: ``auto`` (hub when its gateway is ready, else Faustus's helper), ``hub`` (only the hub), ``faustus``."""
        value = str(self.get("mail.source", "auto") or "auto").strip().lower()
        return value if value in SOURCE_MODES else "auto"

    def hub_up(self) -> bool:
        return self.router.hub_up()

    def source_status(self) -> dict[str, Any]:
        status = self.router.status()
        return {"setting": status["setting"], "effective": status["effective"], "hub_available": status["hub_available"],
                "interest_registered": status["interest_registered"], "hub_since_id": status["hub_since_id"]}

    def forget_interest(self) -> None:
        self.router.forget_interest()

    def ensure_interest(self, travel: bool, *, force: bool = False) -> dict[str, Any]:
        """Tell the hub which mail Phileas wants. Once per process, and again when the travel facet is switched or ``force`` says so."""
        self._travel = bool(travel)
        return self.router.ensure_interest({"subject_terms": interest_spec(travel)["subject_terms"]}, force=force)

    def commit(self) -> None:
        """Remember how far the hub's mail was read. The engine calls it once the messages of a scan are stored."""
        self.router.commit()

    def claim(self, hub_id: Any, kind: str, ref: str) -> None:
        """Tell the hub "this mail is mine" so it leaves the unowned tray. Errors are ignored: claims are hints."""
        if hub_id in (None, ""):
            return
        self.router.claim({"hub_id": hub_id}, ref, kind=kind)

    # ------------------------------------------------------------------ scanning
    def scan(self, *, since_days: int, limit: int, skip: list[str], query: str = "", travel: bool = False, deep: bool = False) -> dict[str, Any]:
        """``{ok, error, accounts, messages, via: "hub" | "faustus", more}``; a hub that cannot answer falls back to the helper in ``auto``."""
        self._travel = bool(travel)
        terms = interest_spec(travel)["subject_terms"]
        gmail = GMAIL_QUERY + (" " + TRAVEL_GMAIL if travel else "")
        answer = self.router.scan_ex(since_days=int(since_days), limit=int(limit), skip=skip, query=query, deep=deep, fields=HUB_FIELDS,
                                     subject_terms=terms, gmail_query=gmail)
        return {"ok": bool(answer.get("ok")), "error": str(answer.get("error") or ""), "accounts": answer.get("accounts") or [],
                "messages": [_normalise(m) for m in answer.get("messages") or [] if isinstance(m, dict)], "via": answer.get("source") or "",
                "more": bool(answer.get("more"))}
