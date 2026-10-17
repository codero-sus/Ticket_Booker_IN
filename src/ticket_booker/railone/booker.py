"""RailOne adapter (honest stub with a working fallback).

RailOne = IRCTC's mobile super-app; it has no automatable public website.
So instead of pretending, this adapter:
  1. Explains the options (IRCTC web fallback / Appium / API research).
  2. Delegates train bookings to the IRCTC web booker — same inventory,
     same PNR system — while keeping a RailOne-compatible result type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger("ticket_booker.railone")


@dataclass
class RailOneResult:
    success: bool
    pnr: str | None = None
    message: str = ""
    booked_via: str = "irctc-web"


class RailOneBooker:
    """Drop-in booker that currently fulfils via IRCTC web inventory."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    def book(self) -> RailOneResult:
        log.info(
            "RailOne has no public web flow; fulfilling via IRCTC web "
            "(identical trains/PNR/fares)..."
        )
        from ..irctc.booker import IRCTCBooker

        res = IRCTCBooker(self.cfg).book()
        return RailOneResult(
            success=res.success, pnr=res.pnr, message=res.message,
            booked_via="irctc-web",
        )

    @staticmethod
    def roadmap() -> str:
        return (
            "RailOne automation roadmap:\n"
            "  [done] IRCTC-web fallback (same inventory as RailOne)\n"
            "  [todo] Appium adapter (real device / emulator + UiAutomator2)\n"
            "  [todo] Private-API research (needs MITM cert pinning bypass)\n"
            "Contributions welcome — see README."
        )
