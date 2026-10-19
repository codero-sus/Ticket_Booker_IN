"""God engine — the relaunch ladder around any browser run.

`god_run()` wraps a whole browser session (`fn(ctx)`). If the browser dies
(crash / target closed / disconnect) or the IP gets blocked, GOD doesn't
give up: it relaunches a FRESH browser and retries, rotating proxies when
configured. Tool-logic errors (bad PNR, no trains) are NOT retried here —
those are already handled by BruteContext.brute() inside the session.
"""

from __future__ import annotations

import logging
import time

from .signals import escalate_delay, looks_like_browser_death

log = logging.getLogger("ticket_booker.god.engine")

# Fresh-browser rounds per brutality level
ROUNDS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4}


def _level(cfg) -> int:
    try:
        return int(getattr(getattr(cfg, "brute", None), "level", 3) or 3)
    except (TypeError, ValueError):
        return 3


def god_run(cfg, headless: bool | None, fn, _runner=None):
    """Run fn(ctx) with fresh-browser relaunch + proxy rotation.

    `_runner` is injectable for tests: _runner(cfg, headless, fn) -> result.
    """
    from ..tools.base import BlockedError, _plain_run

    level = _level(cfg)
    runner = _runner or _plain_run
    rounds = ROUNDS.get(level, 2)
    proxies = list(getattr(getattr(cfg, "brute", None), "proxy_list", None) or [])
    proxy_idx = 0
    last: Exception | None = None

    for rnd in range(1, rounds + 1):
        try:
            if rnd > 1:
                log.warning("🔥 GOD round %d/%d — fresh browser rising...", rnd, rounds)
            return runner(cfg, headless, fn)
        except BlockedError as exc:
            last = exc
            log.error("🚫 Blocked (%s).", exc.reason)
            if proxies:
                proxy = proxies[proxy_idx % len(proxies)]
                proxy_idx += 1
                try:
                    cfg.browser.proxy = dict(proxy)
                except Exception:
                    pass
                log.warning("🔄 Rotating proxy (%d/%d) and relaunching...",
                            proxy_idx, len(proxies))
            elif rnd < rounds:
                wait = escalate_delay(rnd + 2, base=5.0, cap=60.0)
                log.warning("⏳ No proxies configured; cooling down %.0fs...", wait)
                time.sleep(wait)
        except Exception as exc:
            last = exc
            if looks_like_browser_death(exc) and rnd < rounds:
                log.error("💀 Browser died (%s) — relaunching fresh...", str(exc)[:120])
                time.sleep(escalate_delay(rnd, base=2.0, cap=15.0))
                continue
            raise  # tool-logic error: handled inside the session, don't loop here

    assert last is not None
    raise last
