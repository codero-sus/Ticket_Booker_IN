"""Solver interface + shared image helpers."""

from __future__ import annotations

import io
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("ticket_booker.captcha")


class CaptchaError(Exception):
    """Raised when a solver cannot proceed (missing binary, API error...)."""


@dataclass
class CaptchaResult:
    text: str = ""
    confidence: float = 0.0  # 0-100, solver-defined
    solver: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text and self.text.strip())


class BaseSolver(ABC):
    """One captcha-solving strategy. All solvers must be safe to construct
    even when their dependencies are missing — report via available()."""

    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True if this solver can run right now (deps + binaries + keys)."""

    def availability_reason(self) -> str:
        return "" if self.available() else f"{self.name}: unavailable"

    @abstractmethod
    def solve_image(self, image_bytes: bytes) -> CaptchaResult:
        """Solve a text-captcha image. Returns empty result on failure."""


def load_pil_image(image_bytes: bytes):
    """Decode bytes to a PIL image. Raises CaptchaError on failure."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise CaptchaError(
            "Pillow is required for captcha solving: pip install pillow"
        ) from exc
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        return img.convert("RGB")
    except Exception as exc:
        raise CaptchaError(f"Could not decode captcha image: {exc}") from exc


def clean_text(text: str) -> str:
    """Normalise OCR output for IRCTC-style captchas (alphanumeric)."""
    return "".join(ch for ch in text.strip() if ch.isalnum())
