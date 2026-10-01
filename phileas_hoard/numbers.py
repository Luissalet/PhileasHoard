"""Tracking numbers: find them in text and links, validate them, guess the carrier and build its public tracking link.

Three levels of evidence, strongest first:

1. A carrier tracking URL (``ups.com/track?tracknum=…``, ``yuntrack.com/Track/Detail/…``) — the number and the carrier.
2. A self-describing format with a check digit or a fixed prefix (UPS ``1Z…`` with its mod-10 check, UPU S10
   ``RR123456785CN`` with its mod-11 check, DHL ``JJD…``, YunExpress ``YT…``, Correos ``P…`` codes).
3. A bare alphanumeric token right after a label ("número de seguimiento", "tracking number", "Seguimiento:") or
   next to a carrier name. Ambiguous numeric formats (DHL Express, GLS, SEUR, FedEx…) are only accepted this way.

Nothing here touches the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit

CARRIERS: dict[str, dict[str, str]] = {
    "ups": {"name": "UPS", "url": "https://www.ups.com/track?loc=es_ES&tracknum={n}"},
    "dhl": {"name": "DHL", "url": "https://www.dhl.com/es-es/home/tracking/tracking-parcel.html?submit=1&tracking-id={n}"},
    "correos": {"name": "Correos", "url": "https://www.correos.es/es/es/herramientas/localizador/envios/detalle?tracking-number={n}"},
    "correos_express": {"name": "Correos Express", "url": "https://s.correosexpress.com/SeguimientoSinCP/search?n={n}"},
    "seur": {"name": "SEUR", "url": "https://www.seur.com/livetracking/?segOnlineIdentificador={n}&segOnlineIdioma=es"},
    "gls": {"name": "GLS", "url": "https://gls-group.com/ES/es/seguimiento-envio/?match={n}"},
    "mrw": {"name": "MRW", "url": "https://www.mrw.es/seguimiento_envios/MRW_resultados_consultas.asp?modo=nacional&envio={n}"},
    "nacex": {"name": "NACEX", "url": "https://www.nacex.es/seguimientoDetalle.do?agencia_origen=&numero_albaran={n}"},
    "ctt": {"name": "CTT Express", "url": "https://www.cttexpress.com/localizador-de-envios/?sc={n}"},
    "inpost": {"name": "InPost", "url": "https://inpost.es/seguimiento-envio/?number={n}"},
    "fedex": {"name": "FedEx", "url": "https://www.fedex.com/fedextrack/?trknbr={n}"},
    "tnt": {"name": "TNT", "url": "https://www.tnt.com/express/es_es/site/herramientas-envio/seguimiento.html?searchType=con&cons={n}"},
    "yunexpress": {"name": "YunExpress", "url": "https://www.yuntrack.com/Track/Detail/{n}"},
    "cainiao": {"name": "Cainiao", "url": "https://global.cainiao.com/newDetail.htm?mailNoList={n}"},
    "postnl": {"name": "PostNL", "url": "https://jouw.postnl.nl/track-and-trace/{n}"},
    "royalmail": {"name": "Royal Mail", "url": "https://www.royalmail.com/track-your-item#/tracking-results/{n}"},
    "deutschepost": {"name": "Deutsche Post", "url": "https://www.deutschepost.de/de/s/sendungsverfolgung.html?piececode={n}"},
    "laposte": {"name": "La Poste", "url": "https://www.laposte.fr/outils/suivre-vos-envois?code={n}"},
    "chinapost": {"name": "China Post", "url": "https://t.17track.net/es#nums={n}"},
    "amazon": {"name": "Amazon", "url": ""},
    "paack": {"name": "Paack", "url": "https://paack.co/es/tracking?tracking={n}"},
    "zeleris": {"name": "Zeleris", "url": "https://www.zeleris.com/seguimiento_envio.aspx?id_seguimiento={n}"},
    "ecoscooting": {"name": "Ecoscooting", "url": "https://www.ecoscooting.com/tracking/{n}"},
    "dpd": {"name": "DPD", "url": "https://www.dpd.com/es/es/seguimiento/?parcelNumber={n}"},
    "other": {"name": "", "url": "https://t.17track.net/es#nums={n}"},
}

# Words that name a carrier in mail text; used for context-only numbers and for "Se ha enviado con UPS".
CARRIER_WORDS = [
    ("correos_express", r"correos\s*express"), ("correos", r"\bcorreos\b"), ("ups", r"\bUPS\b"), ("dhl", r"\bDHL\b"),
    ("seur", r"\bSEUR\b"), ("gls", r"\bGLS\b"), ("mrw", r"\bMRW\b"), ("nacex", r"\bNACEX\b"), ("ctt", r"\bCTT(?:\s*Express)?\b"),
    ("inpost", r"\bInPost\b|\bMondial\s+Relay\b"), ("fedex", r"\bFed\s?Ex\b"), ("tnt", r"\bTNT\b"), ("yunexpress", r"\bYun\s?Express\b"),
    ("cainiao", r"\bCainiao\b"), ("postnl", r"\bPostNL\b"), ("royalmail", r"\bRoyal\s+Mail\b"), ("deutschepost", r"\bDeutsche\s+Post\b"),
    ("paack", r"\bPaack\b"), ("zeleris", r"\bZeleris\b"), ("amazon", r"\bAmazon\s+Logistics\b"), ("ecoscooting", r"\bEcoscooting\b"),
    ("dpd", r"\bDPD\b"),
]
_CARRIER_WORD_RE = [(cid, re.compile(rx, re.I if cid not in ("ups", "dhl", "gls", "mrw", "tnt", "dpd") else 0)) for cid, rx in CARRIER_WORDS]

S10_COUNTRY = {"ES": "correos", "CN": "chinapost", "GB": "royalmail", "DE": "deutschepost", "NL": "postnl", "FR": "laposte"}

LABEL_RE = re.compile(
    r"(?:n[uú]mero\s+de\s+(?:seguimiento|env[ií]o|tracking)|c[oó]digo\s+de\s+(?:seguimiento|env[ií]o|recogida)|"
    r"tracking\s*(?:number|no\.?|n[º°o]|id|code)?|seguimiento|sendungsnummer|num[eé]ro\s+de\s+suivi|"
    r"localizador|n\.?\s*[ºo°]\s*de\s+env[ií]o|awb)\s*(?:es|is|:|#|\(.*?\))?\s*[:#]?\s*([A-Z0-9][A-Z0-9\- ]{6,34}[A-Z0-9])",
    re.I)
TOKEN_STOP = re.compile(r"\s{2,}|\s(?=[a-záéíóúñ]{2,})")


@dataclass
class Found:
    number: str
    carrier: str = ""            # carrier id from CARRIERS, "" when unknown
    confidence: int = 50         # 0-100
    evidence: str = ""           # url | format | label | context
    url: str = ""                # where it came from, when it was a link
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"number": self.number, "carrier": self.carrier, "confidence": self.confidence, "evidence": self.evidence}


def normalize(number: str) -> str:
    return re.sub(r"[\s\-]", "", str(number or "")).upper()


def ups_valid(n: str) -> bool:
    n = normalize(n)
    if not re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return False
    total = 0
    for i, ch in enumerate(n[2:17]):
        value = int(ch) if ch.isdigit() else (ord(ch) - 63) % 10
        total += value * 2 if i % 2 else value
    return (10 - total % 10) % 10 == int(n[17]) if n[17].isdigit() else False


def s10_valid(n: str) -> bool:
    n = normalize(n)
    if not re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", n):
        return False
    weights = (8, 6, 4, 2, 3, 5, 9, 7)
    total = sum(int(d) * w for d, w in zip(n[2:10], weights))
    check = 11 - total % 11
    check = 0 if check == 10 else 5 if check == 11 else check
    return check == int(n[10])


def classify(number: str) -> tuple[str, int]:
    """``(carrier, confidence)`` from the format alone; ``("", 0)`` when the format says nothing."""
    n = normalize(number)
    if ups_valid(n):
        return "ups", 98
    if re.fullmatch(r"1Z[0-9A-Z]{16}", n):
        return "ups", 70
    if s10_valid(n):
        return S10_COUNTRY.get(n[-2:], "other"), 92
    if re.fullmatch(r"JJD\d{15,24}|JVGL\d{8,20}|GM\d{16,22}|00340\d{15}|3S[A-Z]{4}\d{6,}", n):
        return ("postnl", 85) if n.startswith("3S") else ("dhl", 88)
    if re.fullmatch(r"YT\d{16}", n):
        return "yunexpress", 92
    if re.fullmatch(r"(LP|CN|CAINIAO)\d{12,20}[A-Z]{0,2}|LP\d{14}", n):
        return "cainiao", 75
    if re.fullmatch(r"TBA\d{9,14}", n):
        return "amazon", 85
    if re.fullmatch(r"P[A-Z0-9]{2}[A-Z0-9]{14,20}[A-Z]?", n) and re.search(r"\d{5}", n) and len(n) >= 16:
        return "correos", 72
    return "", 0


def plausible(number: str) -> bool:
    """A token that could be a tracking number at all (not a phone, a price or a postcode)."""
    n = normalize(number)
    if not 8 <= len(n) <= 35:
        return False
    if not re.search(r"\d{4}", n):
        return False
    if re.fullmatch(r"\d{9}", n) and n[0] in "6789":     # Spanish phone number
        return False
    if re.fullmatch(r"(?:34)?[6789]\d{8}", n):
        return False
    return True


# ------------------------------------------------------------------ links
_URL_PARAMS = ("tracknum", "trackingnumber", "tracking-number", "tracking_number", "tracking-id", "trackingid", "tracking", "trknbr",
               "awb", "piececode", "match", "mailnolist", "nums", "number", "numero", "n", "sc", "envio", "segonlineidentificador",
               "numero_albaran", "id_seguimiento", "code", "cons", "shipmentnumber", "parcelnumber", "barcode", "codigo")
_URL_HOSTS = [
    ("ups", "ups.com"), ("dhl", "dhl."), ("correos_express", "correosexpress"), ("correos", "correos.es"), ("seur", "seur.com"),
    ("gls", "gls-"), ("mrw", "mrw.es"), ("nacex", "nacex"), ("ctt", "cttexpress"), ("inpost", "inpost"), ("fedex", "fedex.com"),
    ("tnt", "tnt.com"), ("yunexpress", "yuntrack"), ("yunexpress", "yunexpress"), ("cainiao", "cainiao"), ("postnl", "postnl"),
    ("royalmail", "royalmail"), ("deutschepost", "deutschepost"), ("laposte", "laposte"), ("paack", "paack"), ("zeleris", "zeleris"),
    ("other", "17track"), ("other", "parcelsapp"), ("other", "aftership"),
]


def unwrap(url: str, depth: int = 3) -> str:
    """Follow click-tracking wrappers that carry the real URL inside (awstrack ``/L0/<url>``, ``?U=``, ``?url=``)."""
    for _ in range(depth):
        parts = urlsplit(url)
        inner = ""
        m = re.search(r"/L0/(https?(?::|%3A).*?)/\d+/[0-9A-Za-z-]{10,}", url, re.I) or re.search(r"/L0/(https?(?::|%3A).*)$", url, re.I)
        if m:
            inner = unquote(m.group(1))
        else:
            qs = parse_qs(parts.query)
            for key in ("U", "u", "url", "redirect", "target", "dest", "q", "link"):
                for value in qs.get(key, []):
                    value = unquote(value)
                    if value.lower().startswith(("http://", "https://")):
                        inner = value
                        break
                if inner:
                    break
        if not inner or inner == url:
            return url
        url = inner
    return url


def from_url(url: str) -> Optional[Found]:
    url = unwrap(url)
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    carrier = next((cid for cid, needle in _URL_HOSTS if needle in host), "")
    if not carrier:
        return None
    qs = {k.lower(): v for k, v in parse_qs(parts.query).items()}
    candidates = []
    for key in _URL_PARAMS:
        for value in qs.get(key, []):
            candidates.extend(re.split(r"[,;\s]+", value))
    m = re.search(r"/(?:track(?:ing)?|detail|seguimiento|trace|track-and-trace)/(?:[a-z\-]+/)?([A-Za-z0-9]{8,35})(?:[/?#]|$)", parts.path, re.I)
    if m:
        candidates.append(m.group(1))
    frag = parts.fragment
    m = re.search(r"nums=([A-Za-z0-9,]+)", frag) or re.search(r"tracking-results/([A-Za-z0-9]+)", frag)
    if m:
        candidates.extend(m.group(1).split(","))
    for cand in candidates:
        n = normalize(cand)
        if plausible(n):
            fmt_carrier, _ = classify(n)
            final = fmt_carrier if carrier == "other" and fmt_carrier else carrier
            return Found(n, final if final != "other" else (fmt_carrier or ""), 95, "url", url=url)
    return None


# ------------------------------------------------------------------ text
def carriers_mentioned(text: str) -> list[str]:
    seen = []
    for cid, rx in _CARRIER_WORD_RE:
        if rx.search(text or "") and cid not in seen:
            if cid == "correos" and "correos_express" in seen:
                continue
            seen.append(cid)
    return seen


def _nearest_carrier(text: str, pos: int, window: int = 160) -> str:
    lo, hi = max(0, pos - window), min(len(text), pos + window)
    chunk = text[lo:hi]
    best, best_dist = "", 10**9
    for cid, rx in _CARRIER_WORD_RE:
        for m in rx.finditer(chunk):
            dist = abs((lo + m.start()) - pos)
            if dist < best_dist:
                best, best_dist = cid, dist
    return best


FORMAT_RE = re.compile(
    r"\b(1Z[0-9A-Z]{16}|[A-Z]{2}\d{9}[A-Z]{2}|JJD\d{15,24}|JVGL\d{8,20}|YT\d{16}|TBA\d{9,14}|00340\d{15}|"
    r"P[A-Z0-9]{2}[A-Z0-9]{14,20}[A-Z]?|LP\d{14})\b")


def find(text: str, links: list[dict] | None = None) -> list[Found]:
    """Every tracking number in a message, best evidence first, one entry per number."""
    found: dict[str, Found] = {}

    def keep(item: Found) -> None:
        prev = found.get(item.number)
        if prev is None or item.confidence > prev.confidence:
            if prev is not None and not item.carrier:
                item.carrier = prev.carrier
            found[item.number] = item
        elif prev and not prev.carrier and item.carrier:
            prev.carrier = item.carrier

    for link in links or []:
        item = from_url(str(link.get("url") or ""))
        if item:
            keep(item)
    for url in re.findall(r"https?://[^\s<>\"')\]]+", text or ""):
        item = from_url(url)
        if item:
            keep(item)
    text = text or ""
    for m in FORMAT_RE.finditer(text):
        n = normalize(m.group(1))
        carrier, conf = classify(n)
        if not carrier or conf < 70:
            continue
        if carrier == "correos" and conf < 90 and not re.search(r"correos|recogida|seguimiento|env[ií]o", text, re.I):
            continue
        near = _nearest_carrier(text, m.start())
        if near and carrier in ("other", "") :
            carrier = near
        keep(Found(n, carrier, conf, "format"))
    for m in LABEL_RE.finditer(text):
        raw = TOKEN_STOP.split(m.group(1))[0].strip()
        first = raw.split(" ")[0]
        # "1Z… y RR…": a complete number before a space wins over gluing the words together
        if " " in raw and (classify(first)[0] or (plausible(first) and len(normalize(first)) >= 10)):
            raw = first
        n = normalize(raw)
        if not plausible(n) or re.fullmatch(r"[A-Z]+", n):
            continue
        if re.fullmatch(r"\d{3}-?\d{7}-?\d{7}", raw.replace(" ", "")):  # an Amazon order number, not a parcel
            continue
        carrier, conf = classify(n)
        near = _nearest_carrier(text, m.start())
        keep(Found(n, carrier or near, max(conf, 80 if near else 65), "label"))
    return sorted(found.values(), key=lambda f: -f.confidence)


def tracking_url(carrier: str, number: str) -> str:
    template = (CARRIERS.get(carrier) or {}).get("url") or ""
    return template.format(n=normalize(number)) if template and number else ""


def carrier_name(carrier: str) -> str:
    return (CARRIERS.get(carrier) or {}).get("name") or (carrier or "").upper()
