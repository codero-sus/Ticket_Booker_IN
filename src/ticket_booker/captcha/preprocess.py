"""Image preprocessing variants tuned for IRCTC-style text captchas.

IRCTC captchas are distorted alphanumeric glyphs on a noisy background.
No single threshold works for all of them, so we generate several cleaned
variants and let the OCR engine score each one (best confidence wins).
Works with OpenCV when installed, degrades to pure-PIL otherwise.
"""

from __future__ import annotations

import logging

log = logging.getLogger("ticket_booker.captcha.preprocess")

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore
    _HAS_CV2 = False

try:
    import numpy as np  # type: ignore

    _HAS_NP = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    _HAS_NP = False


def has_cv2() -> bool:
    return _HAS_CV2 and _HAS_NP


def _pil_to_cv(img):
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _cv_to_pil(mat):
    from PIL import Image

    if len(mat.shape) == 2:
        return Image.fromarray(mat, mode="L").convert("RGB")
    return Image.fromarray(cv2.cvtColor(mat, cv2.COLOR_BGR2RGB))


def upscale(img, factor: int = 3):
    from PIL import Image

    w, h = img.size
    return img.resize((w * factor, h * factor), Image.LANCZOS)


def pad(img, border: int = 12, color: str = "white"):
    from PIL import ImageOps

    return ImageOps.expand(img, border=border, fill=color)


def variants(img, max_variants: int = 6) -> list[tuple[str, object]]:
    """Return [(name, PIL.Image)] preprocessing variants for OCR."""
    from PIL import Image, ImageFilter, ImageOps

    out: list[tuple[str, object]] = []
    base = upscale(img.convert("RGB"))

    def add(name: str, im) -> None:
        if len(out) < max_variants:
            out.append((name, pad(im)))

    # 1. Plain upscaled grayscale
    gray = ImageOps.grayscale(base)
    add("gray", gray.convert("RGB"))

    # 2. Median denoise + autocontrast
    denoised = gray.filter(ImageFilter.MedianFilter(size=3))
    add("median_contrast", ImageOps.autocontrast(denoised).convert("RGB"))

    if has_cv2():
        assert cv2 is not None and np is not None
        mat = _pil_to_cv(base)
        g = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
        g = cv2.medianBlur(g, 3)

        # 3. Otsu threshold
        _, otsu = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        add("otsu", _cv_to_pil(otsu))

        # 4. Adaptive gaussian threshold (handles uneven backgrounds)
        adapt = cv2.adaptiveThreshold(
            g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9
        )
        add("adaptive", _cv_to_pil(adapt))

        # 5. Otsu + morphological open (removes thin noise lines/dots)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        opened = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, kernel)
        add("otsu_open", _cv_to_pil(opened))

        # 6. Bilateral filter + Otsu (keeps edges, kills background texture)
        bil = cv2.bilateralFilter(g, 5, 75, 75)
        _, bil_t = cv2.threshold(bil, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        add("bilateral_otsu", _cv_to_pil(bil_t))
    else:  # pure-PIL fallbacks
        log.debug("OpenCV not installed; using PIL-only preprocessing.")
        add("threshold_128", gray.point(lambda p: 255 if p > 128 else 0).convert("RGB"))
        add("threshold_160", gray.point(lambda p: 255 if p > 160 else 0).convert("RGB"))
        add(
            "minfilter",
            gray.filter(ImageFilter.MinFilter(size=3)).convert("RGB"),
        )
        add(
            "maxfilter",
            gray.filter(ImageFilter.MaxFilter(size=3)).convert("RGB"),
        )

    return out[:max_variants]
