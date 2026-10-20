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
  6-9 OMEGA — + HYDRA heads, adaptive pacer, cookie vault, ensemble captcha.
  10+ RADIOACTIVE — + verified clicks, strategy mutation, doomsday budget.
  APOTHEOSIS — BRUTE ALGEBRA levels (god of god of god of god = INT64_MAX),
                GENOME strategy DNA, CHRONOS warbell, `ascend` command.
"""

from .diagnostics import redact_config, redact_text, save_bundle
from .algebra import (
    DEFAULT_BRUTALITY,
    INT64_MAX,
    BruteAlgebraError,
    evaluate as evaluate_brutality,
    parse_level,
    try_parse_level,
)
from .apotheosis import (
    apotheosis_title,
    god_depth,
    level_from,
    report as apotheosis_report,
    tier_name,
    warcry,
)
from .chaos import DrillResult, run_drills
from .chronos import ChronosError, arm_until, parse_hhmm, seconds_until
from .genome import DEFAULT_ARMS, Genome
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
    "INT64_MAX",
    "DEFAULT_BRUTALITY",
    "BruteAlgebraError",
    "evaluate_brutality",
    "parse_level",
    "try_parse_level",
    "apotheosis_title",
    "apotheosis_report",
    "god_depth",
    "level_from",
    "tier_name",
    "warcry",
    "ChronosError",
    "arm_until",
    "parse_hhmm",
    "seconds_until",
    "DEFAULT_ARMS",
    "Genome",
]
