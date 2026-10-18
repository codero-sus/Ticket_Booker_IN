"""Fare enquiry (BRUTE): dry-run booking up to the review page, read fare, STOP.

Never proceeds to payment — it parses the Total Fare text on the review page
and ends the run there. Uses the journey + passengers from config.
"""

from __future__ import annotations

import logging
import re

from ..config import Journey
from ..irctc.constants import HOME_URL
from ..irctc.login import login
from ..irctc.passengers import fill_passengers, submit_and_continue
from ..irctc.search import search_trains, select_train_and_class
from ..timing import NtpClock
from ..utils import human_delay
from .base import BruteContext, ToolResult, run_with_browser

log = logging.getLogger("ticket_booker.tools.fare")

FARE_RE = re.compile(
    r"(?:total\s*fare|total\s*amount|payable|grand\s*total)[^\d₹]{0,12}[₹Rs.\s]*([\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def parse_fare_body(text: str) -> dict:
    """Extract fare figures from review-page text. Never raises."""
    out: dict = {"total_fare": None, "candidates": []}
    try:
        for m in FARE_RE.finditer(text or ""):
            raw = m.group(1).replace(",", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            out["candidates"].append(val)
        if out["candidates"]:
            out["total_fare"] = max(out["candidates"])
    except Exception as exc:
        log.debug("parse_fare_body degraded: %s", exc)
    return out


def _collect(ctx: BruteContext, journey: Journey) -> dict:
    page = ctx.page
    if not ctx.goto(HOME_URL):
        raise RuntimeError("Could not open IRCTC.")
    ctx.brute(lambda: login(page, ctx.cfg.irctc, ctx.captcha, headless=ctx.headless),
              "fare login", retries=2)
    ctx.brute(lambda: search_trains(page, journey), "fare search", retries=2)
    human_delay(2.0, 4.0)
    # Non-tatkal dry run: reuse selection but never wait for a window
    tatkal = ctx.cfg.tatkal.model_copy(update={"enabled": False})
    ctx.brute(lambda: select_train_and_class(page, journey, tatkal, NtpClock()),
              "fare train select", retries=2)
    ctx.brute(lambda: fill_passengers(page, ctx.cfg.passengers, ctx.cfg.preferences),
              "fare passengers", retries=2)
    submit_and_continue(page)
    human_delay(2.0, 4.0)
    ctx.solve_captchas_on_page()  # review captcha if any
    body = ctx.page_text()
    fare = parse_fare_body(body)
    ctx.shot("fare_review")
    if fare["total_fare"] is None:
        raise RuntimeError("Review page reached but no fare found (see screenshot).")
    fare.update({
        "from": journey.from_station, "to": journey.to_station, "date": journey.date,
        "train_no": journey.train_no, "class": journey.class_code,
        "quota": journey.quota, "passengers": len(ctx.cfg.passengers),
        "note": "Dry run — STOPPED before payment. Nothing was booked or paid.",
    })
    return fare


def run_tool(cfg, journey: Journey | None = None, headless: bool | None = None) -> ToolResult:
    journey = journey or cfg.journey

    def _run(ctx: BruteContext) -> ToolResult:
        data = ctx.brute(lambda: _collect(ctx, journey), "fare enquiry",
                         retries=2, relogin_once=True)
        summary = (
            f"Fare {journey.from_station}->{journey.to_station} {journey.date} "
            f"train {journey.train_no or 'auto'} {journey.class_code}/{journey.quota} "
            f"x{data['passengers']} pax = Rs.{data['total_fare']:g} (dry run, not paid)"
        )
        path = ctx.save_report("fare_enquiry", data, summary)
        return ToolResult(True, data, summary, str(path))

    try:
        return run_with_browser(cfg, headless, _run)
    except Exception as exc:
        log.error("Fare tool failed: %s", exc)
        return ToolResult(False, {}, f"Fare tool failed: {exc}")
