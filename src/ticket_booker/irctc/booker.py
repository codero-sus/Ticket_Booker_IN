"""IRCTCBooker — end-to-end orchestration: login -> search -> race -> fill -> pay."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

from ..browser import launch_browser
from ..captcha.manager import AutoCaptcha
from ..config import AppConfig
from ..timing import NtpClock, countdown_until, now_ist, parse_journey_date, tatkal_open_datetime
from ..utils import save_screenshot
from . import constants as C
from .login import login
from .passengers import fill_passengers, submit_and_continue
from .payment import wait_for_completion
from .search import search_trains, select_train_and_class

log = logging.getLogger("ticket_booker.irctc.booker")


@dataclass
class BookingResult:
    success: bool
    pnr: str | None = None
    message: str = ""
    screenshots: list[str] = field(default_factory=list)


class IRCTCBooker:
    def __init__(self, cfg: AppConfig, headless: bool | None = None) -> None:
        self.cfg = cfg
        self.headless = cfg.browser.headless if headless is None else headless
        self.clock = NtpClock()
        self.captcha = AutoCaptcha(cfg.captcha)

    # ---------- public modes ----------

    def login_only(self) -> bool:
        """Just log in (saves session into the persistent profile)."""
        with launch_browser(self.cfg.browser, self.headless) as session:
            return login(
                session.page, self.cfg.irctc, self.captcha, headless=self.headless
            )

    def search_only(self) -> bool:
        """Login + search + show train list (no booking). Useful for testing."""
        with launch_browser(self.cfg.browser, self.headless) as session:
            page = session.page
            login(page, self.cfg.irctc, self.captcha, headless=self.headless)
            search_trains(page, self.cfg.journey)
            time.sleep(4)
            save_screenshot(page, "train_list")
            log.info("Train list captured. Keeping browser open 60s for inspection...")
            time.sleep(60)
            return True

    def book(self) -> BookingResult:
        """Full booking run. For Tatkal quota this includes the opening race."""
        if self.cfg.tatkal.enabled and self.cfg.journey.quota in ("TQ", "PT"):
            self._pre_tatkal_wait()
        try:
            with launch_browser(self.cfg.browser, self.headless) as session:
                page = session.page
                login(page, self.cfg.irctc, self.captcha, headless=self.headless)
                search_trains(page, self.cfg.journey)
                select_train_and_class(page, self.cfg.journey, self.cfg.tatkal, self.clock)
                fill_passengers(page, self.cfg.passengers, self.cfg.preferences)
                submit_and_continue(page)
                # Review-page captcha (IRCTC sometimes asks again here)
                self._solve_review_captcha_if_any(page)
                pnr = wait_for_completion(page, self.cfg.payment)
                if pnr:
                    return BookingResult(True, pnr, f"Ticket booked! PNR {pnr}")
                return BookingResult(
                    False, None,
                    "Payment not confirmed within wait window — verify booking history.",
                )
        except Exception as exc:
            log.exception("Booking run failed: %s", exc)
            return BookingResult(False, None, f"Failed: {exc}")

    # ---------- internals ----------

    def _pre_tatkal_wait(self) -> None:
        """Arrive early: NTP-sync, then sleep until (open - small buffer).

        We launch the browser ~arrive_minutes_early before opening so login +
        search are done ahead of time; the precise last-second race happens in
        select_train_and_class().
        """
        journey_date = parse_journey_date(self.cfg.journey.date)
        opening = tatkal_open_datetime(journey_date, self.cfg.journey.class_code)
        self.clock.sync()
        now = self.clock.now()
        wake_at = opening - timedelta(minutes=self.cfg.tatkal.arrive_minutes_early)
        log.info("Tatkal opens at %s (NTP-corrected clock).", opening.strftime("%Y-%m-%d %H:%M:%S IST"))
        if now >= opening:
            log.warning("Tatkal window already open — racing immediately!")
            return
        if now < wake_at:
            log.info("Arriving early: sleeping until %s ...", wake_at.strftime("%H:%M:%S"))
            countdown_until(wake_at, clock=self.clock, tick=5.0)
        else:
            log.info("Within arrival window; starting now.")

    def _solve_review_captcha_if_any(self, page) -> None:
        """IRCTC occasionally shows a captcha on the review page before pay."""
        from .helpers import fill_first, locate_first

        img_loc = locate_first(page, C.REVIEW_CAPTCHA_IMG, timeout_each=1500)
        if img_loc is None:
            return
        log.info("Review-page captcha detected — solving automatically...")
        for attempt in range(1, self.cfg.captcha.max_attempts + 1):
            try:
                img_bytes = img_loc.screenshot(timeout=5000)
            except Exception:
                return
            res = self.captcha.solve_text_image(img_bytes)
            if not res.ok:
                break
            if fill_first(page, C.REVIEW_CAPTCHA_INPUT, res.text, timeout_each=2000):
                time.sleep(0.6)
                # Continue button on review page doubles as submit
                from .helpers import click_first

                click_first(page, C.CONTINUE_BUTTON, timeout_each=2000)
                time.sleep(2.0)
                if locate_first(page, C.REVIEW_CAPTCHA_IMG, timeout_each=1200) is None:
                    log.info("Review captcha accepted.")
                    return
                log.info("Review captcha rejected; retry %d...", attempt)
        log.warning("Review captcha unsolved — please solve it manually to proceed.")
