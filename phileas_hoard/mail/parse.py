"""Shipping mail → structured facts: is it about a parcel, which one, what happened, when it should arrive.

Rules only (no model): the sender, the subject, the first lines of the body, tracking numbers and links.
``analyze(message)`` returns a ``MailFacts`` with a ``kind``:

* ``shipping`` — about a physical parcel (order confirmation of goods, shipped, out for delivery, delivered, pickup…)
* ``maybe``    — mentions orders or delivery but the evidence is thin; shown for review, never auto-added
* ``noise``    — food delivery, digital purchases, newsletters, job applications…
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from .. import numbers
from ..model import (AVAILABLE_FOR_PICKUP, DELIVERED, EXCEPTION, FAILED_ATTEMPT, IN_TRANSIT, LABEL_CREATED, ORDERED,
                     OUT_FOR_DELIVERY, RETURNED)

# ------------------------------------------------------------------ senders
MERCHANTS = {  # domain suffix -> display name
    "amazon.es": "Amazon", "amazon.com": "Amazon", "amazon.de": "Amazon", "amazon.fr": "Amazon", "amazon.it": "Amazon",
    "amazon.co.uk": "Amazon", "pcspecialist.es": "PCSpecialist", "pcspecialist.co.uk": "PCSpecialist", "wallapop.com": "Wallapop",
    "inpost.es": "InPost", "correos.es": "Correos", "ups.com": "UPS", "dhl.com": "DHL", "dhl.de": "DHL", "seur.com": "SEUR",
    "gls-spain.es": "GLS", "gls-group.eu": "GLS", "mrw.es": "MRW", "nacex.es": "NACEX", "cttexpress.com": "CTT Express",
    "temu.com": "Temu", "temuemail.com": "Temu", "aliexpress.com": "AliExpress", "shein.com": "SHEIN", "pccomponentes.com": "PcComponentes",
    "elcorteingles.es": "El Corte Inglés", "mediamarkt.es": "MediaMarkt", "fnac.es": "Fnac", "zalando.es": "Zalando",
    "decathlon.es": "Decathlon", "ikea.com": "IKEA", "apple.com": "Apple", "game.es": "GAME", "carrefour.es": "Carrefour",
    "vinted.es": "Vinted", "ebay.es": "eBay", "ebay.com": "eBay", "miravia.es": "Miravia", "xiaomi.com": "Xiaomi",
}
SENDER_MERCHANT = {"googlestore-noreply@google.com": "Google Store", "store-noreply@google.com": "Google Store"}
CARRIER_SENDERS = {"ups.com": "ups", "dhl.com": "dhl", "dhl.de": "dhl", "correos.es": "correos", "inpost.es": "inpost", "seur.com": "seur",
                   "gls-spain.es": "gls", "gls-group.eu": "gls", "mrw.es": "mrw", "nacex.es": "nacex", "cttexpress.com": "ctt",
                   "correosexpress.com": "correos_express", "paack.co": "paack", "zeleris.com": "zeleris",
                   "ecoscooting.com": "ecoscooting", "cainiao.com": "cainiao", "gls-group.com": "gls", "dpd.com": "dpd", "dpd.es": "dpd",
                   "fedex.com": "fedex", "tnt.com": "tnt", "postnl.nl": "postnl", "genei.es": "other"}
NOISE_SENDERS = ("just-eat", "justeat", "glovo", "ubereats", "deliveroo", "mcdonalds", "burgerking", "pjespana", "telepizza", "dominos",
                 "tacobell", "kfc", "linkedin.com", "unir.net", "googleplay-noreply", "digital-no-reply@amazon", "no-reply@amazon.es",
                 "novedades@amazon", "store-news@amazon", "newsletter", "deals.aliexpress", "selections.aliexpress", "info@nl.mail",
                 "microsoft-noreply", "steampowered", "playstation", "nintendo", "epicgames", "spotify", "netflix", "noreply@youtube",
                 "talent", "jobs-noreply", "sales.alibaba", "alibaba.com", "invitations@linkedin", "zendesk.com", "business.amazon")
NOISE_SUBJECT = re.compile(
    r"\b(ofertas?|descuentos?|cup[oó]n|rebajas|-\d{2}%|newsletter|suscr[ií]bete|webinar|factura electr[oó]nica|recibo de tu pedido de google play|"
    r"cumple tus expectativas|da tu opini[oó]n|valora|rese[ñn]a|solicitud|candidatura|proceso de selecci[oó]n|regalo fue enviado|"
    r"tareas con fecha de entrega|consigue env[ií]o gratis|alegr[ií]a en camino|entrega especial|realiza tu pedido)\b", re.I)

# ------------------------------------------------------------------ status phrases (subject first, then the headline)
STATUS_PHRASES: list[tuple[str, str]] = [
    (RETURNED, r"devuelto al remitente|devoluci[oó]n al remitente|returned to sender|retour"),
    (DELIVERED, r"\bentregad[oa]s?\b|se acaba de entregar|ha sido entregado|delivered|zugestellt|livr[ée]|consegnato|bezorgd"),
    (AVAILABLE_FOR_PICKUP, r"te est[aá] esperando|ya puedes recoger|listo para (?:su )?recog|disponible para (?:su )?recog|"
                           r"punto pack|a disposici[oó]n del destinatario|ready for (?:pick ?up|collection)|abholbereit"),
    (FAILED_ATTEMPT, r"no (?:hemos|se ha) podido entregar|intento de entrega|ausente|delivery attempt|missed (?:you|delivery)|"
                     r"we tried to deliver"),
    (EXCEPTION, r"incidencia|retraso|delayed|problema con (?:tu|su) (?:env[ií]o|pedido)|exception|detenido en aduanas|"
                r"direcci[oó]n incorrecta"),
    (OUT_FOR_DELIVERY, r"en reparto|out for delivery|llega hoy|arriving today|in zustellung|en cours de livraison|in consegna"),
    (IN_TRANSIT, r"\benviad[oa]s?\b|se ha enviado|ha sido enviado|ha salido|en camino|en tr[aá]nsito|shipped|dispatched|on (?:its|the) way|"
                 r"has shipped|versandt|exp[ée]di[ée]|spedit[oa]|verzonden|en route"),
    (LABEL_CREATED, r"listo para enviar|preparando (?:tu|su) (?:env[ií]o|pedido)|etiqueta creada|label created|ready to ship|"
                    r"pendiente de recogida por parte de la empresa de transporte"),
    (ORDERED, r"gracias por (?:realizar |hacer )?(?:tu|su) (?:pedido|compra)|pedido confirmado|confirmaci[oó]n (?:de|del) pedido|hemos recibido (?:tu|su) pedido|"
              r"order (?:confirmed|confirmation|received)|thank you for your order|^pedido\s*:|tu pedido se ha confirmado"),
]
_STATUS_RE = [(s, re.compile(rx, re.I | re.M)) for s, rx in STATUS_PHRASES]
PROGRESS_BAR_LINES = re.compile(r"^(pedido|enviado|en reparto|entregado|ordered|shipped|out for delivery|delivered)$", re.I)

# "enviado con UPS", "servicio de entrega de UPS", "via DHL", "shipped with GLS", "UPS tracking"
CARRIER_PHRASE = re.compile(r"(?:\b(?:con|mediante|v[ií]a|por|de|with|via|by)\s+(?:el\s+servicio\s+de\s+(?:entrega\s+de\s+)?)?|"
                            r"servicio de entrega de\s+)([A-Z][A-Za-z ]{1,18}?)\b|\b([A-Z][A-Za-z]{1,15})\s+(?:tracking|seguimiento)\b")
REPLY_SUBJECT = re.compile(r"^\s*(?:re|rv|fw|fwd|aw|tr)\s*:", re.I)
GOODS_SIGNAL = re.compile(r"\b(paquete|env[ií]o|enviad[oa]|entrega|reparto|seguimiento|parcel|package|shipment|shipped|delivery|"
                          r"recog(?:er|ida)|transportista|carrier|courier)\b", re.I)
ORDER_SIGNAL = re.compile(r"\b(pedido|order|bestellung|commande|ordine)\b", re.I)

# ------------------------------------------------------------------ order numbers
ORDER_PATTERNS = [
    re.compile(r"\b(\d{3}-\d{7}-\d{7})\b"),                                                    # Amazon
    re.compile(r"\b(GS\.\d{4}-\d{4}-\d{4})\b"),                                                # Google Store
    re.compile(r"pedido\s*\(?\s*(?:n[uú]mero|n\.?\s*[ºo°])\s*[«\"']?\s*([A-Z0-9][A-Z0-9\-]{3,24})", re.I),
    re.compile(r"pedido\s+([0-9]{5,12})\b", re.I),
    re.compile(r"(?:order|bestellung|commande)\s*(?:number|no\.?|n[ºo°]|#|nummer|num[eé]ro)?\s*[:#]?\s*([A-Z]{0,3}[0-9][A-Z0-9\-]{4,24})", re.I),
    re.compile(r"(?:n[uú]mero de pedido|referencia(?: del pedido)?|ref\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\.]{4,24})", re.I),
]

# ------------------------------------------------------------------ dates
MONTHS = {"ene": 1, "enero": 1, "jan": 1, "january": 1, "feb": 2, "febrero": 2, "february": 2, "mar": 3, "marzo": 3, "march": 3,
          "abr": 4, "abril": 4, "apr": 4, "april": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6, "june": 6, "jul": 7, "julio": 7,
          "july": 7, "ago": 8, "agosto": 8, "aug": 8, "august": 8, "sep": 9, "sept": 9, "septiembre": 9, "september": 9, "oct": 10,
          "octubre": 10, "october": 10, "nov": 11, "noviembre": 11, "november": 11, "dic": 12, "diciembre": 12, "dec": 12, "december": 12}
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6, "monday": 0, "tuesday": 1,
            "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
_MONTH_RX = "|".join(sorted(MONTHS, key=len, reverse=True))
_DAYMONTH = rf"(\d{{1,2}})\s*(?:de\s+)?({_MONTH_RX})\.?(?:\s+(?:de\s+)?(\d{{4}}))?"
_MONTHDAY = rf"({_MONTH_RX})\.?\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?"
ETA_LEAD = (r"(?:llega(?:r[aá])?|se entrega(?:r[aá])?|se entraga|entrega (?:estimada|prevista)|fecha (?:estimada |prevista )?de entrega|"
            r"entrega entre|recibir[aá]s|arriv(?:es|ing)|estimated delivery|expected delivery|delivery (?:date|estimate)|voraussichtliche zustellung)")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def clean_text(text: str) -> str:
    """Drop the invisible pre-header padding some senders add (zero-width joiners, soft hyphens, figure spaces)."""
    text = re.sub(r"[͏​‌‍ ­﻿]+", "", text or "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


@dataclass
class MailFacts:
    kind: str = "noise"                      # shipping | maybe | noise
    score: int = 0
    reasons: list[str] = field(default_factory=list)
    merchant: str = ""
    merchant_domain: str = ""
    carrier: str = ""
    carrier_sender: bool = False             # the mail comes from the carrier itself
    numbers: list[dict] = field(default_factory=list)
    order_ref: str = ""
    sub_ref: str = ""                        # e.g. Amazon shipmentId: one order, several parcels
    status: str = ""
    status_phrase: str = ""
    item: str = ""
    eta_from: str = ""                       # ISO dates
    eta_to: str = ""
    eta_text: str = ""
    promise_min_days: Optional[float] = None
    promise_max_days: Optional[float] = None
    promise_business: bool = False
    pickup_code: str = ""
    pickup_place: str = ""
    pickup_deadline: str = ""
    tracking_link: str = ""
    origin_country: str = ""
    price: Optional[float] = None
    currency: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _domain(address: str) -> str:
    return (address or "").rpartition("@")[2].lower().strip()


def _suffix_match(domain: str, table: dict[str, str]) -> str:
    for key, value in table.items():
        if domain == key or domain.endswith("." + key):
            return value
    return ""


def merchant_of(from_address: str, from_name: str, text: str) -> tuple[str, str]:
    address = (from_address or "").lower()
    if address in SENDER_MERCHANT:
        return SENDER_MERCHANT[address], _domain(address)
    domain = _domain(address)
    name = _suffix_match(domain, MERCHANTS)
    if name:
        return name, domain
    if "shopifyemail.com" in domain or "myshopify" in domain:
        first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip() and not ln.strip().startswith(("*", "(", "-"))
                      and len(ln.strip()) < 40 and "order" not in ln.lower()), "")
        store = re.search(r"https?://(?:shop\.|www\.)?([a-z0-9\-]+)\.[a-z.]+", text or "", re.I)
        return (first or (store.group(1).capitalize() if store else "") or (from_name or "Shopify store")), domain
    if from_name and not re.search(r"no.?reply|notific|info|customer|service", from_name, re.I):
        return from_name.strip()[:60], domain
    root = domain.split(".")
    core = root[-2] if len(root) >= 2 else domain
    return core.replace("-", " ").title(), domain


def carrier_from_phrases(text: str) -> str:
    """The carrier named in a phrase like "enviado con UPS" (a bare mention such as "correos electrónicos" is not enough)."""
    for m in CARRIER_PHRASE.finditer(text or ""):
        word = (m.group(1) or m.group(2) or "").strip()
        found = numbers.carriers_mentioned(word)
        if found:
            return found[0]
    return ""


def _status_from(text: str) -> tuple[str, str]:
    for status, rx in _STATUS_RE:
        m = rx.search(text)
        if m:
            return status, m.group(0)
    return "", ""


def _headline(text: str, limit: int = 900) -> str:
    """The first meaningful lines of the body, without progress bars ("Pedido / Enviado / En reparto / Entregado")."""
    lines = []
    for line in clean_text(text).splitlines():
        line = line.strip()
        if not line or PROGRESS_BAR_LINES.match(line) or len(line) <= 2:
            continue
        lines.append(line)
        if sum(len(x) for x in lines) > limit:
            break
    return "\n".join(lines)


def _parse_daymonth(day: str, month: str, year: str, ref: date) -> Optional[date]:
    try:
        m = MONTHS[_fold(month).rstrip(".")]
        y = int(year) if year else ref.year
        d = date(y, m, int(day))
    except (KeyError, ValueError):
        return None
    if not year and d < ref - timedelta(days=60):
        d = date(ref.year + 1, d.month, d.day)
    return d


def _relative_day(word: str, ref: date) -> Optional[date]:
    w = _fold(word)
    if w in ("hoy", "today"):
        return ref
    if w in ("manana", "tomorrow"):
        return ref + timedelta(days=1)
    if w in ("pasado manana",):
        return ref + timedelta(days=2)
    if w in WEEKDAYS:
        ahead = (WEEKDAYS[w] - ref.weekday()) % 7
        return ref + timedelta(days=ahead or 7)
    return None


def find_eta(text: str, ref: date) -> tuple[Optional[date], Optional[date], str]:
    """An explicit delivery date or window: "Llega mañana", "Llega el domingo", "Se entrega: 21 de ago ‑ 24 de ago",
    "Estimated delivery: Oct 3 - Oct 5", "entre el 3 y el 5 de octubre"."""
    folded = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", _fold(clean_text(text)))
    rel = r"(hoy|manana|pasado manana|today|tomorrow|lunes|martes|miercoles|jueves|viernes|sabado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    lead = _fold(ETA_LEAD)
    # window "21 de ago - 24 de ago" / "entre el 3 y el 5 de octubre"
    m = re.search(lead + r"[^\n\d]{0,30}?" + _DAYMONTH + r"\s*(?:-|a|al|hasta|y el|y)\s*" + _DAYMONTH, folded)
    if m:
        a = _parse_daymonth(m.group(1), m.group(2), m.group(3), ref)
        b = _parse_daymonth(m.group(4), m.group(5), m.group(6), ref)
        if a and b:
            return min(a, b), max(a, b), m.group(0)
    m = re.search(r"entre el (\d{1,2}) y el (\d{1,2}) de (" + _MONTH_RX + r")", folded)
    if m:
        a = _parse_daymonth(m.group(1), m.group(3), "", ref)
        b = _parse_daymonth(m.group(2), m.group(3), "", ref)
        if a and b:
            return a, b, m.group(0)
    m = re.search(lead + r"[^\n\d]{0,30}?" + _MONTHDAY + r"\s*(?:-|to|and)\s*(?:" + _MONTHDAY + r"|(\d{1,2}))", folded)
    if m:
        a = _parse_daymonth(m.group(2), m.group(1), m.group(3), ref)
        b = _parse_daymonth(m.group(5), m.group(4), m.group(6), ref) if m.group(4) else _parse_daymonth(m.group(7), m.group(1), m.group(3), ref)
        if a and b:
            return min(a, b), max(a, b), m.group(0)
    m = re.search(lead + r"\s*(?:el |the |on )?" + rel + r"\b", folded)
    if m:
        d = _relative_day(m.group(1), ref)
        if d:
            return d, d, m.group(0)
    m = re.search(lead + r"[^\n\d]{0,30}?(?:el |on )?" + _DAYMONTH, folded)
    if m:
        d = _parse_daymonth(m.group(1), m.group(2), m.group(3), ref)
        if d:
            return d, d, m.group(0)
    m = re.search(lead + r"[^\n\d]{0,30}?" + _MONTHDAY, folded)
    if m:
        d = _parse_daymonth(m.group(2), m.group(1), m.group(3), ref)
        if d:
            return d, d, m.group(0)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", folded)
    if m and re.search(lead, folded[max(0, m.start() - 60):m.start()]):
        try:
            y = int(m.group(3))
            d = date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
            return d, d, m.group(0)
        except ValueError:
            pass
    return None, None, ""


def find_promise(text: str) -> tuple[Optional[float], Optional[float], bool]:
    """The sender's delivery promise in days: "al menos 48 horas … hasta 6 días", "entre 3 y 5 días laborables",
    "2-4 business days". Returns ``(min_days, max_days, business_days)``."""
    folded = _fold(clean_text(text))
    business = bool(re.search(r"dias? (laborables|habiles)|business days|working days|werktage", folded))
    m = re.search(r"entre (\d{1,2}) y (\d{1,2}) dias", folded) or re.search(r"(\d{1,2})\s*(?:-|a)\s*(\d{1,2})\s*(?:dias|business days|working days|days|werktage)", folded)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b), business
    lo = re.search(r"(?:al menos|minimo|at least)\s+(\d{1,3})\s*(horas|hours|dias|days)", folded)
    hi = re.search(r"(?:hasta|up to|maximo)\s+(\d{1,2})\s*(dias|days|werktage)", folded)
    to_days = lambda n, unit: float(n) / 24 if unit.startswith(("hora", "hour")) else float(n)  # noqa: E731
    if lo or hi:
        a = to_days(lo.group(1), lo.group(2)) if lo else None
        b = to_days(hi.group(1), hi.group(2)) if hi else None
        return a, b, business
    m = re.search(r"(?:entrega|delivery) (?:en|in) (\d{1,2})\s*(?:-|a)?\s*(\d{1,2})?\s*(horas|hours|dias|days)", folded)
    if m:
        a = to_days(m.group(1), m.group(3))
        b = to_days(m.group(2), m.group(3)) if m.group(2) else a
        return a, b, business
    return None, None, business


def find_pickup(text: str, ref: date) -> tuple[str, str, str]:
    t = clean_text(text)
    code = ""
    m = re.search(r"(?:c[oó]digo(?: de recogida| pin)?|pin|siguiente c[oó]digo)\s*[:\n]*\s*([A-Z0-9]{4,24})\b", t, re.I)
    if m and re.search(r"\d", m.group(1)):
        code = m.group(1)
    place = ""
    m = re.search(r"(?:te est[aá] esperando en|est[aá] esperando en|punto de recogida|recoger en|pick ?up point)\s*:?\s*\n+((?:.+\n?){1,3})", t, re.I)
    if m:
        lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()][:3]
        place = ", ".join(lines)[:160]
    deadline = ""
    m = re.search(r"(?:dispones de|tienes|plazo de|within)\s+(\d{1,2})\s*(?:d[ií]as|days)", t, re.I)
    if m:
        deadline = (ref + timedelta(days=int(m.group(1)))).isoformat()
    m2 = re.search(r"(?:hasta el|antes del|before|until)\s+" + _DAYMONTH, _fold(t))
    if m2 and not deadline:
        d = _parse_daymonth(m2.group(1), m2.group(2), m2.group(3), ref)
        if d:
            deadline = d.isoformat()
    return code, place, deadline


def find_item(subject: str, text: str, merchant: str) -> str:
    m = re.search(r"[\"“«]([^\"”»]{3,80})[\"”»]", subject or "")
    if m:
        item = m.group(1).strip().rstrip(".").rstrip("…").strip()
        more = re.search(r"y (\d+) productos? m[aá]s", subject or "", re.I)
        return item + (f" (+{more.group(1)})" if more else "")
    lines = [ln.strip() for ln in clean_text(text).splitlines() if ln.strip()]
    for i in range(1, len(lines)):
        if not re.fullmatch(r"\d{1,5}[.,]\d{2}\s*€|€\s*\d{1,5}[.,]\d{2}", lines[i]):
            continue
        # the product name sits right above its price, sometimes with an ID or quantity line in between
        for line in reversed(lines[max(0, i - 3):i]):
            if re.search(r"n[uú]mero de id|imei|cantidad|quantity|^id\b", line, re.I) or not re.search(r"[A-Za-zÀ-ÿ]{3}", line):
                continue
            if 6 <= len(line) <= 90 and not re.search(r"total|env[ií]o|protecci|precio|price|subtotal|iva", line, re.I):
                return line
            break
    m = re.search(r"items in this shipment\s*-+\s*\n+(.+)", text or "", re.I)
    if m:
        return m.group(1).strip()[:90]
    return ""


def find_order(text: str, subject: str) -> str:
    for rx in ORDER_PATTERNS:
        for source in (subject or "", clean_text(text)):
            m = rx.search(source)
            if m:
                ref = m.group(1).strip().strip("-.")
                if len(ref) >= 5 and re.search(r"\d", ref) and not numbers.ups_valid(ref):
                    return ref
    return ""


def find_price(text: str) -> tuple[Optional[float], str]:
    m = re.search(r"\btotal\b[^\n\d]{0,20}(\d{1,6}[.,]\d{2})\s*(€|eur)", text or "", re.I) or re.search(r"(\d{1,6}[.,]\d{2})\s*€", text or "")
    if not m:
        return None, ""
    try:
        return float(m.group(1).replace(".", "").replace(",", ".") if "," in m.group(1) else m.group(1)), "EUR"
    except ValueError:
        return None, ""


def _amazon_sub_ref(links: list[dict]) -> str:
    for link in links or []:
        url = numbers.unwrap(str(link.get("url") or ""))
        m = re.search(r"shipmentId=([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
    return ""


def _tracking_link(links: list[dict]) -> str:
    for link in links or []:
        url = numbers.unwrap(str(link.get("url") or ""))
        if re.search(r"progress-tracker|track|seguimiento|delivery/timeline|trace", url, re.I) and not re.search(r"unsubscribe|baja", url, re.I):
            return url[:600]
    return ""


def analyze(message: dict[str, Any]) -> MailFacts:
    subject = clean_text(str(message.get("subject") or "")).strip()
    text = clean_text(str(message.get("text") or ""))
    links = message.get("links") or []
    address = str(message.get("from_address") or "").lower()
    ts = message.get("ts")
    ref = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone().date() if ts else date.today()
    facts = MailFacts()
    facts.merchant, facts.merchant_domain = merchant_of(address, str(message.get("from_name") or ""), text)
    domain = _domain(address)
    carrier_sender = _suffix_match(domain, CARRIER_SENDERS)
    facts.carrier_sender = bool(carrier_sender)
    score, reasons = 0, []

    noise = next((n for n in NOISE_SENDERS if n in address), "")
    if noise:
        score -= 10
        reasons.append(f"sender looks like {noise}")
    if message.get("from_self") or (address and address == str(message.get("account_address") or "").lower()):
        score -= 8
        noise = noise or "yourself"
        reasons.append("sent by you")
    if REPLY_SUBJECT.search(subject):
        score -= 3
        reasons.append("a reply or forward")
    if NOISE_SUBJECT.search(_fold(subject)):
        score -= 4
        reasons.append("marketing or non-parcel subject")

    found = numbers.find(text + "\n" + subject, links)
    facts.numbers = [f.to_dict() for f in found if f.confidence >= 65][:5]
    if facts.numbers:
        score += 5
        reasons.append(f"tracking number {facts.numbers[0]['number']}")
    facts.carrier = (facts.numbers[0]["carrier"] if facts.numbers and facts.numbers[0]["carrier"] else "") or carrier_sender or \
        carrier_from_phrases(subject + "\n" + text[:4000])
    if facts.merchant == "Amazon" and not facts.carrier:
        facts.carrier = "amazon"

    status, phrase = _status_from(_fold(subject))
    if not status:
        status, phrase = _status_from(_fold(_headline(text, 600)))
    facts.status, facts.status_phrase = status, phrase
    if status:
        score += 3
        reasons.append(f"status phrase «{phrase}»")
    if carrier_sender:
        score += 3
        reasons.append(f"sent by the carrier ({carrier_sender})")
    if GOODS_SIGNAL.search(subject):
        score += 1
    if ORDER_SIGNAL.search(subject):
        score += 1

    facts.order_ref = find_order(text, subject)
    if facts.merchant == "Amazon":
        facts.sub_ref = _amazon_sub_ref(links)
        if facts.sub_ref or "progress-tracker" in " ".join(str(l.get("url")) for l in links):
            score += 2
    facts.tracking_link = _tracking_link(links)
    a, b, eta_text = find_eta(subject + "\n" + _headline(text, 3000), ref)
    if a:
        facts.eta_from, facts.eta_to, facts.eta_text = a.isoformat(), b.isoformat(), eta_text.strip()
        score += 1
    facts.promise_min_days, facts.promise_max_days, facts.promise_business = find_promise(text)
    if status == AVAILABLE_FOR_PICKUP or re.search(r"recog", subject, re.I):
        facts.pickup_code, facts.pickup_place, facts.pickup_deadline = find_pickup(text, ref)
    facts.item = find_item(subject, text, facts.merchant)
    facts.price, facts.currency = find_price(text)
    # Survey mails after delivery still say "entregado": they confirm, they do not create.
    if re.search(r"cu[eé]ntanos|opini[oó]n|valora|survey|how did we do", subject, re.I) and status == DELIVERED:
        reasons.append("survey after delivery")
        score -= 1

    facts.score = score
    facts.reasons = reasons
    if noise and not facts.numbers:
        facts.kind = "noise"
    elif score >= 4 or (facts.numbers and score >= 3):
        facts.kind = "shipping"
    elif score >= 2:
        facts.kind = "maybe"
    else:
        facts.kind = "noise"
    return facts
