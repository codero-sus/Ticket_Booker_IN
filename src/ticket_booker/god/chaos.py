"""CHAOS drills — prove GOD survives cascading disasters (offline, scripted).

`ticket-booker chaos` unleashes scripted calamities against fake pages:
flaky actions, browser death, block walls, session rot, doomsday budgets.
If GOD BLEEDS, you see FAIL. Currently: GOD SURVIVES.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest import mock

log = logging.getLogger("ticket_booker.god.chaos")


@dataclass
class DrillResult:
    name: str
    ok: bool
    detail: str = ""


class ScriptedLocator:
    """Fake playwright locator: invisible nothings, scripted body text."""

    def __init__(self, page: "ScriptedPage", sel: str) -> None:
        self.page = page
        self.sel = sel

    @property
    def first(self):
        return self

    def nth(self, i: int):
        return self

    def count(self) -> int:
        return self.page._count_for(self.sel)

    def is_visible(self, timeout=None) -> bool:
        return False

    def inner_text(self, timeout=None) -> str:
        return self.page._text_for(self.sel)

    def __getattr__(self, name: str):
        raise AssertionError(f"chaos: unexpected locator.{name} (sel={self.sel!r})")


class ScriptedPage:
    """Fake playwright page with a scripted body and no pixels."""

    def __init__(self, body: str = "IRCTC trains page", counts: dict | None = None) -> None:
        self._body = body
        self._counts = counts or {}
        self.url = "https://chaos.test/"
        self.frames: list = []
        self.gotos: list[str] = []

    def locator(self, sel: str) -> ScriptedLocator:
        return ScriptedLocator(self, sel)

    def goto(self, url: str, **kwargs) -> None:
        self.gotos.append(url)

    def screenshot(self, **kwargs):
        raise RuntimeError("chaos: no pixels")

    def content(self):
        raise RuntimeError("chaos: no dom")

    def _count_for(self, sel: str) -> int:
        return self._counts.get(sel, 0)

    def _text_for(self, sel: str) -> str:
        return self._body if sel == "body" else ""


def _make_ctx(body: str = "IRCTC trains page", level: int = 2):
    from ..config import BruteCfg, CaptchaCfg
    from ..tools.base import BruteContext

    cfg = SimpleNamespace(captcha=CaptchaCfg(), brute=BruteCfg(level=level))
    return BruteContext(cfg, ScriptedPage(body), False)


def _quiet():
    """Kill all sleeping inside drills (we test logic, not clocks)."""
    return (
        mock.patch("time.sleep", return_value=None),
        mock.patch("ticket_booker.tools.base.human_delay", return_value=None),
        mock.patch("ticket_booker.irctc.login.human_delay", return_value=None),
    )


def drill_flaky_action() -> DrillResult:
    ctx = _make_ctx()
    calls: list[int] = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("flaky boom")
        return "recovered"

    patches = _quiet()
    for p in patches:
        p.start()
    try:
        out = ctx.brute(fn, "chaos flaky", retries=3, reload_between=False)
    finally:
        for p in patches:
            p.stop()
    ok = out == "recovered" and len(calls) == 3
    return DrillResult("flaky-action", ok, f"attempts={len(calls)} out={out!r}")


def drill_browser_death() -> DrillResult:
    ctx = _make_ctx()
    calls: list[int] = []

    def fn():
        calls.append(1)
        raise RuntimeError("Target closed: boom")

    try:
        ctx.brute(fn, "chaos death", retries=5, reload_between=False)
        return DrillResult("browser-death", False, "death did not propagate!")
    except RuntimeError:
        ok = len(calls) == 1
        return DrillResult("browser-death", ok, f"aborted after {len(calls)} attempt(s)")


def drill_block_wall() -> DrillResult:
    from ..tools.base import BlockedError

    ctx = _make_ctx("Error 403 Forbidden — Access Denied")
    try:
        ctx._heartbeat()
        return DrillResult("block-wall", False, "no BlockedError raised!")
    except BlockedError as exc:
        return DrillResult("block-wall", True, f"raised: {exc.reason}")


def drill_session_rot() -> DrillResult:
    ctx = _make_ctx("Your session expired, please login again")
    patches = _quiet()
    for p in patches:
        p.start()
    try:
        ctx._heartbeat()  # must attempt re-login, must not raise
    finally:
        for p in patches:
            p.stop()
    ok = ctx._relogins_this_run == 1
    return DrillResult("session-rot", ok, f"relogins={ctx._relogins_this_run}")


def drill_doomsday() -> DrillResult:
    import time as _t

    ctx = _make_ctx(level=1)
    ctx._deadline = _t.time() - 1
    try:
        ctx.brute(lambda: "x", "chaos doom", retries=3, reload_between=False)
        return DrillResult("doomsday", False, "budget not enforced!")
    except TimeoutError as exc:
        return DrillResult("doomsday", "DOOMSDAY" in str(exc), str(exc)[:80])


def drill_journal() -> DrillResult:
    ctx = _make_ctx()
    ctx.journal.event("chaos", "ping", ok=True)
    ok = any(e.get("what") == "ping" for e in ctx.journal.read())
    return DrillResult("journal", ok, f"events={len(ctx.journal.read())}")


DRILLS = (
    drill_flaky_action,
    drill_browser_death,
    drill_block_wall,
    drill_session_rot,
    drill_doomsday,
    drill_journal,
)


def run_drills() -> list[DrillResult]:
    results: list[DrillResult] = []
    for drill in DRILLS:
        try:
            results.append(drill())
        except Exception as exc:  # a drill crashing = GOD WOUNDED
            log.exception("Drill %s crashed: %s", drill.__name__, exc)
            results.append(DrillResult(drill.__name__, False, f"CRASH: {exc}"))
    return results
