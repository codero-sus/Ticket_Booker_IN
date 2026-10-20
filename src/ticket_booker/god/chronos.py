"""CHRONOS — the WARBELL. Arm the run at 09:59:55 and walk away.

Tatkal opens at 10:00:00 sharp. Humans set alarms, oversleep, and fumble
passwords. Gods arm a bell::

    "brute": {"arm_at": "09:59:55", "arm_lead_seconds": 5}

`arm_until()` sleeps in chunks until the wall clock reaches the target,
logging a countdown, and then the browser launches. No cron, no systemd,
no second terminal — the booking process itself is the alarm clock.

Pure time math + unit-tested. `sleep_fn` is injectable, so tests never wait.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

log = logging.getLogger("ticket_booker.god.chronos")


class ChronosError(ValueError):
    """Bad arm time (the bell cannot ring at 25:99)."""


def parse_hhmm(text) -> tuple[int, int, int]:
    """Accept '10:00', '10.00', '1000', '9:59:55', '10' -> (h, m, s)."""
    raw = str(text or "").strip().replace(".", ":").replace("_", ":")
    if not raw:
        raise ChronosError("empty arm time")
    parts = raw.split(":")
    try:
        if len(parts) == 1:
            token = parts[0]
            if not token.isdigit():
                raise ChronosError(f"bad arm time {text!r}")
            if len(token) <= 2:
                h, m, s = int(token), 0, 0
            elif len(token) in (3, 4):
                h, m, s = int(token[:-2]), int(token[-2:]), 0
            elif len(token) in (5, 6):
                h, m, s = int(token[:-4]), int(token[-4:-2]), int(token[-2:])
            else:
                raise ChronosError(f"bad arm time {text!r}")
        elif len(parts) in (2, 3):
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) == 3 else 0
        else:
            raise ChronosError(f"bad arm time {text!r}")
    except ValueError as exc:
        raise ChronosError(f"bad arm time {text!r}") from exc
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        raise ChronosError(f"bad arm time {text!r} (expected HH:MM[:SS])")
    return h, m, s


def next_arm_datetime(text, now: datetime | None = None) -> datetime:
    """The next occurrence of HH:MM[:SS] (today, else tomorrow)."""
    now = now or datetime.now()
    h, m, s = parse_hhmm(text)
    target = now.replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def seconds_until(text, now: datetime | None = None, lead: float = 0.0) -> float:
    """Seconds until the bell, minus the lead (never negative)."""
    now = now or datetime.now()
    seconds = (next_arm_datetime(text, now) - now).total_seconds()
    seconds -= max(0.0, float(lead or 0.0))
    return max(0.0, seconds)


def wait(seconds: float, sleep_fn=time.sleep, on_tick=None,
         chunk: float = 30.0) -> float:
    """Sleep in short chunks (Ctrl-C friendly). Returns seconds slept."""
    remaining = max(0.0, float(seconds or 0.0))
    total = remaining
    chunk = max(0.05, float(chunk or 30.0))
    while remaining > 0:
        step = min(chunk, remaining)
        sleep_fn(step)
        remaining -= step
        if on_tick is not None:
            try:
                on_tick(remaining)
            except Exception:
                pass
    return total


def arm_until(text, lead: float = 5.0, now_fn=datetime.now, sleep_fn=time.sleep,
              on_tick=None, chunk: float = 30.0) -> float:
    """Block until HH:MM[:SS] minus `lead`. Returns seconds waited.

    Never raises on an empty value (returns 0.0) so a blank config cannot
    kill a run. A malformed value raises ChronosError — preflight catches it.
    """
    raw = str(text or "").strip()
    if not raw:
        return 0.0
    seconds = seconds_until(raw, now=now_fn(), lead=lead)
    if seconds <= 0:
        return 0.0
    log.info("⏰ WARBELL armed for %s — waiting %s (lead %.0fs)",
             raw, _human(seconds), float(lead or 0.0))
    waited = wait(seconds, sleep_fn=sleep_fn, on_tick=on_tick, chunk=chunk)
    log.info("🔔 WARBELL fired — GO GO GO")
    return waited


def _human(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


__all__ = [
    "ChronosError",
    "parse_hhmm",
    "next_arm_datetime",
    "seconds_until",
    "wait",
    "arm_until",
]
