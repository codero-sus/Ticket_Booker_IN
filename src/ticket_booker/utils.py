"""Shared helpers: logging, screenshots, retries, small utilities."""

from __future__ import annotations

import functools
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure root logging. Uses rich formatting when available."""
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return logging.getLogger("ticket_booker")
    try:
        from rich.logging import RichHandler

        handler = RichHandler(rich_tracebacks=True, show_time=True, show_path=False)
        fmt = "%(message)s"
    except Exception:  # pragma: no cover - rich is a hard dep, fallback is just safety
        handler = logging.StreamHandler()
        fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(level)
    return logging.getLogger("ticket_booker")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_screenshot(page, name: str, directory: str | Path = "./screenshots") -> Path | None:
    """Best-effort full-page screenshot. Returns path or None on failure."""
    log = logging.getLogger("ticket_booker.utils")
    try:
        out = ensure_dir(directory) / f"{timestamp()}_{name}.png"
        page.screenshot(path=str(out), full_page=True)
        log.debug("Screenshot saved: %s", out)
        return out
    except Exception as exc:  # never let screenshots break a booking run
        log.debug("Screenshot failed (%s): %s", name, exc)
        return None


def save_bytes(data: bytes, name: str, directory: str | Path) -> Path:
    out = ensure_dir(directory) / f"{timestamp()}_{name}"
    out.write_bytes(data)
    return out


def human_delay(min_s: float = 0.3, max_s: float = 1.2) -> None:
    """Randomised pause so automation doesn't look metronomic."""
    time.sleep(random.uniform(min_s, max_s))


def retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Simple retry decorator with exponential backoff."""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            wait = delay
            last: BaseException | None = None
            for i in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last = exc
                    if i < attempts - 1:
                        time.sleep(wait)
                        wait *= backoff
            assert last is not None
            raise last

        return wrapper

    return deco


def mask_secret(value: str | None, keep: int = 2) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)
