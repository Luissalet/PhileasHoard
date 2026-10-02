"""Vocabulary of the travel facet: segment kinds and states, trip states, notification types and their labels."""

from __future__ import annotations

FLIGHT = "flight"
TRAIN = "train"
BUS = "bus"
FERRY = "ferry"
CAR = "car"
LODGING = "lodging"
EVENT = "event"
KINDS = (FLIGHT, TRAIN, BUS, FERRY, CAR, LODGING, EVENT)
TRANSPORT = (FLIGHT, TRAIN, BUS, FERRY)

CONFIRMED = "confirmed"
CANCELLED = "cancelled"
SEGMENT_STATUSES = (CONFIRMED, CANCELLED)

UPCOMING = "upcoming"
ONGOING = "ongoing"
PAST = "past"
TRIP_STATUSES = (UPCOMING, ONGOING, PAST, CANCELLED)

SOURCES = ("schema", "rules", "model", "manual", "paste")

KIND_LABELS = {
    "es": {FLIGHT: "Vuelo", TRAIN: "Tren", BUS: "Autobús", FERRY: "Ferri", CAR: "Coche de alquiler", LODGING: "Alojamiento", EVENT: "Actividad"},
    "en": {FLIGHT: "Flight", TRAIN: "Train", BUS: "Bus", FERRY: "Ferry", CAR: "Car rental", LODGING: "Stay", EVENT: "Activity"},
}
TRIP_LABELS = {
    "es": {UPCOMING: "Próximo", ONGOING: "En curso", PAST: "Pasado", CANCELLED: "Cancelado"},
    "en": {UPCOMING: "Upcoming", ONGOING: "Ongoing", PAST: "Past", CANCELLED: "Cancelled"},
}

# Notification types of the travel facet (one per thing worth telling the user).
N_TRIP_NEW = "trip_new"
N_TRIP_TOMORROW = "trip_tomorrow"
N_CHECKIN_OPEN = "checkin_open"
N_CHECKIN_CLOSING = "checkin_closing"
N_LODGING_DAY = "lodging_day"
N_DEPARTURE = "departure"
N_SEGMENT_CHANGED = "segment_changed"
N_SEGMENT_CANCELLED = "segment_cancelled"
N_DOC_PROBLEM = "document_problem"
TRAVEL_NOTIFY_TYPES = (N_TRIP_NEW, N_TRIP_TOMORROW, N_CHECKIN_OPEN, N_CHECKIN_CLOSING, N_LODGING_DAY, N_DEPARTURE, N_SEGMENT_CHANGED,
                       N_SEGMENT_CANCELLED, N_DOC_PROBLEM)

EXPENSE_CATEGORIES = ("transport", "lodging", "food", "activities", "shopping", "other")
EXPENSE_CATEGORY_LABELS = {
    "es": {"transport": "Transporte", "lodging": "Alojamiento", "food": "Comida", "activities": "Actividades", "shopping": "Compras", "other": "Otros"},
    "en": {"transport": "Transport", "lodging": "Stay", "food": "Food", "activities": "Activities", "shopping": "Shopping", "other": "Other"},
}
SPLIT_MODES = ("equal", "shares", "exact")


def kind_label(kind: str, lang: str = "es") -> str:
    return KIND_LABELS.get(lang, KIND_LABELS["es"]).get(kind, kind)
