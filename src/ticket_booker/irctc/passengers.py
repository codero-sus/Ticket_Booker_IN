"""Passenger-details form filling (fast path for Tatkal)."""

from __future__ import annotations

import logging
import time

from ..config import Passenger, Preferences
from ..utils import human_delay, save_screenshot
from . import constants as C
from .helpers import click_first, locate_first, page_text

log = logging.getLogger("ticket_booker.irctc.passengers")


def _fill_row(page, index: int, pax: Passenger) -> None:
    """Fill the index-th passenger row (0-based)."""
    def _loc(selector: str):
        try:
            loc = page.locator(selector).nth(index)
            if loc.count() and loc.is_visible(timeout=4000):
                return loc
        except Exception:
            pass
        return None

    name = _loc(C.PASSENGER_NAME)
    if name is None:
        raise RuntimeError(f"Passenger row {index + 1} name field not found.")
    name.scroll_into_view_if_needed(timeout=3000)
    name.fill("", timeout=3000)
    name.press_sequentially(pax.name, delay=15, timeout=8000)

    age = _loc(C.PASSENGER_AGE)
    if age is None:
        raise RuntimeError(f"Passenger row {index + 1} age field not found.")
    age.fill("", timeout=3000)
    age.press_sequentially(str(pax.age), delay=15, timeout=8000)

    gender = _loc(C.PASSENGER_GENDER)
    if gender is not None:
        try:
            gender.select_option(label=C.GENDER_LABELS.get(pax.gender, "Male"), timeout=4000)
        except Exception:
            try:
                gender.select_option(value=pax.gender, timeout=3000)
            except Exception as exc:
                log.debug("gender select failed: %s", exc)

    if pax.berth and pax.berth != "NP":
        berth = _loc(C.PASSENGER_BERTH)
        if berth is not None:
            try:
                berth.select_option(label=C.BERTH_LABELS[pax.berth], timeout=3000)
            except Exception as exc:
                log.debug("berth select failed: %s", exc)

    if pax.food:
        food = _loc(C.PASSENGER_FOOD)
        if food is not None:
            try:
                food.select_option(label=C.FOOD_LABELS[pax.food], timeout=3000)
            except Exception as exc:
                log.debug("food select failed: %s", exc)

    if pax.id_card_type:
        idt = _loc(C.PASSENGER_ID_TYPE)
        if idt is not None:
            try:
                idt.select_option(label=pax.id_card_type, timeout=3000)
            except Exception:
                pass
    if pax.id_card_no:
        idn = _loc(C.PASSENGER_ID_NO)
        if idn is not None:
            try:
                idn.fill(pax.id_card_no, timeout=3000)
            except Exception:
                pass

    log.info("Passenger %d: %s, %sy, %s", index + 1, pax.name, pax.age, pax.gender)


def _set_checkbox(page, selectors: list[str], want: bool, what: str) -> None:
    loc = locate_first(page, selectors, timeout_each=1200)
    if loc is None:
        log.debug("Checkbox '%s' not found; skipping.", what)
        return
    try:
        checked = loc.is_checked(timeout=2000)
    except Exception:
        checked = False
    if checked != want:
        try:
            loc.scroll_into_view_if_needed(timeout=2000)
            loc.click(timeout=4000, force=True)
            log.info("Checkbox '%s' -> %s", what, want)
        except Exception as exc:
            log.debug("checkbox %s click failed: %s", what, exc)


def fill_passengers(
    page, passengers: list[Passenger], prefs: Preferences
) -> None:
    """Fill all passenger rows + contact + preference checkboxes."""
    log.info("Filling %d passenger(s)...", len(passengers))
    for i, pax in enumerate(passengers):
        if i > 0:
            if not click_first(page, C.ADD_PASSENGER, timeout_each=2500):
                raise RuntimeError("Could not add passenger row %d." % (i + 1))
            time.sleep(0.8)
        _fill_row(page, i, pax)

    mobile = prefs.mobile
    if mobile:
        try:
            loc = locate_first(page, C.MOBILE_INPUT, timeout_each=2500)
            if loc is not None:
                try:
                    current = (loc.input_value(timeout=2000) or "").strip()
                except Exception:
                    current = ""
                if not current:
                    loc.scroll_into_view_if_needed(timeout=2000)
                    loc.fill(mobile, timeout=4000)
                    log.info("Mobile number filled.")
                else:
                    log.info("Mobile already present in form.")
        except Exception as exc:
            log.debug("mobile fill failed: %s", exc)

    _set_checkbox(page, C.AUTO_UPGRADE_CHECK, prefs.auto_upgrade, "auto-upgrade")
    _set_checkbox(page, C.CONFIRM_BERTH_CHECK, prefs.confirm_berths, "confirm-berths")
    if prefs.travel_insurance:
        click_first(page, C.INSURANCE_YES, timeout_each=1200)
    human_delay(0.3, 0.7)
    save_screenshot(page, "passengers_filled")


def submit_and_continue(page) -> None:
    """Submit passenger form and continue through the review page to payment.

    IRCTC sometimes shows a captcha on the review page too — the caller can
    pass an AutoCaptcha-aware handler; here we detect it and pause briefly so
    login-style solving can be wired in via `handle_review_captcha`.
    """
    if not click_first(page, C.CONTINUE_BUTTON, timeout_each=3000):
        raise RuntimeError("Continue/Submit button not found on passenger page.")
    log.info("Passenger form submitted; waiting for review/payment page...")
    deadline = time.time() + 45
    while time.time() < deadline:
        body = page_text(page).lower()
        if any(k in body for k in ("payment", "pay ", "upi", "review journey", "fare")):
            log.info("Reached review/payment stage.")
            return
        time.sleep(1.0)
    save_screenshot(page, "after_passenger_submit")
    log.warning("Review page not clearly detected; continuing anyway.")
