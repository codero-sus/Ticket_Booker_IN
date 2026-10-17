"""Local OCR solver (Tesseract) — free, offline, zero-touch.

Needs the Tesseract *binary* (the pip package is only a wrapper):
  Ubuntu/Debian:  sudo apt install tesseract-ocr
  macOS:          brew install tesseract
  Windows:        install from https://github.com/UB-Mannheim/tesseract/wiki
                  then add it to PATH.

Strategy: run every preprocessing variant through Tesseract with PSM 7/8
(single line/word), whitelist alphanumerics, and keep the result with the
best mean character confidence.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .base import BaseSolver, CaptchaResult, CaptchaError, clean_text, load_pil_image
from .preprocess import variants

log = logging.getLogger("ticket_booker.captcha.ocr")

CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


class OcrSolver(BaseSolver):
    name = "tesseract-ocr"

    def __init__(
        self,
        psm_modes: tuple[int, ...] | list[int] = (7, 8),
        min_confidence: float = 25.0,
        max_variants: int = 6,
        debug_dir: str | Path | None = None,
    ) -> None:
        self.psm_modes = tuple(psm_modes)
        self.min_confidence = min_confidence
        self.max_variants = max_variants
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self._reason = ""

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            self._reason = "pytesseract not installed (pip install pytesseract)"
            return False
        if not shutil.which("tesseract"):
            self._reason = (
                "tesseract binary not found. Install it: "
                "`sudo apt install tesseract-ocr` (Ubuntu/Debian), "
                "`brew install tesseract` (macOS)."
            )
            return False
        return True

    def availability_reason(self) -> str:
        self.available()
        return self._reason

    def _ocr_once(self, image, psm: int) -> tuple[str, float]:
        import pytesseract

        config = (
            f"--psm {psm} --oem 3 -c tessedit_char_whitelist={CHARSET} "
            "-c load_system_dawg=0 -c load_freq_dawg=0"
        )
        try:
            data = pytesseract.image_to_data(
                image, config=config, output_type=pytesseract.Output.DICT
            )
        except Exception as exc:
            log.debug("tesseract psm=%d failed: %s", psm, exc)
            return "", 0.0
        words: list[str] = []
        confs: list[float] = []
        for txt, conf in zip(data.get("text", []), data.get("conf", [])):
            try:
                c = float(conf)
            except (TypeError, ValueError):
                c = -1.0
            if txt and txt.strip() and c >= 0:
                words.append(txt.strip())
                confs.append(c)
        text = clean_text("".join(words))
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        return text, mean_conf

    def solve_image(self, image_bytes: bytes) -> CaptchaResult:
        if not self.available():
            raise CaptchaError(self.availability_reason())
        img = load_pil_image(image_bytes)
        best = CaptchaResult(solver=self.name)

        for variant_name, variant_img in variants(img, self.max_variants):
            for psm in self.psm_modes:
                text, conf = self._ocr_once(variant_img, psm)
                log.debug("ocr variant=%s psm=%d -> %r (conf=%.1f)", variant_name, psm, text, conf)
                plausible = 3 <= len(text) <= 8
                if text and plausible and conf > best.confidence:
                    best = CaptchaResult(text=text, confidence=conf, solver=self.name)

        if self.debug_dir is not None:
            try:
                self.debug_dir.mkdir(parents=True, exist_ok=True)
                from ..utils import timestamp

                img.save(self.debug_dir / f"{timestamp()}_captcha_raw.png")
            except Exception:
                pass

        if best.ok and best.confidence >= self.min_confidence:
            log.info("OCR solved captcha: %r (conf=%.1f)", best.text, best.confidence)
            return best
        # Return low-confidence guess anyway — caller decides to retry with a
        # fresh captcha; an empty result signals "no usable reading".
        if best.ok:
            log.info(
                "OCR low-confidence reading %r (conf=%.1f) — will retry.",
                best.text, best.confidence,
            )
        else:
            log.info("OCR could not read captcha.")
        return best
