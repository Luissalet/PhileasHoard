"""Working days for delivery estimates: weekends, Spanish national holidays, an optional region and extra dates.

Carriers count "días laborables" Monday to Friday; some deliver on Saturday (and Amazon every day). ``Calendar``
answers "is this a delivery day for this carrier" and adds or counts delivery days between two dates.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable

# Carriers that deliver on these weekdays (0 = Monday). Everything else: Monday-Friday.
DELIVERY_WEEKDAYS = {
    "amazon": (0, 1, 2, 3, 4, 5, 6),
    "correos": (0, 1, 2, 3, 4, 5),
    "inpost": (0, 1, 2, 3, 4, 5),
}
DEFAULT_WEEKDAYS = (0, 1, 2, 3, 4)
REGIONS = ("", "ES-MD", "ES-CT", "ES-AN", "ES-VC", "ES-GA", "ES-PV")


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def holidays(year: int, region: str = "") -> frozenset[date]:
    """National holidays in Spain plus the most stable regional ones (moved Sunday holidays are not modelled)."""
    e = easter(year)
    days = {date(year, 1, 1), date(year, 1, 6), e - timedelta(days=2), date(year, 5, 1), date(year, 8, 15), date(year, 10, 12),
            date(year, 11, 1), date(year, 12, 6), date(year, 12, 8), date(year, 12, 25)}
    region = (region or "").upper()
    if region in ("ES-MD", "ES-AN", "ES-GA", "ES-PV", "ES-VC", "ES-CT"):
        if region != "ES-CT":
            days.add(e - timedelta(days=3))          # Holy Thursday
        else:
            days.add(e + timedelta(days=1))          # Easter Monday
    extra = {"ES-MD": [(5, 2)], "ES-CT": [(6, 24), (9, 11), (12, 26)], "ES-AN": [(2, 28)], "ES-VC": [(3, 19), (10, 9)],
             "ES-GA": [(5, 17), (7, 25)], "ES-PV": [(7, 25)]}
    for month, day in extra.get(region, []):
        days.add(date(year, month, day))
    return frozenset(days)


class Calendar:
    def __init__(self, region: str = "", extra: Iterable[date] = ()):
        self.region = region if region in REGIONS else ""
        self.extra = frozenset(extra)

    def is_holiday(self, day: date) -> bool:
        return day in holidays(day.year, self.region) or day in self.extra

    def is_delivery_day(self, day: date, carrier: str = "") -> bool:
        weekdays = DELIVERY_WEEKDAYS.get(carrier or "", DEFAULT_WEEKDAYS)
        if day.weekday() not in weekdays:
            return False
        # Amazon delivers on most holidays too; everyone else stops.
        return carrier == "amazon" or not self.is_holiday(day)

    def next_delivery_day(self, day: date, carrier: str = "") -> date:
        for _ in range(30):
            if self.is_delivery_day(day, carrier):
                return day
            day += timedelta(days=1)
        return day

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
