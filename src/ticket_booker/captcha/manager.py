"""AutoCaptcha — orchestrates the solver chain with zero-touch default."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import CaptchaCfg
from .base import BaseSolver, CaptchaResult
from .buster import BusterSolver, BusterResult
from .gemini_solver import GeminiSolver
from .ocr_solver import OcrSolver
from .service_solver import AntiCaptchaSolver, TwoCaptchaSolver

log = logging.getLogger("ticket_booker.captcha")

#: Below this confidence, an OCR answer gets a Gemini Nano second opinion.
NANO_REPAIR_BELOW = 60.0


class AutoCaptcha:
    """Tries solvers in order: Gemini -> OCR -> paid service. Never prompts by
    itself; the caller (login flow) decides on manual fallback via
    cfg.on_failure."""

    def __init__(self, cfg: CaptchaCfg) -> None:
        self.cfg = cfg
        self.solvers: list[BaseSolver] = []
        self.gemini: GeminiSolver | None = None

        bcfg = getattr(cfg, "buster", None)
        self.buster: BusterSolver | None = None
        if bcfg is not None and getattr(bcfg, "enabled", False):
            self.buster = BusterSolver(
                mode=bcfg.mode,
                timeout=bcfg.timeout,
                max_attempts=bcfg.max_attempts,
                solve_checkbox=bcfg.solve_checkbox,
                language=bcfg.language,
            )

        gcfg = getattr(cfg, "gemini", None)
        if gcfg is not None and gcfg.enabled:
            self.gemini = GeminiSolver(
                api_key=gcfg.api_key,
                model=gcfg.model,
                base_url=gcfg.base_url,
                mode=gcfg.mode,
                timeout=gcfg.timeout,
                max_variants=gcfg.max_variants,
                repair_ocr=gcfg.repair_ocr,
                temperature=gcfg.temperature,
                cache_path=gcfg.cache,
            )
            self.solvers.append(self.gemini)

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
        if not any(s.available() for s in self.solvers) and not self.nano_pending:
            if cfg.mode == "auto":
                log.warning(
                    "No automatic captcha solver is available! Install tesseract "
                    "(`sudo apt install tesseract-ocr`), set GEMINI_API_KEY, or set "
                    "captcha.mode=manual. Run `ticket-booker doctor` for a checkup."
                )

    @property
    def nano_pending(self) -> bool:
        """True when on-device Gemini Nano will come online once a page exists."""
        return self.gemini is not None and self.gemini.mode in ("auto", "nano")

    def attach_page(self, page) -> None:
        """Hand the live browser page to solvers that run inside it."""
        if self.buster is not None:
            self.buster.set_page(page)
        for solver in self.solvers:
            hook = getattr(solver, "set_page", None)
            if hook is None:
                continue
            try:
                hook(page)
            except Exception as exc:  # never break a booking over a solver
                log.debug("could not attach page to %s: %s", solver.name, exc)

    def _polish(self, res: CaptchaResult) -> CaptchaResult:
        """Give a shaky OCR reading one Gemini Nano repair pass."""
        if self.gemini is None or not res.ok:
            return res
        if res.solver == self.gemini.name or res.confidence >= NANO_REPAIR_BELOW:
            return res
        fixed = self.gemini.polish(res.text)
        if fixed and fixed != res.text:
            return CaptchaResult(
                text=fixed,
                confidence=max(res.confidence, 70.0),
                solver=f"{res.solver}+nano",
            )
        return res

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
                    return self._polish(res)
                last = res
            except Exception as exc:
                log.warning("Solver %s errored: %s", solver.name, exc)
        return last

    def solve_recaptcha(self, page=None) -> BusterResult:
        """Click the Buster icon then PLAY - the requested reCAPTCHA path.

        Falls back to the legacy Buster-style audio solver when the bridge
        is disabled, so behaviour never regresses.
        """
        target = page if page is not None else (self.buster.page if self.buster else None)
        if self.buster is not None and target is not None:
            try:
                result = self.buster.solve(target)
                if result.solved:
                    return result
                log.warning("Buster bridge could not solve: %s", result.message)
            except Exception as exc:  # never break a login over reCAPTCHA
                log.warning("Buster bridge errored: %s", exc)
        if target is None:
            return BusterResult(False, message="buster: no page attached")
        from .recaptcha_solver import solve_recaptcha_if_present

        try:
            ok = solve_recaptcha_if_present(target, language=self._language())
        except Exception as exc:
            log.warning("legacy reCAPTCHA solver errored: %s", exc)
            ok = False
        return BusterResult(
            bool(ok), method="native" if ok else "none",
            message="legacy audio solver" if ok else "reCAPTCHA unsolved",
        )

    def _language(self) -> str:
        bcfg = getattr(self.cfg, "buster", None)
        return str(getattr(bcfg, "language", "en") or "en")

    def buster_status(self) -> dict:
        bcfg = getattr(self.cfg, "buster", None)
        if self.buster is None:
            return {"enabled": False}
        info = self.buster.status()
        info["enabled"] = True
        info["extension_path"] = getattr(bcfg, "extension_path", "")
        info["extension_on_disk"] = bool(
            getattr(bcfg, "extension_path", "")
            and Path(getattr(bcfg, "extension_path", "")).exists()
        )
        return info

    @property
    def wants_manual_fallback(self) -> bool:
        return self.cfg.on_failure == "manual" and self.cfg.mode != "manual"
