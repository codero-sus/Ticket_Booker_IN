"""Payment stage — deliberately human-in-the-loop.

SAFETY: this tool NEVER types card numbers, net-banking passwords or OTPs.
For Tatkal the recommended rail-approved fast path is UPI: we optionally
select the UPI tab and pre-fill your UPI ID; you approve the collect request
on your phone. The bot then watches for the booking confirmation and
captures the PNR.
"""

from __future__ import annotations

import logging
import re
import time

from ..config import Payment
from ..utils import save_screenshot
from . import constants as C
from .helpers import click_first, fill_first, page_text

log = logging.getLogger("ticket_booker.irctc.payment")

PNR_RE = re.compile(r"\bPNR(?:\s*(?:no|number|[:\-]))?\s*[:\-]?\s*(\d{10})\b", re.IGNORECASE)
SUCCESS_HINTS = (
    "booking successful", "booked successfully", "transaction successful",
    "pnr", "chart", "ticket booked", "booking confirmed",
)
FAILURE_HINTS = (
    "payment failed", "transaction failed", "payment declined",
    "transaction declined", "payment cancelled", "cancelled by user",
    "transaction cancelled", "payment unsuccessful",
)


def is_failure_page(text):
    low = (text or "").lower()
    return any(f in low for f in FAILURE_HINTS)


def find_pnr(text: str) -> str | None:
    m = PNR_RE.search(text or "")
    return m.group(1) if m else None


def choose_upi(page, upi_id: str) -> None:
    """Best-effort: open UPI tab and pre-fill the UPI ID."""
    if click_first(page, C.UPI_TAB, timeout_each=2500):
        log.info("UPI payment tab selected.")
        time.sleep(1.0)
    else:
        log.info("UPI tab not found; continuing on current payment tab.")
    if upi_id:
        if fill_first(page, C.UPI_ID_INPUT, upi_id, timeout_each=2500):
            log.info("UPI ID pre-filled.")
        else:
            log.warning("Could not find UPI ID field; fill it manually.")


def wait_for_completion(page, payment: Payment) -> str | None:
    """Wait for the user to finish payment in the browser.

    Returns the PNR when detected, else None (caller should verify in
    booking history). Screenshots the final state either way.
    """
    if payment.method == "upi" and payment.upi_id:
        choose_upi(page, payment.upi_id)
    elif payment.method == "upi":
        choose_upi(page, "")

    print("\n" + "=" * 70)
    print("  COMPLETE THE PAYMENT IN THE BROWSER NOW")
    print(f"  Waiting up to {payment.wait_minutes} min for confirmation...")
    print("=" * 70 + "\n")
    log.warning("Waiting for manual payment completion (up to %d min)...", payment.wait_minutes)

    deadline = time.time() + payment.wait_minutes * 60
    last_hint = time.time()
    while time.time() < deadline:
        try:
            body = page_text(page)
        except Exception:
            body = ""
        pnr = find_pnr(body)
        lowered = body.lower()
        if is_failure_page(lowered):
            log.error("Payment FAILED (gateway said so) - aborting wait.")
            save_screenshot(page, "payment_failed")
            return None
        if pnr and any(h in lowered for h in SUCCESS_HINTS):
            log.info("Booking confirmed! PNR: %s", pnr)
            save_screenshot(page, f"ticket_PNR_{pnr}")
            return pnr
        if time.time() - last_hint > 60:
            log.info("Still waiting for payment confirmation...")
            save_screenshot(page, "payment_waiting")
            last_hint = time.time()
        time.sleep(2.0)

    log.error("Payment wait timed out. Check IRCTC booking history manually.")
    save_screenshot(page, "payment_timeout")
    return None
