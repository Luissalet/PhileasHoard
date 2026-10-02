"""Working days for delivery estimates: weekends, Spanish holidays, an optional region and extra dates.

Holidays, Easter and business-day arithmetic come from ``hoard_link.bizdays``. What stays here is what only a delivery
estimate needs: which weekdays each carrier delivers on (Correos and InPost on Saturday, Amazon every day, even on
holidays) and counting delivery days between two dates.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .hoard_link.bizdays import REGIONS as _REGION_TABLE, Calendar as _Calendar, easter, holidays  # noqa: F401

# Carriers that deliver on these weekdays (0 = Monday). Everything else: Monday-Friday.
DELIVERY_WEEKDAYS = {
    "amazon": (0, 1, 2, 3, 4, 5, 6),
    "correos": (0, 1, 2, 3, 4, 5),
    "inpost": (0, 1, 2, 3, 4, 5),
}
DEFAULT_WEEKDAYS = (0, 1, 2, 3, 4)
REGIONS = ("", *_REGION_TABLE)


class Calendar(_Calendar):
    """The shared calendar with the delivery rules of this app. ``region`` "" (or an unknown one) is the national calendar."""

    def __init__(self, region: str = "", extra: Iterable[date] = ()):
        super().__init__(region if region in REGIONS and region else "ES", extra)

    def is_delivery_day(self, day: date, carrier: str = "") -> bool:
        weekdays = DELIVERY_WEEKDAYS.get(carrier or "", DEFAULT_WEEKDAYS)
        if day.weekday() not in weekdays:
            return False
        # Amazon delivers on most holidays too; everyone else stops.
        return carrier == "amazon" or not self.is_holiday(day)

    def next_delivery_day(self, day: date, carrier: str = "", *, include_self: bool = True) -> date:  # type: ignore[override]
        """The first delivery day on or after ``day`` (after it with ``include_self=False``)."""
        return super().next_delivery_day(day, carrier, include_self=include_self)

    def add(self, start: date, days: int, carrier: str = "") -> date:
        """The delivery day ``days`` delivery days after ``start`` (0 = the next delivery day on or after start)."""
        current = self.next_delivery_day(start, carrier) if days <= 0 else start
        remaining = max(0, int(days))
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_delivery_day(current, carrier):
                remaining -= 1
        return current

    def count(self, start: date, end: date, carrier: str = "") -> int:
        """Delivery days after ``start`` up to and including ``end`` (0 when end <= start)."""
        if end <= start:
            return 0
        n, current = 0, start
        while current < end:
            current += timedelta(days=1)
            if self.is_delivery_day(current, carrier):
                n += 1
        return n
