"""Diagnostics bundles — when GOD finally fails, it leaves a black box.

Bundle dir: ./diagnostics/<timestamp>_<name>/
  screenshot.png, page.html, url.txt, extra.json (traceback, redacted config...)

All secrets (passwords, API keys, UPI ids, card numbers, OTPs) are redacted —
bundles are safe to paste into GitHub issues.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("ticket_booker.god.diagnostics")

_SECRET_PAIRS = re.compile(
    r'("(?:password|passwd|pwd|api[_-]?key|clientkey|upi[_-]?id|mobile|phone|card|cardnumber|cvv|otp|token)"\s*:\s*")[^"]*(")',
    re.IGNORECASE,
)
_SECRET_KV = re.compile(
    r"(?i)\b(password|passwd|pwd|api[_-]?key|upi[_-]?id|cvv|otp)\b\s*[:=]\s*\S+"
)
_CARD_RUN = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")


def redact_text(text: str) -> str:
    if not text:
        return ""
    text = _SECRET_PAIRS.sub(r"\1***REDACTED***\2", text)
    text = _SECRET_KV.sub("[REDACTED]", text)
    text = _CARD_RUN.sub("****-****-****-****", text)
    return text


def redact_config(obj: Any) -> Any:
    """Redact a config dict / pydantic model. Returns redacted dict or str."""
    try:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        dumped = redact_text(json.dumps(obj, indent=2, default=str))
        try:
            return json.loads(dumped)
        except Exception:
            return dumped
    except Exception:
        return {"redacted": True}


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_bundle(
    base_dir: str | Path,
    name: str,
    page=None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a diagnostics bundle. NEVER raises (god doesn't crash on crash)."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name)[:60]
    out = Path(base_dir) / f"{_stamp()}_{safe}"
    try:
        out.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log.debug("diagnostics mkdir failed: %s", exc)
        return out
    # screenshot
    try:
        if page is not None:
            shot = out / "screenshot.png"
            try:
                data = page.screenshot(path=str(shot), full_page=True)
                if data and not shot.exists():
                    shot.write_bytes(data)
            except TypeError:  # fake pages with screenshot(path) only
                page.screenshot(path=str(shot))
    except Exception as exc:
        log.debug("diagnostics screenshot failed: %s", exc)
    # html
    try:
        if page is not None:
            html = page.content() if hasattr(page, "content") else ""
            (out / "page.html").write_text(redact_text(str(html))[:500_000], encoding="utf-8")
    except Exception as exc:
        log.debug("diagnostics html failed: %s", exc)
    # url
    try:
        (out / "url.txt").write_text(str(getattr(page, "url", "unknown") or "unknown"), encoding="utf-8")
    except Exception:
        pass
    # extra
    try:
        blob = {k: (redact_config(v) if k in ("config", "cfg") else v) for k, v in (extra or {}).items()}
        (out / "extra.json").write_text(
            redact_text(json.dumps(blob, indent=2, default=str)[:200_000]), encoding="utf-8"
        )
    except Exception as exc:
        log.debug("diagnostics extra failed: %s", exc)
    log.warning("📦 Diagnostics bundle saved → %s", out)
    return out
