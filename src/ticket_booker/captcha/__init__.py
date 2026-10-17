"""Zero-touch automatic captcha solving.

Chain (first success wins):
  1. :class:`OcrSolver` — local Tesseract OCR with IRCTC-tuned preprocessing.
     Free, offline (needs the `tesseract` binary), solves IRCTC's text captcha.
  2. :class:`TwoCaptchaSolver` — paid 2Captcha/AntiCaptcha API (optional).
  3. :func:`solve_recaptcha_if_present` — Buster-style reCAPTCHA solver:
     clicks the checkbox, and if challenged, plays the *audio* challenge and
     transcribes it automatically. No user touch needed.
  4. Manual fallback — only when headed and `on_failure: manual`.

IRCTC login uses a text captcha (handled by 1/2). reCAPTCHA handling exists
for payment gateways / future flows that embed Google reCAPTCHA.
"""

from .base import BaseSolver, CaptchaError, CaptchaResult
from .manager import AutoCaptcha
from .ocr_solver import OcrSolver
from .recaptcha_solver import solve_recaptcha_audio, solve_recaptcha_if_present
from .service_solver import ServiceSolver, TwoCaptchaSolver

__all__ = [
    "AutoCaptcha",
    "BaseSolver",
    "CaptchaError",
    "CaptchaResult",
    "OcrSolver",
    "ServiceSolver",
    "TwoCaptchaSolver",
    "solve_recaptcha_audio",
    "solve_recaptcha_if_present",
]
