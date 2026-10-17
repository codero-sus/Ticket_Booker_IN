"""Camoufox stealth-browser launcher.

Why Camoufox for IRCTC?
  * Real Firefox with anti-fingerprinting (IRCTC sits behind bot checks that
    flag plain Selenium/Playwright-Chromium quickly).
  * `humanize=True` moves the mouse on human-like curves instead of teleporting.
  * Persistent profile keeps your IRCTC session/cookies between runs, so you
    can log in once and reuse the session for Tatkal day.
  * Indian locale/timezone/geolocation keeps the fingerprint coherent.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .config import BrowserCfg
from .utils import ensure_dir

log = logging.getLogger("ticket_booker.browser")


@dataclass
class BrowserSession:
    """Persistent-context session. `context` IS the browser (Camoufox
    persistent_context=True returns a BrowserContext)."""

    context: Any
    page: Any
    profile_dir: Path


def _has_display() -> bool:
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def build_launch_options(cfg: BrowserCfg, headless: bool | None = None) -> dict[str, Any]:
    headless = cfg.headless if headless is None else headless
    profile_dir = ensure_dir(cfg.profile_dir)

    # On headless Linux servers, use Camoufox's virtual display (Xvfb) so the
    # site still sees a headed browser (much harder to flag than headless).
    headless_opt: Any = headless
    if headless and sys.platform.startswith("linux") and not _has_display():
        headless_opt = "virtual"
        log.info("No display detected; using Camoufox virtual display (Xvfb).")

    humanize: Any = cfg.humanize
    if isinstance(humanize, bool):
        humanize = True if humanize else False
    else:
        humanize = max(0.2, min(float(humanize), 5.0))

    options: dict[str, Any] = {
        "persistent_context": True,
        "user_data_dir": str(profile_dir.resolve()),
        "headless": headless_opt,
        "humanize": humanize,
        "locale": cfg.locale,
        "timezone_id": cfg.timezone,
        "geolocation": {
            "latitude": cfg.geolocation.latitude,
            "longitude": cfg.geolocation.longitude,
        },
        "os": "windows",  # most common real-user fingerprint in India
        "enable_cache": True,  # faster repeat loads (train refresh loops)
        "block_images": cfg.block_images,
    }
    if cfg.proxy:
        options["proxy"] = dict(cfg.proxy)
        options["geoip"] = True  # derive tz/locale from proxy exit IP
    if cfg.addons:
        missing = [a for a in cfg.addons if not Path(a).exists()]
        if missing:
            log.warning("Addon files not found, skipping: %s", missing)
        options["addons"] = [a for a in cfg.addons if Path(a).exists()]
    return options


@contextmanager
def launch_browser(
    cfg: BrowserCfg, headless: bool | None = None
) -> Iterator[BrowserSession]:
    """Launch Camoufox and yield a session with one open page."""
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as exc:
        raise RuntimeError(
            "camoufox is not installed. Run: pip install -r requirements.txt"
        ) from exc

    options = build_launch_options(cfg, headless)
    profile_dir = Path(options["user_data_dir"])
    log.info(
        "Launching Camoufox (profile=%s, headless=%s, humanize=%s)",
        profile_dir,
        options["headless"],
        options["humanize"],
    )
    try:
        with Camoufox(**options) as context:
            pages = list(context.pages) if hasattr(context, "pages") else []
            page = pages[0] if pages else context.new_page()
            # Sensible defaults for a booking race: don't hang forever.
            try:
                page.set_default_timeout(15000)
                page.set_default_navigation_timeout(45000)
            except Exception:
                pass
            yield BrowserSession(context=context, page=page, profile_dir=profile_dir)
    except Exception as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg or "fetch" in msg.lower():
            raise RuntimeError(
                "Camoufox browser binaries missing. Run: camoufox fetch"
            ) from exc
        raise
