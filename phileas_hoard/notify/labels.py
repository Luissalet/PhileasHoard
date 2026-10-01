"""Notification type -> human label (ES / EN) and the text of a notification."""

from __future__ import annotations

from typing import Any

from ..model import N_DELIVERED, N_ETA, N_NEW, N_OUT, N_PICKUP, N_PICKUP_DEADLINE, N_PROBLEM, N_STALE, N_STATUS, NOTIFY_TYPES

LABELS: dict[str, dict[str, str]] = {
    "es": {N_NEW: "Nuevo envío", N_STATUS: "Cambio de estado", N_OUT: "En reparto", N_DELIVERED: "Entregado", N_PICKUP: "Para recoger",
           N_PICKUP_DEADLINE: "Plazo de recogida", N_PROBLEM: "Incidencia", N_ETA: "Nueva fecha", N_STALE: "Sin noticias", "test": "Prueba"},
    "en": {N_NEW: "New shipment", N_STATUS: "Status change", N_OUT: "Out for delivery", N_DELIVERED: "Delivered", N_PICKUP: "Ready for pickup",
           N_PICKUP_DEADLINE: "Pickup deadline", N_PROBLEM: "Problem", N_ETA: "New date", N_STALE: "No news", "test": "Test"},
}
assert all(t in LABELS["es"] and t in LABELS["en"] for t in NOTIFY_TYPES)

WORDS = {"es": {"open": "Ver seguimiento", "test_title": "Prueba de notificación", "test_body": "Si lo lees, este canal funciona."},
         "en": {"open": "Open tracking", "test_title": "Notification test", "test_body": "If you can read this, the channel works."}}

TYPE_TAGS = {N_NEW: "package", N_STATUS: "truck", N_OUT: "truck", N_DELIVERED: "white_check_mark", N_PICKUP: "round_pushpin",
             N_PICKUP_DEADLINE: "alarm_clock", N_PROBLEM: "warning", N_ETA: "calendar", N_STALE: "hourglass", "test": "bell"}


def label(kind: str, lang: str = "es") -> str:
    return LABELS.get(lang, LABELS["es"]).get(kind, kind.replace("_", " ").capitalize() if kind else "")


def format_price(price: Any, currency: Any, lang: str = "es") -> str:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return ""
    text = f"{value:,.2f}"
    if lang == "es":
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {'€' if str(currency or 'EUR').upper() == 'EUR' else currency}"


def compose(event: dict[str, Any], lang: str = "es") -> tuple[str, str]:
    """``(title, body)``: the engine already writes both in the user's language; this only guards empty values."""
    title = str(event.get("title") or "").strip() or label(str(event.get("type") or ""), lang) or "Phileas's Hoard"
    return title, str(event.get("summary") or "").strip()
