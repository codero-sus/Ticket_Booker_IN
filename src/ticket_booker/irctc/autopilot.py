"""AUTOPILOT — hands-free booking: auto login, auto search, auto everything.

One call books a ticket with no prompts, no clicking and no babysitting:

    launch -> auto-login -> auto-search -> pick train -> fill passengers
           -> submit -> solve captcha -> choose UPI -> submit payment
           -> watch for the PNR

Every stage is instrumented on the :mod:`ticket_booker.monitor`, so a small
popup window can show the live page and the step log while it runs.

Design rules
------------
* **Never block on a human.** Captcha falls back to ``error`` (not ``manual``),
  and there is no ``input()`` anywhere in this path.
* **Retry the whole cycle.** A dead session, a sold-out refresh, a dropped
  browser — the cycle starts again from login. ``max_cycles`` bounds it.
* **A browser that can be watched.** ``browser.small_window`` launches a small
  window so the run is visible, and the monitor streams frames regardless.
* **The bank is still the bank.** The autopilot can drive IRCTC up to and
  including submitting the payment, but it never types a PIN, password or OTP.
  The final UPI approval happens in the user's bank app — that boundary is
  deliberate and not configurable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from ..browser import apply_small_window, launch_browser
from ..config import AppConfig
from ..monitor import Monitor, get_monitor
from ..timing import NtpClock
from . import constants as C
from .helpers import click_first, page_text
from .login import login
from .passengers import fill_passengers, submit_and_continue
from .payment import choose_upi, is_failure_page
from .payment import find_pnr as _find_pnr
from .search import search_trains, select_train_and_class

log = logging.getLogger("ticket_booker.irctc.autopilot")


@dataclass
class PilotReport:
    """What the autopilot did, in one object."""

    ok: bool
    pnr: str | None = None
    cycles: int = 0
    message: str = ""
    steps: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "pnr": self.pnr or "",
            "cycles": self.cycles,
            "message": self.message,
            "steps": list(self.steps),
            "seconds": round(self.seconds, 1),
        }


class Autopilot:
    """Hands-free end-to-end booking with retries and a live monitor."""

    def __init__(
        self,
        cfg: AppConfig,
        headless: bool | None = None,
        monitor: Monitor | None = None,
    ) -> None:
        self.cfg = cfg
        self.headless = cfg.browser.headless if headless is None else headless
        self.monitor = monitor if monitor is not None else get_monitor()
        self.clock = NtpClock()
        self.steps: list[str] = []
        self._prepared = False
        self._payment_submitted = False

    # ------------------------------------------------------------------ #
    # setup
    # ------------------------------------------------------------------ #

    def prepare(self) -> None:
        """Force the configuration into a shape that cannot block on a human."""
        if self._prepared:
            return
        cap = self.cfg.captcha
        if getattr(self.cfg.pilot, "force_auto_captcha", True):
            if cap.mode == "manual":
                log.warning("Autopilot: captcha.mode=manual is not hands-free - using auto.")
                cap.mode = "auto"
            if cap.on_failure == "manual":
                cap.on_failure = "error"
        if self.cfg.payment.method == "manual" and getattr(
            self.cfg.pilot, "auto_payment", True
        ):
            log.warning(
                "Autopilot: payment.method=manual - switching to upi so the payment "
                "step can be driven automatically."
            )
            self.cfg.payment.method = "upi"
        if getattr(self.cfg.pilot, "auto_submit", True) and not self.cfg.payment.auto_submit:
            log.info("Autopilot: enabling payment.auto_submit (hands-free).")
            self.cfg.payment.auto_submit = True
        self._prepared = True

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _mark(self, step: str, detail: str = "", level: str = "info") -> None:
        self.steps.append(step)
        self.monitor.step_now(step, detail, level=level)

    def _shot(self, page, label: str = "") -> None:
        """Capture a frame (main thread only) - failures are ignored."""
        try:
            self.monitor.snapshot(page, label or "frame")
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("monitor snapshot skipped: %s", exc)

    # ------------------------------------------------------------------ #
    # public entry point
    # ------------------------------------------------------------------ #

    def run(self) -> PilotReport:
        """Book a ticket with zero human involvement. Never raises."""
        self.prepare()
        started = time.monotonic()
        self.monitor.begin("autopilot", detail=f"{self.cfg.journey.from_station} -> "
                                              f"{self.cfg.journey.to_station}")
        max_cycles = max(1, int(getattr(self.cfg.pilot, "max_cycles", 4)))
        last_message = "autopilot did not run"

        for cycle in range(1, max_cycles + 1):
            self.monitor.step_now(
                "cycle", f"attempt {cycle}/{max_cycles}", level="info"
            )
            try:
                ok, pnr, message = self._cycle()
            except Exception as exc:
                log.exception("Autopilot cycle %d crashed: %s", cycle, exc)
                ok, pnr, message = False, None, f"cycle error: {exc}"
            last_message = message
            if self._payment_submitted and not (ok and pnr):
                # Money may already be in flight. Re-running could double-book,
                # so we stop and tell the user to verify booking history.
                report = PilotReport(
                    False, None, cycle,
                    "Payment was submitted but no PNR was detected - STOPPING so the "
                    "ticket is not booked twice. Verify IRCTC booking history.",
                    self.steps,
                    time.monotonic() - started,
                )
                self.monitor.finish(False, report.message)
                return report
            if ok and pnr:
                report = PilotReport(
                    True, pnr, cycle,
                    f"BOOKED - PNR {pnr} (cycle {cycle})",
                    self.steps,
                    time.monotonic() - started,
                )
                self.monitor.finish(True, report.message, pnr=pnr)
                return report
            if ok and not pnr:
                # Submitted but no PNR: do not double-book, stop and report.
                report = PilotReport(
                    False, None, cycle,
                    "Payment submitted but no PNR yet - check IRCTC booking history "
                    "before retrying (not re-booking automatically).",
                    self.steps,
                    time.monotonic() - started,
                )
                self.monitor.finish(False, report.message)
                return report
            if cycle < max_cycles:
                wait = float(getattr(self.cfg.pilot, "retry_delay_seconds", 8.0))
                self._mark("retrying", f"{message} - sleeping {wait:.0f}s", level="warn")
                time.sleep(max(0.0, wait))

        report = PilotReport(
            False, None, max_cycles,
            f"Gave up after {max_cycles} cycles: {last_message}",
            self.steps,
            time.monotonic() - started,
        )
        self.monitor.finish(False, report.message)
        return report

    # ------------------------------------------------------------------ #
    # one full booking cycle
    # ------------------------------------------------------------------ #

    def _cycle(self) -> tuple[bool, str | None, str]:
        with launch_browser(self.cfg.browser, self.headless) as session:
            page = session.page

            # A small window is the whole point: you can watch it work.
            if apply_small_window(page, self.cfg.browser):
                self._mark("window", "small popup window shown")

            self._shot(page, "launched")

            # 1. AUTO LOGIN
            self._mark("login", "signing in")
            solver = self._captcha()
            try:
                solver.attach_page(page)  # Nano/Buster need the live page
            except Exception as exc:
                log.debug("captcha page attach skipped: %s", exc)
            login(page, self.cfg.irctc, solver, headless=self.headless)
            self._shot(page, "logged-in")
            self._mark("login", "signed in")

            # 2. AUTO SEARCH
            self._mark("search", f"{self.cfg.journey.from_station} -> "
                                 f"{self.cfg.journey.to_station} on {self.cfg.journey.date}")
            search_trains(page, self.cfg.journey)
            self._shot(page, "train-list")
            self._mark("search", "train list loaded")

            # 3. SELECT TRAIN + CLASS (includes the Tatkal race when armed)
            self._mark("select", f"{self.cfg.journey.train_no or 'best'} / "
                                 f"{self.cfg.journey.class_code}")
            select_train_and_class(
                page, self.cfg.journey, self.cfg.tatkal, self.clock
            )
            self._shot(page, "selected")
            self._mark("select", "train and class selected")

            # 4. PASSENGERS
            self._mark("passengers", f"{len(self.cfg.passengers)} passenger(s)")
            fill_passengers(page, self.cfg.passengers, self.cfg.preferences)
            submit_and_continue(page)
            self._shot(page, "passengers")
            self._mark("passengers", "filled and continued")

            # 5. REVIEW PAGE CAPTCHA
            self._review_captcha(page)

            # 6. PAYMENT
            return self._pay(page)

    # ------------------------------------------------------------------ #
    # payment
    # ------------------------------------------------------------------ #

    def _pay(self, page) -> tuple[bool, str | None, str]:
        payment = self.cfg.payment
        auto_submit = bool(getattr(payment, "auto_submit", False))

        self._mark("payment", f"choosing UPI ({payment.upi_id or 'no id set'})")
        try:
            choose_upi(page, payment.upi_id)
        except Exception as exc:
            log.debug("UPI selection failed: %s", exc)
        self._shot(page, "payment-page")

        if auto_submit:
            self._mark("payment", "submitting payment (no PIN/OTP is ever typed)")
            try:
                click_first(page, C.PAY_BUTTON, timeout_each=3000)
                self._payment_submitted = True
            except Exception as exc:
                log.debug("pay button click failed: %s", exc)
            self._shot(page, "payment-submitted")
        else:
            self._mark("payment", "auto_submit off - waiting on the open page")

        # 7. WATCH FOR THE PNR (bank approval happens on the phone)
        self._mark("waiting", "waiting for payment confirmation / PNR")
        pnr = self._await_pnr(page)
        if pnr:
            self._mark("booked", f"PNR {pnr}", level="ok")
            self._shot(page, f"PNR-{pnr}")
            return True, pnr, f"BOOKED - PNR {pnr}"
        return False, None, "payment not confirmed within the wait window"

    def _await_pnr(self, page) -> str | None:
        """Poll the page for a confirmed PNR. Returns None on timeout/failure."""
        minutes = int(getattr(self.cfg.payment, "wait_minutes", 10))
        deadline = time.time() + minutes * 60
        snap_every = float(getattr(self.cfg.pilot, "snapshot_seconds", 3.0))
        next_shot = time.time() + snap_every
        while time.time() < deadline:
            try:
                body = page_text(page)
            except Exception:
                body = ""
            lowered = (body or "").lower()
            if is_failure_page(lowered):
                self._mark("payment", "gateway reported failure", level="error")
                self._shot(page, "payment-failed")
                return None
            pnr = _find_pnr(body)
            if pnr:
                return pnr
            if time.time() >= next_shot:
                self._shot(page, "waiting")
                next_shot = time.time() + snap_every
            time.sleep(1.0)
        self._mark("payment", "timed out waiting for the PNR", level="warn")
        self._shot(page, "payment-timeout")
        return None

    # ------------------------------------------------------------------ #
    # misc
    # ------------------------------------------------------------------ #

    def _captcha(self):
        from ..captcha.manager import AutoCaptcha

        solver = AutoCaptcha(self.cfg.captcha)
        return solver

    def _review_captcha(self, page) -> None:
        """IRCTC sometimes asks for a captcha again on the review page."""
        from .helpers import locate_first

        try:
            img = locate_first(page, C.REVIEW_CAPTCHA_IMG, timeout_each=1200)
        except Exception:
            img = None
        if img is None:
            return
        self._mark("captcha", "review-page captcha detected")
        solver = self._captcha()
        solver.attach_page(page)
        for _ in range(max(1, self.cfg.captcha.max_attempts)):
            try:
                blob = img.screenshot(timeout=5000)
            except Exception:
                return
            res = solver.solve_text_image(blob)
            if not res.ok:
                return
            from .helpers import fill_first

            if fill_first(page, C.REVIEW_CAPTCHA_INPUT, res.text, timeout_each=2000):
                click_first(page, C.CONTINUE_BUTTON, timeout_each=2000)
                time.sleep(1.5)
                if locate_first(page, C.REVIEW_CAPTCHA_IMG, timeout_each=1000) is None:
                    self._mark("captcha", f"solved ({res.solver})", level="ok")
                    return
        self._mark("captcha", "review captcha not accepted", level="warn")


def run_autopilot(cfg: AppConfig, headless: bool | None = None) -> PilotReport:
    """Convenience wrapper used by the CLI and the WebUI."""
    return Autopilot(cfg, headless=headless).run()


__all__ = ["Autopilot", "PilotReport", "run_autopilot"]
