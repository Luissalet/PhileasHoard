"""Europe/Madrid without depending on the OS tz database (Windows has none unless ``tzdata`` is installed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache


class _Madrid(tzinfo):
    """CET/CEST with the EU rule: summer time from the last Sunday of March 01:00 UTC to the last Sunday of October 01:00 UTC."""

    @staticmethod
    def _last_sunday(year: int, month: int) -> datetime:
        d = datetime(year, month + 1, 1) - timedelta(days=1) if month < 12 else datetime(year, 12, 31)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    def _is_dst_utc(self, utc: datetime) -> bool:
        start = self._last_sunday(utc.year, 3).replace(hour=1)
        end = self._last_sunday(utc.year, 10).replace(hour=1)
        naive = utc.replace(tzinfo=None)
        return start <= naive < end

    def utcoffset(self, dt):  # noqa: D401
        if dt is None:
            return timedelta(hours=1)
        guess = dt.replace(tzinfo=None) - timedelta(hours=1)
        return timedelta(hours=2) if self._is_dst_utc(guess) else timedelta(hours=1)

    def dst(self, dt):
        return self.utcoffset(dt) - timedelta(hours=1)

    def tzname(self, dt):
        return "CEST" if self.dst(dt) else "CET"

    def fromutc(self, dt):
        utc = dt.replace(tzinfo=None)
        offset = timedelta(hours=2) if self._is_dst_utc(utc) else timedelta(hours=1)
        return (utc + offset).replace(tzinfo=self)


@lru_cache(maxsize=1)
def madrid() -> tzinfo:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Madrid")
    except Exception:  # noqa: BLE001 — no tz database on this machine
        return _Madrid()


def utc() -> tzinfo:
    return timezone.utc
