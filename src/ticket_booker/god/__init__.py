"""ULTIMATE BRUTE GOD — the resilience layer that refuses to die.

  * :mod:`signals` — fuzzy text matching, block/session-death detection, backoff.
  * :mod:`memory` — SelectorMemory: remembers which locator strategy worked and
    tries winners first (persisted across runs).
  * :mod:`diagnostics` — secret-redacted failure bundles (screenshot + HTML + URL).
  * :mod:`engine` — god_run: relaunch ladder + proxy rotation around any browser run.

Brutality levels (config `brute.level`, CLI `--brutality`, WebUI selector):
  1 calm — minimal retries, for debugging.
  2 normal — classic behavior.
  3 BRUTE — + selector memory, fuzzy fallback, diagnostics.
  4 GOD (default) — + block detection, session keepalive, browser-relaunch ladder.
  5 ULTIMATE GOD — + max retries, screenshot every step, proxy rotation, no mercy.
"""

from .diagnostics import redact_config, redact_text, save_bundle
from .chaos import DrillResult, run_drills
from .engine import god_run
from .journal import Journal
from .preflight import PreflightResult, preflight
from .hydra import heads_for, hydra_race
from .pacer import Pacer
from .session_vault import load_vault, save_vault, vault_status
from .memory import SelectorMemory
from .signals import (
    best_match,
    detect_block,
    detect_session_dead,
    escalate_delay,
    looks_like_browser_death,
    normalize,
    tier_of,
    title_for_level,
)

__all__ = [
    "SelectorMemory",
    "best_match",
    "detect_block",
    "detect_session_dead",
    "diagnostics",
    "escalate_delay",
    "god_run",
    "DrillResult",
    "run_drills",
    "Journal",
    "PreflightResult",
    "preflight",
    "heads_for",
    "hydra_race",
    "Pacer",
    "load_vault",
    "save_vault",
    "vault_status",
    "looks_like_browser_death",
    "normalize",
    "tier_of",
    "title_for_level",
    "redact_config",
    "redact_text",
    "save_bundle",
]
