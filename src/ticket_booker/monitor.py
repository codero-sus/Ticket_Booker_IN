"""LIVE MONITOR — watch the booking happen, without touching it.

The autopilot is hands-free, which is only comfortable if you can *see* it.
This module keeps two things in memory while a run is going:

* a rolling **event log** (``login -> search -> select -> fill -> pay -> PNR``)
* the latest **screenshot frames** from the live page

A tiny popup page (``/monitor`` in the WebUI) polls both and renders them, so a
small window floats next to whatever you are doing showing exactly what the
browser is doing.

THREAD SAFETY
-------------
Playwright's sync API is not thread-safe per page, so frames are captured by
the thread that *owns* the page (the booking thread) and only the resulting
JPEG bytes are handed to other threads. Everything shared here is plain data
guarded by an ``RLock``; no Playwright object is ever touched under it.

Nothing in this module raises into a booking: a broken page, a failed capture
or a missing Pillow all degrade to "no frame yet".
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque

log = logging.getLogger("ticket_booker.monitor")

DEFAULT_MAX_EVENTS = 300
DEFAULT_MAX_FRAMES = 6
SNAPSHOT_QUALITY = 62


@dataclass
class Event:
    """One line in the live log."""

    at: str
    elapsed: float
    step: str
    detail: str = ""
    level: str = "info"

    def as_dict(self) -> dict:
        return {
            "at": self.at,
            "elapsed": round(self.elapsed, 2),
            "step": self.step,
            "detail": self.detail,
            "level": self.level,
        }


@dataclass
class Frame:
    seq: int
    at: str
    label: str
    data: bytes
    url: str = ""
    title: str = ""

    def as_dict(self) -> dict:
        return {
            "seq": self.seq,
            "at": self.at,
            "label": self.label,
            "bytes": len(self.data),
            "url": self.url,
            "title": self.title,
        }


@dataclass
class Monitor:
    """In-memory live view of one booking run."""

    max_events: int = DEFAULT_MAX_EVENTS
    max_frames: int = DEFAULT_MAX_FRAMES
    quality: int = SNAPSHOT_QUALITY

    running: bool = field(default=False, init=False)
    task: str = field(default="", init=False)
    step: str = field(default="", init=False)
    ok: bool | None = field(default=None, init=False)
    message: str = field(default="", init=False)
    pnr: str = field(default="", init=False)
    started_at: str = field(default="", init=False)
    started_monotonic: float = field(default=0.0, init=False)
    finished_monotonic: float = field(default=0.0, init=False)
    frame_seq: int = field(default=0, init=False)

    _events: Deque[Event] = field(default_factory=deque, init=False, repr=False)
    _frames: Deque[Frame] = field(default_factory=deque, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def begin(self, task: str = "booking", detail: str = "") -> None:
        with self._lock:
            self._events.clear()
            self._frames.clear()
            self.running = True
            self.task = task
            self.step = "starting"
            self.ok = None
            self.message = ""
            self.pnr = ""
            self.started_at = _clock()
            self.started_monotonic = time.monotonic()
            self.finished_monotonic = 0.0
            self.frame_seq = 0
        self.step_now("armed", detail or task)

    def finish(self, ok: bool, message: str = "", pnr: str = "") -> None:
        with self._lock:
            self.running = False
            self.ok = bool(ok)
            self.message = message
            self.pnr = pnr
            self.finished_monotonic = time.monotonic()
        self.step_now("finished" if ok else "failed", message, level="ok" if ok else "error")

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._frames.clear()
            self.running = False
            self.task = ""
            self.step = ""
            self.ok = None
            self.message = ""
            self.pnr = ""
            self.frame_seq = 0

    # ------------------------------------------------------------------ #
    # events
    # ------------------------------------------------------------------ #

    def _elapsed(self) -> float:
        started = self.started_monotonic
        if not started:
            return 0.0
        ref = self.finished_monotonic or time.monotonic()
        return max(0.0, ref - started)

    def step_now(self, step: str, detail: str = "", level: str = "info") -> Event:
        """Record a step. Safe from any thread (no browser objects involved)."""
        with self._lock:
            self.step = step
            event = Event(_clock(), self._elapsed(), step, detail, level)
            self._events.append(event)
            while len(self._events) > self.max_events:
                self._events.popleft()
        log.info("[%s] %s%s", step, detail, "" if level == "info" else f" ({level})")
        return event

    # backward/readability aliases
    step_event = step_now
    mark = step_now

    def events(self, limit: int = 60) -> list[dict]:
        with self._lock:
            items = list(self._events)
        if limit and len(items) > limit:
            items = items[-limit:]
        return [e.as_dict() for e in items]

    # ------------------------------------------------------------------ #
    # frames (MAIN THREAD ONLY — this touches the page)
    # ------------------------------------------------------------------ #

    def snapshot(self, page, label: str = "", force: bool = False) -> bool:
        """Capture a JPEG frame from the live page. Call from the owning thread.

        Returns True when a frame was stored. Never raises.
        """
        if page is None:
            return False
        try:
            if not self.running and not force:
                return False
        except Exception:
            pass
        try:
            data = page.screenshot(type="jpeg", quality=self.quality, timeout=8000)
        except TypeError:
            try:
                data = page.screenshot(type="jpeg", quality=self.quality)
            except Exception as exc:
                log.debug("monitor snapshot failed: %s", exc)
                return False
        except Exception as exc:
            log.debug("monitor snapshot failed: %s", exc)
            return False
        if not data:
            return False

        url, title = "", ""
        try:
            url = str(getattr(page, "url", "") or "")
        except Exception:
            url = ""
        try:
            title = str(page.title() or "")[:120]
        except Exception:
            title = ""

        with self._lock:
            self.frame_seq += 1
            frame = Frame(self.frame_seq, _clock(), label or self.step, data, url, title)
            self._frames.append(frame)
            while len(self._frames) > self.max_frames:
                self._frames.popleft()
        return True

    snap = snapshot

    def frame(self) -> tuple[bytes, int]:
        """Latest frame bytes and its sequence number (b'', 0 when empty)."""
        with self._lock:
            if not self._frames:
                return b"", 0
            latest = self._frames[-1]
            return latest.data, latest.seq

    def latest_frame(self) -> Frame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    # ------------------------------------------------------------------ #
    # state for the popup
    # ------------------------------------------------------------------ #

    def state(self, limit: int = 60) -> dict[str, Any]:
        with self._lock:
            busy = self.running
            payload = {
                "running": busy,
                "task": self.task,
                "step": self.step,
                "ok": self.ok,
                "message": self.message,
                "pnr": self.pnr,
                "started_at": self.started_at,
                "elapsed": round(self._elapsed(), 1),
                "frame_seq": self.frame_seq,
                "frame_count": len(self._frames),
                "events": [e.as_dict() for e in list(self._events)[-limit:]],
            }
        return payload


def _clock() -> str:
    return time.strftime("%H:%M:%S")


#: Process-wide monitor. The CLI and the WebUI both read this one object.
MONITOR = Monitor()


def get_monitor() -> Monitor:
    return MONITOR


__all__ = [
    "Event",
    "Frame",
    "Monitor",
    "MONITOR",
    "get_monitor",
    "DEFAULT_MAX_EVENTS",
    "DEFAULT_MAX_FRAMES",
]
