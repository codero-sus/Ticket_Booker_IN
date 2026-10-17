"""AutoCaptcha — orchestrates the solver chain with zero-touch default."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import CaptchaCfg
from .base import BaseSolver, CaptchaResult
from .ocr_solver import OcrSolver
from .service_solver import AntiCaptchaSolver, TwoCaptchaSolver

log = logging.getLogger("ticket_booker.captcha")


class AutoCaptcha:
    """Tries solvers in order: OCR -> paid service. Never prompts by itself;
    the caller (login flow) decides on manual fallback via cfg.on_failure."""

    def __init__(self, cfg: CaptchaCfg) -> None:
        self.cfg = cfg
        self.solvers: list[BaseSolver] = []
        if cfg.ocr.enabled:
            self.solvers.append(
                OcrSolver(
                    psm_modes=tuple(cfg.ocr.psm_modes),
                    min_confidence=cfg.ocr.min_confidence,
                    max_variants=cfg.ocr.max_variants,
                    debug_dir=Path(cfg.debug_dir),
                )
            )
        if cfg.service.enabled:
            cls = TwoCaptchaSolver if cfg.service.provider == "twocaptcha" else AntiCaptchaSolver
            self.solvers.append(
                cls(api_key=cfg.service.api_key, poll_timeout=cfg.service.poll_timeout)
            )
        for solver in self.solvers:
            if solver.available():
                log.info("Captcha solver ready: %s", solver.name)
            else:
                log.warning("Captcha solver unavailable: %s", solver.availability_reason())
        if cfg.mode == "manual":
            log.info("Captcha mode=manual: auto solvers will be skipped.")
        if not any(s.available() for s in self.solvers) and cfg.mode == "auto":
            log.warning(
                "No automatic captcha solver is available! "
                "Install tesseract (`sudo apt install tesseract-ocr`) or set "
                "captcha.mode=manual. Run `ticket-booker doctor` for a checkup."
            )

    def solve_text_image(self, image_bytes: bytes) -> CaptchaResult:
        """Run the chain on one captcha image. Empty result = all failed."""
        if self.cfg.mode == "manual":
            return CaptchaResult(solver="manual")
        last = CaptchaResult(solver="none")
        for solver in self.solvers:
            if not solver.available():
                continue
            try:
                res = solver.solve_image(image_bytes)
                if res.ok:
                    return res
                last = res
            except Exception as exc:
                log.warning("Solver %s errored: %s", solver.name, exc)
        return last

    @property
    def wants_manual_fallback(self) -> bool:
        return self.cfg.on_failure == "manual" and self.cfg.mode != "manual"
