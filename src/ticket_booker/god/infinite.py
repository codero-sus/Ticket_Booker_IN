"""INFINITE BRUTE VOID — beyond INT64_MAX, beyond saturation.

Cross the ceiling and the rules change:

* no retry floor cap — the brute ladder is immortal
* no doomsday budget — ``max_tool_minutes`` is ignored
* no pacer slowing — maximum velocity, the site feels the full force
* omni-captcha — every available solver fires in parallel, first answer wins
* HYDRA heads uncapped beyond 3
* screenshot every step — black-box evidence of absolute brutality

Pure logic + unit-tested. No browser, no clock, no side effects.
"""

from __future__ import annotations

import concurrent.futures
import logging

from .algebra import (
    INT64_MAX,
    VOID_THRESHOLD,
    evaluate_raw,
    format_level,
    is_void,
)

log = logging.getLogger("ticket_booker.god.infinite")

VOID_TITLE = "INFINITE BRUTE VOID"


def void_title(level) -> str:
    return f"{VOID_TITLE} LVL {format_level(int(level))}"


def void_behavior(brutality: int) -> dict:
    """Return the behavior overrides for a void-level run ({} if not void)."""
    if not is_void(brutality):
        return {}
    return {
        "immortal": True,  # ignore max_tool_minutes / doomsday
        "no_pacer": True,  # maximum velocity, no slowing
        "retry_floor": 50,  # uncapped brute ladder
        "screenshot_every_step": True,
        "genome_aggressive": True,  # mutate every attempt
        "hydra_heads_uncapped": True,
        "omni_captcha": True,
    }


class OmniSolver:
    """Fire ALL captcha solvers in parallel; first non-empty answer wins.

    Zero-touch on steroids: OCR, audio, paid services — everything at once.
    The brute god does not wait for one solver to fail before trying the next.
    """

    def __init__(self, solvers: list, timeout: float = 20.0) -> None:
        self.solvers = [s for s in solvers if getattr(s, "available", lambda: False)()]
        self.timeout = timeout

    def solve_text_image(self, image_bytes: bytes, fallback=None):
        """Run every solver concurrently. Return the first non-empty OK result."""
        solvers = self.solvers
        if not solvers:
            return fallback(image_bytes) if fallback else None

        results: list = []

        def _run(solver):
            try:
                res = solver.solve_image(image_bytes)
                return solver.name, res
            except Exception as exc:  # noqa: BLE001
                return solver.name, None, str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(solvers)) as pool:
            futures = [pool.submit(_run, s) for s in solvers]
            done, _ = concurrent.futures.wait(
                futures,
                timeout=self.timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for f in done:
                try:
                    outcome = f.result()
                except Exception:
                    continue
                name, res = outcome[0], outcome[1]
                if res is not None and getattr(res, "ok", False):
                    text = (getattr(res, "text", "") or "").strip()
                    if text:
                        for other in futures:
                            other.cancel()
                        log.info("🔥 OMNI captcha solved by %s", name)
                        return res
        # nothing won in time — fall back to the caller's sequential chain
        return fallback(image_bytes) if fallback else None


__all__ = [
    "INT64_MAX",
    "VOID_THRESHOLD",
    "VOID_TITLE",
    "is_void",
    "void_title",
    "void_behavior",
    "OmniSolver",
]
