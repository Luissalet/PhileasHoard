"""Airline codes and names for the common carriers in Spain and Europe (flight-number prefixes in mail)."""

from __future__ import annotations

import re
import unicodedata

# IATA 2-character code -> display name. Reduced on purpose: what shows up in Spanish and European inboxes.
AIRLINES: dict[str, str] = {
    "IB": "Iberia", "I2": "Iberia Express", "YW": "Air Nostrum", "VY": "Vueling", "UX": "Air Europa", "FR": "Ryanair", "RK": "Ryanair UK",
    "U2": "easyJet", "EC": "easyJet Europe", "DS": "easyJet Switzerland", "V7": "Volotea", "NT": "Binter Canarias", "TP": "TAP Air Portugal",
    "LH": "Lufthansa", "BA": "British Airways", "AF": "Air France", "KL": "KLM", "EW": "Eurowings", "W6": "Wizz Air", "HV": "Transavia",
    "TO": "Transavia France", "DY": "Norwegian", "D8": "Norwegian", "SK": "SAS", "LX": "Swiss", "OS": "Austrian", "SN": "Brussels Airlines",
    "AZ": "ITA Airways", "EI": "Aer Lingus", "AY": "Finnair", "TK": "Turkish Airlines", "EK": "Emirates", "QR": "Qatar Airways",
    "DL": "Delta", "AA": "American Airlines", "UA": "United", "AC": "Air Canada", "LA": "LATAM", "AV": "Avianca", "AM": "Aeroméxico",
    "AT": "Royal Air Maroc", "DE": "Condor", "X3": "TUIfly", "LS": "Jet2", "LV": "Level", "PV": "Canaryfly", "PU": "Plus Ultra",
    "2W": "World2fly", "E9": "Evelop", "G9": "Air Arabia", "PC": "Pegasus", "VS": "Virgin Atlantic", "LO": "LOT Polish Airlines",
    "SU": "Aeroflot", "ET": "Ethiopian", "MS": "EgyptAir", "TU": "Tunisair", "AH": "Air Algérie", "BT": "airBaltic", "A3": "Aegean",
    "OU": "Croatia Airlines", "JU": "Air Serbia", "KM": "Air Malta", "W4": "Wizz Air Malta", "4O": "Lauda Europe", "AL": "Malta Air",
}
# Lower-case, accent-free name (as it appears in sender names and bodies) -> code. Longest names are tried first.
_NAME_TO_CODE = {
    "iberia express": "I2", "iberia": "IB", "air nostrum": "YW", "vueling": "VY", "air europa": "UX", "ryanair": "FR", "easyjet": "U2",
    "volotea": "V7", "binter": "NT", "tap air portugal": "TP", "tap portugal": "TP", "lufthansa": "LH", "british airways": "BA",
    "air france": "AF", "klm": "KL", "eurowings": "EW", "wizz air": "W6", "wizzair": "W6", "transavia": "HV", "norwegian": "DY",
    "swiss": "LX", "austrian": "OS", "brussels airlines": "SN", "ita airways": "AZ", "aer lingus": "EI", "finnair": "AY",
    "turkish airlines": "TK", "emirates": "EK", "qatar airways": "QR", "delta": "DL", "american airlines": "AA", "united": "UA",
    "air canada": "AC", "latam": "LA", "avianca": "AV", "royal air maroc": "AT", "condor": "DE", "jet2": "LS", "level": "LV",
    "canaryfly": "PV", "plus ultra": "PU", "world2fly": "E9", "evelop": "E9", "pegasus": "PC", "tui fly": "X3", "tuifly": "X3",
    "lot polish": "LO", "airbaltic": "BT", "air malta": "KM", "tap": "TP",
}
FLIGHT_NUMBER_PREFIXES = frozenset(AIRLINES)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def airline_name(code: str) -> str:
    return AIRLINES.get((code or "").upper(), "")


def code_for_name(text: str) -> str:
    """The IATA code of the first airline named in ``text`` (word-boundary match, longest names first), or ''."""
    folded = fold(text)
    for name in sorted(_NAME_TO_CODE, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", folded):
            return _NAME_TO_CODE[name]
    return ""


def split_flight_number(raw: str) -> tuple[str, str]:
    """``"VY 8421"`` -> ``("VY", "8421")``; unknown shapes give ``("", raw)``."""
    m = re.fullmatch(r"\s*([A-Z][A-Z0-9]|[0-9][A-Z])\s*0*(\d{1,4}[A-Z]?)\s*", (raw or "").upper())
    return (m.group(1), m.group(2)) if m else ("", (raw or "").strip())
