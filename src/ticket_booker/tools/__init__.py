"""BRUTE web-scraper tools: PNR, availability, schedule, fare, live status.

Every tool runs through :class:`BruteContext` (see base.py):
  * text-first locators (find by visible text anywhere on the page — immune
    to IRCTC/NTES DOM reshuffles, same idea as the sample grabber script),
  * automatic captcha solving wherever a captcha appears,
  * retry + page-reload + re-login recovery, human-like random delays,
  * JSON + human-readable reports saved to ./reports/.

Tools never touch payments. Booking stays in `irctc/booker.py`.
"""

from .availability import run_tool as availability_tool
from .base import BlockedError, BruteContext, ToolResult, run_with_browser
from .fare import run_tool as fare_tool
from .live_status import run_tool as live_status_tool
from .pnr import run_tool as pnr_tool
from .schedule import run_tool as schedule_tool

TOOLS = {
    "pnr": (pnr_tool, "PNR status (passengers, chart, current status)"),
    "availability": (availability_tool, "Seat/berth availability between stations"),
    "schedule": (schedule_tool, "Train schedule / route (all halts)"),
    "fare": (fare_tool, "Fare enquiry via dry-run to review page (never pays)"),
    "live": (live_status_tool, "Live running status — Spot Your Train (NTES)"),
}

__all__ = [
    "TOOLS",
    "BlockedError",
    "BruteContext",
    "ToolResult",
    "run_with_browser",
    "pnr_tool",
    "availability_tool",
    "schedule_tool",
    "fare_tool",
    "live_status_tool",
]
