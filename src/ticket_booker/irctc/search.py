"""Train search + train/class selection (incl. Tatkal refresh race)."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from ..config import Journey, Tatkal
from ..timing import NtpClock, countdown_until, format_duration, now_ist, parse_journey_date
from ..utils import human_delay, save_screenshot
from . import constants as C
from .helpers import click_first, fill_first, locate_first, page_text

log = logging.getLogger("ticket_booker.irctc.search")


def _pick_autocomplete_option(page, code: str, timeout_s: int = 8) -> bool:
    """After typing a station code, click the matching suggestion."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            options = page.locator(", ".join(C.AUTOCOMPLETE_OPTION))
            n = options.count()
            for i in range(min(n, 10)):
                try:
                    text = (options.nth(i).inner_text(timeout=1500) or "").upper()
                except Exception:
                    continue
                if code.upper() in text.replace(" ", "") or f"({code.upper()})" in text or code.upper() in text:
                    options.nth(i).scroll_into_view_if_needed(timeout=2000)
                    options.nth(i).click(timeout=4000)
                    return True
            if n:
                options.first.scroll_into_view_if_needed(timeout=2000)
                options.first.click(timeout=4000)
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def fill_station(page, which: str, code: str) -> None:
    sels = C.FROM_INPUT if which == "from" else C.TO_INPUT
    loc = locate_first(page, sels, timeout_each=4000)
    if loc is None:
        raise RuntimeError(f"'{which}' station field not found.")
    loc.scroll_into_view_if_needed(timeout=3000)
    loc.click(timeout=4000)
    try:
        loc.fill("", timeout=3000)
    except Exception:
        loc.press("ControlOrMeta+a")
        loc.press("Backspace")
    time.sleep(0.3)
    # Type slowly so the autocomplete queries fire
    loc.press_sequentially(code.upper(), delay=90, timeout=8000)
    time.sleep(1.0)
    if not _pick_autocomplete_option(page, code):
        save_screenshot(page, f"station_{which}_fail")
        raise RuntimeError(f"Could not select station {code} from suggestions.")
    log.info("Station %s = %s", which, code.upper())
    human_delay(0.2, 0.5)


def fill_date(page, journey_date: str) -> None:
    target = parse_journey_date(journey_date)
    display = target.strftime("%d/%m/%Y")
    loc = locate_first(page, C.DATE_INPUT, timeout_each=4000)
    if loc is None:
        raise RuntimeError("Journey-date field not found.")
    loc.scroll_into_view_if_needed(timeout=3000)
    loc.click(timeout=4000)
    time.sleep(0.4)
    try:
        loc.fill("", timeout=3000)
    except Exception:
        loc.press("ControlOrMeta+a")
        loc.press("Backspace")
    loc.press_sequentially(display, delay=40, timeout=8000)
    time.sleep(0.5)
    page.keyboard.press("Enter")
    # Dismiss calendar popup if open
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    log.info("Journey date = %s", display)


def _select_dropdown(page, dropdown_sels: list[str], label: str, what: str) -> None:
    dd = locate_first(page, dropdown_sels, timeout_each=3000)
    if dd is None:
        raise RuntimeError(f"{what} dropdown not found.")
    dd.scroll_into_view_if_needed(timeout=3000)
    dd.click(timeout=4000)
    time.sleep(0.8)
    # Try exact label, then a contains-match, via role/text first
    for attempt_sel in (
        f"li:has-text('{label}')",
        f"text={label}",
    ):
        try:
            opt = page.locator(attempt_sel).first
            if opt.count() and opt.is_visible(timeout=1500):
                opt.scroll_into_view_if_needed(timeout=2000)
                opt.click(timeout=4000)
                log.info("%s = %s", what, label)
                return
        except Exception:
            continue
    # Fallback: iterate raw items and match loosely
    try:
        items = page.locator(", ".join(C.DROPDOWN_ITEM))
        for i in range(items.count()):
            try:
                text = (items.nth(i).inner_text(timeout=1200) or "").strip()
            except Exception:
                continue
            if label.lower() in text.lower() or text.lower() in label.lower():
                items.nth(i).click(timeout=4000)
                log.info("%s = %s", what, label)
                return
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    raise RuntimeError(f"Could not pick '{label}' in {what} dropdown.")


def search_trains(page, journey: Journey) -> None:
    """Fill From/To/Date/Class/Quota and press Search."""
    log.info(
        "Searching %s -> %s on %s (%s, %s)%s",
        journey.from_station, journey.to_station, journey.date,
        journey.class_code, journey.quota,
        f" train {journey.train_no}" if journey.train_no else "",
    )
    fill_station(page, "from", journey.from_station)
    fill_station(page, "to", journey.to_station)
    fill_date(page, journey.date)
    class_label = C.CLASS_LABELS.get(journey.class_code, journey.class_code)
    quota_label = C.QUOTA_LABELS.get(journey.quota, journey.quota)
    _select_dropdown(page, C.CLASS_DROPDOWN, class_label, "Class")
    human_delay(0.2, 0.5)
    _select_dropdown(page, C.QUOTA_DROPDOWN, quota_label, "Quota")
    human_delay(0.3, 0.7)
    if not click_first(page, C.SEARCH_BUTTON, timeout_each=3000):
        raise RuntimeError("Search button not found.")
    log.info("Search submitted; waiting for train list...")
    time.sleep(2.5)


def _train_row(page, train_no: str):
    """Locate the row/card for a train number, or the first row if blank."""
    if train_no:
        for sel in (
            f"div.train-list:has-text('{train_no}')",
            f"text={train_no}",
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=2500):
                    return loc
            except Exception:
                continue
        return None
    row = locate_first(page, C.TRAIN_ROWS, timeout_each=4000)
    return row


def _click_availability_and_book(page, scope, class_code: str) -> bool:
    """Inside a train row: click the class availability cell, then Book Now."""
    # IRCTC shows per-class availability tabs/cells; class code text nearby.
    candidates = [
        f"text=/{class_code}.*(AVAILABLE|AVL|RAC|WL)/i",
        f"td:has-text('{class_code}')",
        f"div:has-text('{class_code}')",
        C.AVAILABLE_CELL,
    ]
    root = scope if scope is not None else page
    for sel in candidates:
        try:
            loc = root.locator(sel).first
            if loc.count() and loc.is_visible(timeout=1200):
                loc.scroll_into_view_if_needed(timeout=2000)
                loc.click(timeout=4000)
                time.sleep(1.2)
                break
        except Exception:
            continue
    # Now Book Now (prefer one inside the same row scope)
    for _ in range(2):
        btn = None
        if scope is not None:
            try:
                b = scope.locator(", ".join(C.BOOK_NOW_BUTTON)).first
                if b.count() and b.is_visible(timeout=1200):
                    btn = b
            except Exception:
                btn = None
        if btn is None:
            btn = locate_first(page, C.BOOK_NOW_BUTTON, timeout_each=1500)
        if btn is None:
            return False
        try:
            btn.scroll_into_view_if_needed(timeout=2000)
            btn.click(timeout=6000)
            time.sleep(2.5)
            body = page_text(page).lower()
            # Passenger page markers
            if any(k in body for k in ("passenger details", "passenger name", "berth", "book only if")):
                return True
            # Still on list = click didn't take; retry once
        except Exception:
            pass
    return False


def select_train_and_class(
    page,
    journey: Journey,
    tatkal: Tatkal,
    clock: NtpClock | None = None,
) -> None:
    """Pick the train + class, racing the Tatkal clock when enabled.

    Tatkal strategy: keep refreshing the availability until the opening
    second (NTP-corrected), then click Book Now immediately.
    """
    from ..timing import tatkal_open_datetime

    clock = clock or NtpClock()
    target_open = None
    if tatkal.enabled and journey.quota in ("TQ", "PT"):
        target_open = tatkal_open_datetime(parse_journey_date(journey.date), journey.class_code)
        remaining = (target_open - clock.now()).total_seconds()
        log.info("Tatkal opens at %s (in %s)", target_open.strftime("%H:%M:%S IST"), _fmt_secs(remaining))

    deadline = time.time() + (30 * 60 if tatkal.enabled else 5 * 60)
    interval = max(0.3, tatkal.refresh_interval_ms / 1000.0)
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        # If Tatkal hasn't opened yet, wait precisely until it does.
        if target_open is not None:
            remaining = (target_open - clock.now()).total_seconds()
            if remaining > 1.0:
                if attempt == 1 or attempt % 10 == 0:
                    log.info("Waiting for Tatkal window... %s left", _fmt_secs(remaining))
                # Gentle refresh so the session stays alive, then precise wait
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                countdown_until(target_open, clock=clock, tick=min(interval, 1.0))
                continue

        row = _train_row(page, journey.train_no)
        if row is None:
            log.warning("Train %s not in list yet (attempt %d); refreshing...",
                        journey.train_no or "<any>", attempt)
            save_screenshot(page, "train_not_found")
            time.sleep(interval)
            try:
                page.reload(wait_until="domcontentloaded")
                time.sleep(2.0)
            except Exception:
                pass
            continue

        log.info("Found train %s — booking %s...", journey.train_no or "(first)", journey.class_code)
        if _click_availability_and_book(page, row, journey.class_code):
            log.info("Reached passenger-details page.")
            return
        log.warning("Book Now didn't land on passenger page; retrying...")
        time.sleep(interval)
        try:
            page.reload(wait_until="domcontentloaded")
            time.sleep(2.0)
        except Exception:
            pass

    raise TimeoutError("Could not reach the passenger page in time.")


def _fmt_secs(seconds: float) -> str:
    if seconds <= 0:
        return "OPEN NOW"
    return format_duration(seconds)
