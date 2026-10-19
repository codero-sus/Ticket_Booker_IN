"""Pure signal helpers: fuzzy matching, block/session detection, backoff.

100% offline and unit-tested — no browser needed.
"""

from __future__ import annotations

import difflib
import random
import re

# Phrases meaning "the site is actively blocking us" (not just a dead session)
BLOCK_PHRASES = (
    "access denied",
    "403 forbidden",
    "request blocked",
    "blocked for security",
    "suspicious activity",
    "unusual traffic",
    "just a moment",  # bot-wall interstitial
    "attention required",
    "access to this page has been denied",
    "you have been blocked",
    "ip blocked",
    "too many requests",
)

# Phrases meaning "session died — just log in again"
SESSION_PHRASES = (
    "session expired",
    "session timed out",
    "session invalid",
    "logged out",
    "login again",
    "please login",
    "please log in",
    "sign in again",
)

BROWSER_DEATH_RE = re.compile(
    r"target closed|browser closed|browser has been closed|crash|disconnected"
    r"|navigating frame was detached|ns_error|ERR_SOCKET|ERR_CONNECTION_CLOSED",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def best_match(
    needle: str, options: list[str], cutoff: float = 0.62
) -> tuple[str, float] | None:
    """Fuzzy-match needle against options. Returns (original, score) or None."""
    n = normalize(needle)
    if not n:
        return None
    best: tuple[str, float] | None = None
    for opt in options:
        o = normalize(opt)
        if not o:
            continue
        # Fast paths: exact / containment (IRCTC loves "Submit »", "  SUBMIT ")
        if n == o:
            return (opt, 1.0)
        if n in o or o in n:
            score = 0.95
        else:
            score = difflib.SequenceMatcher(None, n, o).ratio()
        if score >= cutoff and (best is None or score > best[1]):
            best = (opt, score)
    return best


def detect_block(page_text: str) -> str | None:
    """Return the matched block phrase, or None if page looks fine."""
    low = (page_text or "").lower()
    for phrase in BLOCK_PHRASES:
        if phrase in low:
            return phrase
    return None


def detect_session_dead(page_text: str) -> bool:
    low = (page_text or "").lower()
    return any(p in low for p in SESSION_PHRASES)


def looks_like_browser_death(exc: BaseException | str) -> bool:
    return bool(BROWSER_DEATH_RE.search(str(exc)))


def escalate_delay(attempt: int, base: float = 1.5, cap: float = 25.0) -> float:
    """Jittered exponential backoff: 1.5s, 3s, 6s... capped."""
    raw = min(cap, base * (2 ** max(0, attempt - 1)))
    return raw * random.uniform(0.7, 1.3)
