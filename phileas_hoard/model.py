"""Shipment statuses, their order, and the labels the UI and the notifications use."""

from __future__ import annotations

ORDERED = "ordered"                  # the shop has the order; nothing shipped yet
LABEL_CREATED = "label_created"      # label printed / carrier informed, not scanned yet
NOT_FOUND = "not_found"              # the carrier does not know the number (yet)
IN_TRANSIT = "in_transit"
CUSTOMS = "customs"
OUT_FOR_DELIVERY = "out_for_delivery"
AVAILABLE_FOR_PICKUP = "available_for_pickup"
FAILED_ATTEMPT = "failed_attempt"
EXCEPTION = "exception"
DELIVERED = "delivered"
RETURNED = "returned"
UNKNOWN = "unknown"

STATUSES = (ORDERED, LABEL_CREATED, NOT_FOUND, IN_TRANSIT, CUSTOMS, OUT_FOR_DELIVERY, AVAILABLE_FOR_PICKUP, FAILED_ATTEMPT,
            EXCEPTION, DELIVERED, RETURNED, UNKNOWN)
FINAL = frozenset({DELIVERED, RETURNED})
ACTIVE = frozenset(STATUSES) - FINAL

# How far along the journey a status is (0-100), for the progress bar and for "never go backwards on stale mail".
PROGRESS = {ORDERED: 5, NOT_FOUND: 10, UNKNOWN: 10, LABEL_CREATED: 15, IN_TRANSIT: 50, CUSTOMS: 45, EXCEPTION: 55,
            FAILED_ATTEMPT: 85, OUT_FOR_DELIVERY: 90, AVAILABLE_FOR_PICKUP: 92, DELIVERED: 100, RETURNED: 100}

LABELS = {
    "es": {ORDERED: "Pedido", LABEL_CREATED: "Etiqueta creada", NOT_FOUND: "Aún sin datos del transportista", IN_TRANSIT: "En tránsito",
           CUSTOMS: "En aduanas", OUT_FOR_DELIVERY: "En reparto", AVAILABLE_FOR_PICKUP: "Listo para recoger",
           FAILED_ATTEMPT: "Intento de entrega fallido", EXCEPTION: "Incidencia", DELIVERED: "Entregado", RETURNED: "Devuelto",
           UNKNOWN: "Sin estado"},
    "en": {ORDERED: "Ordered", LABEL_CREATED: "Label created", NOT_FOUND: "No carrier data yet", IN_TRANSIT: "In transit",
           CUSTOMS: "In customs", OUT_FOR_DELIVERY: "Out for delivery", AVAILABLE_FOR_PICKUP: "Ready for pickup",
           FAILED_ATTEMPT: "Delivery attempt failed", EXCEPTION: "Exception", DELIVERED: "Delivered", RETURNED: "Returned",
           UNKNOWN: "No status"},
}
assert all(s in LABELS["es"] and s in LABELS["en"] for s in STATUSES)

# Notification types (one per thing worth telling the user).
N_NEW = "shipment_new"
N_STATUS = "status_change"
N_OUT = "out_for_delivery"
N_DELIVERED = "delivered"
N_PICKUP = "pickup_ready"
N_PICKUP_DEADLINE = "pickup_deadline"
N_PROBLEM = "problem"
N_ETA = "eta_change"
N_STALE = "stale"
from .travel.model import TRAVEL_NOTIFY_TYPES  # noqa: E402

NOTIFY_TYPES = (N_NEW, N_STATUS, N_OUT, N_DELIVERED, N_PICKUP, N_PICKUP_DEADLINE, N_PROBLEM, N_ETA, N_STALE, *TRAVEL_NOTIFY_TYPES)


def label(status: str, lang: str = "es") -> str:
    return LABELS.get(lang, LABELS["es"]).get(status, status)


def progress(status: str) -> int:
    return PROGRESS.get(status, 10)
