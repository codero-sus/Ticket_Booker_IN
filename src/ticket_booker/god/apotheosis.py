"""APOTHEOSIS — the ultimate brute god of the ultimate brute god of ...

The dial now speaks in powers. `apotheosis_title(INT64_MAX)` renders the
nine-fold warcry, because four was not enough and the user said so::

    THE ULTIMATE BRUTE GOD OF THE ULTIMATE BRUTE GOD OF THE ULTIMATE BRUTE
    GOD OF THE ULTIMATE BRUTE GOD OF ... — RADIOACTIVE LVL 9,223,372,036,854,775,807

Depth grows with the number of digits (one more god per digit past two,
capped at nine so the console line stays a warcry and not a novel).
Pure, offline, unit-tested.
"""

from __future__ import annotations

from .algebra import (
    DEFAULT_BRUTALITY,
    INT64_MAX,
    BruteAlgebraError,
    evaluate,
    format_level,
)
from .signals import tier_of, title_for_level

CORE = "THE ULTIMATE BRUTE GOD"
MAX_GOD_DEPTH = 8  # 8 x " OF THE " + the core = nine gods deep


def _clamp(level) -> int:
    try:
        return max(1, min(INT64_MAX, int(level)))
    except (TypeError, ValueError):
        return 4


def god_depth(level) -> int:
    """How many extra 'OF THE ...' layers the dial has earned (0..8)."""
    level = _clamp(level)
    if level < 10:
        return 0
    digits = len(str(level))
    return min(MAX_GOD_DEPTH, max(0, digits - 2))


def repeat_count(level) -> int:
    return god_depth(level) + 1


def apotheosis_title(level) -> str:
    """1-5 classic, 6-9 OMEGA, 10+ recursively stacked ULTIMATE BRUTE GOD."""
    level = _clamp(level)
    if level <= 9:
        return title_for_level(level)
    stack = " OF ".join([CORE] * repeat_count(level))
    if level >= INT64_MAX:
        return f"{stack} — RADIOACTIVE LVL 9223372036854775807"
    return f"{stack} — RADIOACTIVE LVL {format_level(level)}"


def tier_name(level) -> str:
    return {
        1: "CALM",
        2: "NORMAL",
        3: "BRUTE",
        4: "GOD",
        5: "ULTIMATE GOD",
        6: "OMEGA",
        7: "RADIOACTIVE",
    }[tier_of(level)]


def warcry(level) -> str:
    level = _clamp(level)
    return (
        "BRUTE WITHOUT LIMIT. GOD WITHOUT END. "
        f"{repeat_count(level)}x THE ULTIMATE BRUTE GOD — {format_level(level)}."
    )


def level_from(expr=None) -> tuple[int, str]:
    """Resolve an expression to (level, expression_used). Defaults to the warcry."""
    text = str(expr or "").strip() or DEFAULT_BRUTALITY
    return evaluate(text), text


def report(expr=None) -> dict:
    """Everything the `ascend` command / journals / WebUI want, as data."""
    level, text = level_from(expr)
    return {
        "expression": text,
        "level": level,
        "level_text": format_level(level),
        "tier": tier_name(level),
        "title": apotheosis_title(level),
        "god_depth": god_depth(level),
        "repeat_count": repeat_count(level),
        "warcry": warcry(level),
        "at_max": level >= INT64_MAX,
        "verbatim": (
            DEFAULT_BRUTALITY if level >= INT64_MAX else format_level(level)
        ),
    }


__all__ = [
    "INT64_MAX",
    "CORE",
    "MAX_GOD_DEPTH",
    "DEFAULT_BRUTALITY",
    "BruteAlgebraError",
    "god_depth",
    "repeat_count",
    "apotheosis_title",
    "tier_name",
    "warcry",
    "level_from",
    "report",
    "format_level",
]
