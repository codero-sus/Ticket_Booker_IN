"""IST clock helpers, NTP sync and Tatkal countdown.

Tatkal booking opens 1 day before the journey date (excluding the date of
journey) at:
  * 10:00 IST for AC classes (1A/2A/3A/CC/EC/3E)
  * 11:00 IST for Non-AC classes (SL/2S/...)

For Tatkal, your system clock being even 5-10s slow can cost you the seat,
so :class:`NtpClock` measures the offset against public NTP servers and the
countdown compensates for it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

AC_CLASSES = {"1A", "2A", "3A", "CC", "EC", "EA", "3E", "EV", "VC", "VS"}
AC_TATKAL_HOUR = 10
NON_AC_TATKAL_HOUR = 11

NTP_SERVERS = ("time.google.com", "pool.ntp.org", "time.cloudflare.com")

log = logging.getLogger("ticket_booker.timing")


def now_ist() -> datetime:
    return datetime.now(IST)


def is_ac_class(class_code: str) -> bool:
    return class_code.strip().upper() in AC_CLASSES


def parse_journey_date(value: str | date) -> date:
    """Accept YYYY-MM-DD, DD-MM-YYYY or DD/MM/YYYY."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Unrecognised journey date {value!r}. Use YYYY-MM-DD (e.g. 2026-10-20)."
    )


def tatkal_open_datetime(journey_date: date, class_code: str) -> datetime:
    """When Tatkal opens for a given journey date + class (IST, tz-aware).

    Note: IRCTC counts the opening day from the *train's source-station
    starting date*. For most bookings that equals journey_date - 1 day.
    If you board at an intermediate station where the train arrives a day
    later, set your config date to the train's source starting date.
    """
    hour = AC_TATKAL_HOUR if is_ac_class(class_code) else NON_AC_TATKAL_HOUR
    opening_day = journey_date - timedelta(days=1)
    return datetime(
        opening_day.year, opening_day.month, opening_day.day, hour, 0, 0, tzinfo=IST
    )


def measure_ntp_offset(
    servers: tuple[str, ...] = NTP_SERVERS, timeout: int = 5
) -> float:
    """Seconds to ADD to the local clock to get true time. 0.0 on failure."""
    try:
        import ntplib
    except ImportError:
        log.warning("ntplib not installed; skipping NTP sync (offset=0).")
        return 0.0
    client = ntplib.NTPClient()
    for server in servers:
        try:
            resp = client.request(server, version=3, timeout=timeout)
            log.info("NTP sync via %s: offset %+0.3fs", server, resp.offset)
            return float(resp.offset)
        except Exception as exc:
            log.debug("NTP %s failed: %s", server, exc)
    log.warning("All NTP servers unreachable; using local clock (offset=0).")
    return 0.0


@dataclass
class NtpClock:
    """Clock with a cached NTP offset."""

    offset: float = 0.0

    def sync(self) -> float:
        self.offset = measure_ntp_offset()
        return self.offset

    def now(self) -> datetime:
        return now_ist() + timedelta(seconds=self.offset)


def countdown_until(
    target: datetime,
    clock: NtpClock | None = None,
    tick: float = 0.5,
    on_tick: Callable[[float], None] | None = None,
) -> None:
    """Sleep until `target` (tz-aware). Compensates NTP offset; the last
    2 seconds use a tight loop for precision."""
    clock = clock or NtpClock()
    while True:
        remaining = (target - clock.now()).total_seconds()
        if remaining <= 0:
            return
        if on_tick is not None:
            on_tick(remaining)
        if remaining > 2.5:
            time.sleep(min(tick, remaining - 2.0))
        else:
            time.sleep(0.05)  # precision finish


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"
