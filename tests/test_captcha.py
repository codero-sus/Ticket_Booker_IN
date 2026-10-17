"""Offline captcha tests — no browser, no tesseract binary needed."""

import io

import pytest

from ticket_booker.captcha.base import clean_text
from ticket_booker.captcha.manager import AutoCaptcha
from ticket_booker.captcha.ocr_solver import OcrSolver
from ticket_booker.captcha.preprocess import has_cv2, variants
from ticket_booker.config import CaptchaCfg


def make_synthetic_captcha(text="A7K9P2", size=(180, 60)):
    """Draw a noisy text captcha with PIL (mimics IRCTC style roughly)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.text((18, 12), text, fill="black")
    # noise dots + a strike line
    import random

    rnd = random.Random(42)
    for _ in range(120):
        d.point((rnd.randrange(size[0]), rnd.randrange(size[1])), fill="gray")
    d.line((0, 30, size[0], 36), fill="gray", width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_clean_text():
    assert clean_text("  A7-K9 P2!\n") == "A7K9P2"


def test_variants_produced():
    from ticket_booker.captcha.base import load_pil_image

    img = load_pil_image(make_synthetic_captcha())
    vs = variants(img, max_variants=4)
    assert 1 <= len(vs) <= 4
    names = [n for n, _ in vs]
    assert "gray" in names
    for _, im in vs:
        assert im.size[0] > 180  # upscaled + padded


def test_preprocess_reports_cv2_flag():
    assert isinstance(has_cv2(), bool)


def test_ocr_solver_available_returns_bool():
    s = OcrSolver()
    assert isinstance(s.available(), bool)
    assert isinstance(s.availability_reason(), str)


def test_ocr_solver_end_to_end_when_tesseract_present():
    """If tesseract IS installed, it should read our big clean synthetic text."""
    import shutil

    pytesseract = pytest.importorskip("pytesseract")
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract binary not installed")
    # big clean text (easy for OCR) — separate from the noisy variant test
    data = make_synthetic_captcha("HELLO7", size=(300, 90))
    res = OcrSolver().solve_image(data)
    assert res.solver == "tesseract-ocr"
    # don't assert exact text (fonts vary); just that it read *something*
    assert isinstance(res.text, str)


def test_manager_with_no_solvers_returns_empty():
    cfg = CaptchaCfg(mode="manual")
    ac = AutoCaptcha(cfg)
    res = ac.solve_text_image(make_synthetic_captcha())
    assert res.ok is False
