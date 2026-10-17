"""Playwright convenience helpers shared by the IRCTC steps."""

from __future__ import annotations

import logging
import time

log = logging.getLogger("ticket_booker.irctc")


def locate_first(page_or_frame, selectors: list[str], timeout_each: int = 1500):
    """Return the first selector that becomes visible, or None."""
    for sel in selectors:
        try:
            loc = page_or_frame.locator(sel).first
            if loc.count() and loc.is_visible(timeout=timeout_each):
                return loc
        except Exception:
            continue
    return None


def click_first(page_or_frame, selectors: list[str], timeout_each: int = 1500) -> bool:
    loc = locate_first(page_or_frame, selectors, timeout_each)
    if loc is None:
        return False
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
        loc.click(timeout=8000)
        return True
    except Exception as exc:
        log.debug("click failed for %s: %s", selectors, exc)
        return False


def fill_first(
    page_or_frame,
    selectors: list[str],
    value: str,
    timeout_each: int = 1500,
    clear: bool = True,
) -> bool:
    loc = locate_first(page_or_frame, selectors, timeout_each)
    if loc is None:
        return False
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
        if clear:
            try:
                loc.fill("", timeout=3000)
            except Exception:
                loc.press("ControlOrMeta+a")
                loc.press("Backspace")
        loc.press_sequentially(value, delay=25, timeout=10000)
        return True
    except Exception as exc:
        log.debug("fill failed for %s: %s", selectors, exc)
        return False


def page_text(page, timeout: int = 3000) -> str:
    try:
        return page.locator("body").inner_text(timeout=timeout) or ""
    except Exception:
        return ""


def dismiss_popups(page) -> None:
    """Close common IRCTC popups (alerts, session messages, COVID-era banners)."""
    for sel in (
        "button:has-text('OK')",
        "button:has-text('Yes')",
        "p-confirmdialog button:has-text('Yes')",
        ".ui-dialog-titlebar-close",
        "button.close",
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=500):
                loc.click(timeout=2000)
                time.sleep(0.4)
        except Exception:
            continue


def wait_for_any_text(page, texts: tuple[str, ...], timeout_s: int = 20) -> str | None:
    """Poll page text for any of the substrings. Returns the match or None."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = page_text(page).lower()
        for t in texts:
            if t.lower() in body:
                return t
        time.sleep(0.5)
    return None
