"""DEMO reel — drive the LIVE popup without touching IRCTC.

The monitor is only convincing when it is moving. This module plays a scripted
booking sequence into the :class:`~ticket_booker.monitor.Monitor` and draws
synthetic frames, so you can see exactly what the popup looks like during a
real run without a browser, a network or an IRCTC login.

Everything is labelled ``demo``: no ticket is booked, no PNR is real.
"""

from __future__ import annotations

import io
import logging
import threading
import time

from .monitor import Monitor, get_monitor

log = logging.getLogger("ticket_booker.demo")

DEMO_PNR = "0000000000"

SCRIPT: list[tuple[float, str, str, str]] = [
    (0.6, "login", "opening IRCTC login form", "info"),
    (1.2, "login", "filling credentials (from config)", "info"),
    (1.0, "login", "captcha detected - Gemini/Buster solving", "info"),
    (1.3, "login", "signed in", "ok"),
    (0.8, "search", "NDLS -> BCT on journey date", "info"),
    (1.5, "search", "train list loaded", "ok"),
    (0.9, "select", "choosing train + class", "info"),
    (1.2, "select", "availability confirmed - seat held", "ok"),
    (0.8, "passengers", "filling passenger details", "info"),
    (1.0, "passengers", "continued to review page", "ok"),
    (0.8, "captcha", "review captcha solved", "ok"),
    (1.0, "payment", "UPI selected, id pre-filled", "info"),
    (1.2, "payment", "payment submitted (no PIN/OTP typed)", "info"),
    (2.0, "waiting", "waiting for bank approval on the phone", "warn"),
    (1.4, "booked", f"PNR {DEMO_PNR} (demo)", "ok"),
]

SCREENS = {
    "login": ("IRCTC - LOGIN", "username  ••••••   captcha  [ OK ]"),
    "search": ("IRCTC - TRAIN SEARCH", "NDLS -> BCT   12951 / 3A / GN"),
    "select": ("IRCTC - SELECT CLASS", "12951 MUMBAI RAJDHANI   AVAILABLE-0042"),
    "passengers": ("IRCTC - PASSENGERS", "1 passenger   berth: LB"),
    "captcha": ("IRCTC - REVIEW", "captcha accepted   [ CONTINUE ]"),
    "payment": ("IRCTC - PAYMENT", "BHIM/UPI   you@upi   [ PAY & BOOK ]"),
    "waiting": ("IRCTC - AWAITING BANK", "approve the collect request on your phone"),
    "booked": ("IRCTC - BOOKED", f"PNR {DEMO_PNR}"),
}

_LOCK = threading.Lock()
_RUNNING = False


def _draw(title: str, line: str) -> bytes:
    """A synthetic 'browser screenshot' so the popup has something to show."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return b""
    w, h = 720, 460
    img = Image.new("RGB", (w, h), (18, 24, 36))
    d = ImageDraw.Draw(img)
    # browser chrome
    d.rectangle([0, 0, w, 44], fill=(34, 45, 66))
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([14 + i * 20, 16, 26 + i * 20, 28], fill=colour)
    d.rectangle([84, 12, w - 16, 32], fill=(22, 30, 46))
    d.text((94, 16), "irctc.co.in", fill=(150, 168, 196))
    # header band
    d.rectangle([0, 44, w, 96], fill=(26, 34, 52))
    d.text((24, 62), "IRCTC  |  " + title, fill=(255, 176, 32))
    # body text
    d.text((24, 140), line, fill=(232, 237, 247))
    d.text((24, 180), "DEMO FRAME - no real booking", fill=(120, 136, 160))
    # a fake progress bar that advances with the script
    d.rectangle([24, h - 60, w - 24, h - 40], fill=(28, 38, 58))
    progress = min(1.0, (abs(hash(title)) % 70 + 30) / 100.0)
    d.rectangle([24, h - 60, 24 + int((w - 48) * progress), h - 40],
                fill=(55, 214, 122))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


class _FramePage:
    """Minimal page stand-in so `Monitor.snapshot()` can be reused verbatim."""

    def __init__(self, blob: bytes, label: str):
        self.blob = blob
        self.label = label
        self.url = "https://www.irctc.co.in/nget/train-search"
        self._title = f"IRCTC - {label}"

    def screenshot(self, type="jpeg", quality=60, timeout=None):
        return self.blob

    def title(self):
        return self._title


def start_demo(monitor: Monitor | None = None, speed: float = 1.0) -> bool:
    """Play the scripted sequence into the monitor. Returns False if busy."""
    global _RUNNING
    m = monitor if monitor is not None else get_monitor()
    with _LOCK:
        if _RUNNING:
            return False
        _RUNNING = True

    def _play() -> None:
        global _RUNNING
        try:
            m.begin("demo", detail="scripted run - nothing is really booked")
            for delay, step, detail, level in SCRIPT:
                time.sleep(max(0.0, delay / max(0.1, speed)))
                m.step_now(step, f"{detail} (demo)", level=level)
                title, line = SCREENS.get(step, ("IRCTC", step))
                blob = _draw(title, line)
                if blob:
                    m.snapshot(_FramePage(blob, step), step)
            m.finish(True, f"DEMO complete - no ticket was booked (fake PNR {DEMO_PNR})",
                     pnr=DEMO_PNR)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("demo reel failed: %s", exc)
            m.finish(False, f"demo failed: {exc}")
        finally:
            with _LOCK:
                _RUNNING = False

    threading.Thread(target=_play, daemon=True, name="tb-demo").start()
    return True


def demo_running() -> bool:
    return _RUNNING


__all__ = ["start_demo", "demo_running", "SCRIPT", "DEMO_PNR"]
