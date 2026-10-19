"""Live running status (BRUTE) via NTES 'Spot Your Train'.

Text-driven: finds tabs/buttons/inputs by visible text, auto-solves NTES
captchas, and mines delay/status lines from page text. No login needed.
"""

from __future__ import annotations

import logging
import re

from ..utils import human_delay
from .base import BruteContext, ToolResult, run_with_browser
from .schedule import NTES_URLS

log = logging.getLogger("ticket_booker.tools.live")


def parse_live_body(text: str) -> dict:
    """Mine live-status info from NTES text. Never raises."""
    out: dict = {"delay": None, "status_lines": [], "last_station": None}
    try:
        text = text or ""
        m = re.search(r"(delay(?:ed)?\s*(?:by)?\s*\d+\s*(?:hrs?|hours?|mins?|minutes?)?"
                      r"|\d+\s*(?:hrs?|hours?|mins?|minutes?)\s*late|right\s*time|on\s*time)",
                      text, re.I)
        if m:
            out["delay"] = " ".join(m.group(0).split())
        for ln in text.splitlines():
            ln = ln.strip()
            if re.search(r"(delay|late|right time|arrived|departed|expected|platform|at station|last location)", ln, re.I):
                out["status_lines"].append(ln[:160])
        out["status_lines"] = out["status_lines"][:20]
        st = re.search(r"(?:at|reached|departed|arrived)\s+([A-Z][A-Za-z .()-]{2,40}?(?:\([A-Z]{2,5}\))?)", text)
        if st:
            out["last_station"] = st.group(1).strip()
    except Exception as exc:
        log.debug("parse_live_body degraded: %s", exc)
    return out


def _collect(ctx: BruteContext, train_no: str, station: str) -> dict:
    if not ctx.goto(*NTES_URLS):
        raise RuntimeError("NTES unreachable.")
    ctx.click_text("Spot Your Train", "Spot Train", "Live Train", "Running Status")
    human_delay(1.5, 3.0)
    ctx.solve_captchas_on_page()
    if not ctx.fill_near_text(("Train No", "Train Number", "Enter Train", "Train"), train_no):
        raise RuntimeError("Train-number box not found on NTES.")
    if station:
        ctx.fill_near_text(("Station", "From Station", "Select Station"), station)
        human_delay(0.5, 1.0)
    ctx.solve_captchas_on_page()
    if not ctx.click_text("Get Status", "Search", "Submit", "Show", "Go", "Spot", verify_change=True):
        raise RuntimeError("Status button not found.")
    human_delay(2.5, 5.0)
    for _ in range(2):
        if ctx.wait_text("Delay", "delay", "Right Time", "Arrived", "Departed",
                         "Expected", "Station", "Invalid", "not found", timeout_s=20):
            break
        if ctx.solve_captchas_on_page():
            ctx.click_text("Get Status", "Search", "Submit", "Go", verify_change=True)
            human_delay(2.5, 5.0)
    body = ctx.page_text()
    data = parse_live_body(body)
    data.update({"train_no": train_no, "station_filter": station or "any"})
    tables = ctx.table_texts(max_tables=2)
    if tables:
        data["table"] = tables[0][:15]
    if not data["status_lines"] and not data.get("table"):
        ctx.shot("live_empty")
        raise RuntimeError("NTES gave no readable running status (see screenshot).")
    return data


def run_tool(cfg, train_no: str, station: str = "", headless: bool | None = None) -> ToolResult:
    train_no = (train_no or "").strip()
    if not re.fullmatch(r"\d{5}", train_no):
        return ToolResult(False, {}, f"Train number must be 5 digits, got {train_no!r}.")

    def _run(ctx: BruteContext) -> ToolResult:
        data = ctx.brute(lambda: _collect(ctx, train_no, station.strip().upper()),
                         f"live status {train_no}", retries=3)
        delay = data.get("delay") or "see status lines"
        summary = f"Train {train_no} live: {delay}\n" + "\n".join(data["status_lines"][:8])
        path = ctx.save_report(f"live_{train_no}", data, summary)
        return ToolResult(True, data, f"Train {train_no}: {delay}", str(path))

    try:
        return run_with_browser(cfg, headless, _run)
    except Exception as exc:
        log.error("Live-status tool failed: %s", exc)
        return ToolResult(False, {}, f"Live-status tool failed: {exc}")
