"""Zero-touch automatic captcha solving.

Chain (first success wins):
  1. :class:`OcrSolver` — local Tesseract OCR with IRCTC-tuned preprocessing.
     Free, offline (needs the `tesseract` binary), solves IRCTC's text captcha.
  2. :class:`TwoCaptchaSolver` — paid 2Captcha/AntiCaptcha API (optional).
  3. :class:`BusterSolver` — the Buster bridge. Clicks Buster's in-widget
     icon (``#solver-button``) then PLAY, or performs the identical clicks
     itself when the extension is absent. No user touch needed.
  4. Manual fallback — only when headed and `on_failure: manual`.

IRCTC login uses a text captcha (handled by 1/2). reCAPTCHA handling exists
for payment gateways / future flows that embed Google reCAPTCHA.
"""

from .base import BaseSolver, CaptchaError, CaptchaResult
from .buster import BusterSolver
from .gemini_solver import GeminiSolver
from .manager import AutoCaptcha
from .ocr_solver import OcrSolver
from .recaptcha_solver import solve_recaptcha_audio, solve_recaptcha_if_present
from .service_solver import ServiceSolver, TwoCaptchaSolver

__all__ = [
    "AutoCaptcha",
    "BaseSolver",
    "BusterSolver",
    "CaptchaError",
    "CaptchaResult",
    "GeminiSolver",
    "OcrSolver",
    "ServiceSolver",
    "TwoCaptchaSolver",
    "solve_recaptcha_audio",
    "solve_recaptcha_if_present",
]
