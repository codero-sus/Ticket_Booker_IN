"""HYDRA — N parallel browser heads race the same TOOL; first success wins.

Cut off one head, two more take its place. Each head is a FULLY INDEPENDENT
Camoufox browser (own thread, own profile dir, own proxy) so a crash, ban or
captcha-loop in one head never touches the others. First head returning
ok=True wins; the rest are abandoned (daemon threads, die with the run).

HYDRA IS FOR TOOLS ONLY (reads + fare dry-runs). Booking stays single-headed
on purpose — parallel bookings could double-book and double-charge you.
`run_with_browser()` only routes tools here; `IRCTCBooker.book()` never is.
"""

from __future__ import annotations

import logging
import threading
import time

from .signals import tier_of

log = logging.getLogger("ticket_booker.god.hydra")

MAX_HEADS = 3  # physics + politeness: never nuke IRCTC with more
HEADS_BY_TIER = {6: 2, 7: 3}


def heads_for(cfg) -> int:
    """How many heads this config wants (1 below OMEGA tier)."""
    try:
        brute = getattr(cfg, "brute", None)
        level = int(getattr(brute, "level", 3) or 3)
        want = int(getattr(brute, "hydra_heads", 0) or 0)
    except (TypeError, ValueError):
        return 1
    if tier_of(level) < 6:
        return 1
    if want <= 0:
        want = HEADS_BY_TIER.get(tier_of(level), 2)
    return max(1, min(MAX_HEADS, want))


def _fork_config(cfg, head: int):
    """Per-head config: own profile dir + round-robin proxy."""
    hcfg = cfg.model_copy(deep=True)
    try:
        base = str(hcfg.browser.profile_dir).rstrip("/")
        hcfg.browser.profile_dir = f"{base}.hydra{head}"
    except Exception:
        pass
    try:
        proxies = list(getattr(hcfg.brute, "proxy_list", None) or [])
        if proxies:
            hcfg.browser.proxy = dict(proxies[head % len(proxies)])
    except Exception:
        pass
    return hcfg


def hydra_race(cfg, headless: bool | None, fn, _runner=None):
    """Race `fn(ctx)` across heads. Returns the winning result.

    `_runner(hcfg, headless, fn)` injectable for tests (default: fresh browser
    per head via `_plain_run`). Winner = first ok=True in FINISH order;
    if every head fails, returns the first finished result.
    """
    from ..tools.base import _plain_run

    runner = _runner or _plain_run
    n = heads_for(cfg)
    if n <= 1:
        return runner(cfg, headless, fn)

    try:
        budget = float(getattr(getattr(cfg, "brute", None), "max_tool_minutes", 0) or 0)
    except (TypeError, ValueError):
        budget = 0.0
    deadline = time.time() + budget * 60 if budget > 0 else None

    results: dict[int, object] = {}
    order: list[int] = []
    lock = threading.Lock()
    stop = threading.Event()

    def _head(i: int) -> None:
        if stop.is_set():
            return
        try:
            hcfg = _fork_config(cfg, i)
            log.warning("🐲 HYDRA head %d/%d rising...", i + 1, n)
            res = runner(hcfg, headless, fn)
        except Exception as exc:  # a head dying must never kill the race
            log.error("🐲 HYDRA head %d died: %s", i + 1, str(exc)[:150])
            res = None
        with lock:
            if res is not None:
                results[i] = res
                order.append(i)
                if bool(getattr(res, "ok", False)):
                    stop.set()

    threads = [threading.Thread(target=_head, args=(i,), daemon=True, name=f"hydra-{i}") for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        if deadline is None:
            t.join()
        else:
            t.join(timeout=max(0.1, deadline - time.time()))

    with lock:
        for i in order:  # winner: first SUCCESS in finish order
            if bool(getattr(results[i], "ok", False)):
                log.warning("🏆 HYDRA head %d WINS.", i + 1)
                return results[i]
        if order:
            log.warning("🐲 All HYDRA heads failed — returning head %d's report.", order[0] + 1)
            return results[order[0]]
    raise TimeoutError("HYDRA: every head timed out with no result.")
