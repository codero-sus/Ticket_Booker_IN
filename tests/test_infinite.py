"""Offline GOD7 tests — INFINITE BRUTE VOID: unbounded algebra, void tier, omni solver."""

from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest

from ticket_booker.god.algebra import (
    INT64_MAX,
    VOID_THRESHOLD,
    BruteAlgebraError,
    evaluate,
    evaluate_raw,
    format_level,
    is_void,
    parse_level,
    parse_level_raw,
)
from ticket_booker.god.apotheosis import apotheosis_title
from ticket_booker.captcha.base import CaptchaResult
from ticket_booker.god.infinite import OmniSolver, void_behavior, void_title
from ticket_booker.god.signals import tier_of, title_for_level


# --------------------------------------------------------------------------- #
# unbounded algebra
# --------------------------------------------------------------------------- #

def test_saturating_still_caps_at_int64_max():
    assert evaluate("god of god of god of god") == INT64_MAX
    assert evaluate("void") == INT64_MAX  # constant is VOID_THRESHOLD, clamped
    assert evaluate("infinity") == INT64_MAX  # googol clamped


def test_raw_breaks_the_ceiling_into_void():
    v = evaluate_raw("god of god of god of god")
    assert v > INT64_MAX  # raw power tower exceeds the ceiling
    assert is_void(v)

    assert evaluate_raw("void") == VOID_THRESHOLD
    assert is_void(VOID_THRESHOLD)

    inf = evaluate_raw("infinity")
    assert inf > INT64_MAX
    assert is_void(inf)

    assert evaluate_raw("singularity") == 2 ** 256
    assert evaluate_raw("beyond") == 2 ** 512


def test_raw_plain_numbers_and_expressions():
    assert evaluate_raw(4) == 4
    assert evaluate_raw("7") == 7
    assert evaluate_raw("2^10") == 1024
    assert evaluate_raw("god * 2") == 2_000_000
    assert evaluate_raw("brute!") == 120


def test_parse_level_raw_vs_saturating():
    assert parse_level("void") == INT64_MAX  # saturating clamps
    assert parse_level_raw("void") == VOID_THRESHOLD  # raw keeps it
    assert parse_level_raw("god of god of god of god") > INT64_MAX


def test_is_void():
    assert is_void(INT64_MAX) is False
    assert is_void(INT64_MAX + 1) is True
    assert is_void(10**100) is True
    assert is_void(4) is False
    assert is_void("banana") is False


def test_format_level_big():
    s = format_level(VOID_THRESHOLD)
    assert "9,223,372,036,854,775,808" in s


# --------------------------------------------------------------------------- #
# void tier / titles
# --------------------------------------------------------------------------- #

def test_tier_of_void_is_8():
    assert tier_of(INT64_MAX) == 7  # RADIOACTIVE
    assert tier_of(VOID_THRESHOLD) == 8  # VOID
    assert tier_of(10**100) == 8


def test_title_for_level_void():
    assert "RADIOACTIVE LVL 9223372036854775807" in title_for_level(INT64_MAX)
    assert "INFINITE BRUTE VOID LVL" in title_for_level(VOID_THRESHOLD)
    assert "INFINITE BRUTE VOID LVL 1" in title_for_level(10**100)


def test_apotheosis_title_void():
    t = apotheosis_title(VOID_THRESHOLD)
    assert t.count("ULTIMATE BRUTE GOD") == 9  # still 9-deep stack
    assert "INFINITE BRUTE VOID LVL 9,223,372,036,854,775,808" in t


def test_void_title():
    assert void_title(VOID_THRESHOLD) == "INFINITE BRUTE VOID LVL 9,223,372,036,854,775,808"


# --------------------------------------------------------------------------- #
# void behavior
# --------------------------------------------------------------------------- #

def test_void_behavior_flags():
    b = void_behavior(VOID_THRESHOLD)
    assert b["immortal"] is True
    assert b["no_pacer"] is True
    assert b["retry_floor"] == 50
    assert b["screenshot_every_step"] is True
    assert b["genome_aggressive"] is True
    assert b["hydra_heads_uncapped"] is True
    assert b["omni_captcha"] is True

    normal = void_behavior(4)
    assert normal == {}


# --------------------------------------------------------------------------- #
# omni solver — parallel, first non-empty OK wins
# --------------------------------------------------------------------------- #

class _FakeSolver:
    def __init__(self, name, result=None, delay=0.0, fail=False):
        self.name = name
        self.result = result
        self.delay = delay
        self.fail = fail
        self.called = False

    def available(self):
        return True

    def solve_image(self, image_bytes):
        import time

        self.called = True
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        from ticket_booker.captcha.base import CaptchaResult

        return CaptchaResult(text=self.result or "", solver=self.name)


def test_omni_returns_first_non_empty_ok():
    from ticket_booker.captcha.base import CaptchaResult

    slow = _FakeSolver("slow", result="ABCD", delay=0.2)
    fast = _FakeSolver("fast", result="WXYZ", delay=0.01)
    omni = OmniSolver([slow, fast], timeout=5.0)
    res = omni.solve_text_image(b"image")
    assert res.ok is True
    assert res.text == "WXYZ"
    assert res.solver == "fast"


def test_omni_skips_failed_and_empty():
    bad = _FakeSolver("bad", fail=True)
    empty = _FakeSolver("empty", result="")
    good = _FakeSolver("good", result="OK123")
    omni = OmniSolver([bad, empty, good], timeout=5.0)
    res = omni.solve_text_image(b"image")
    assert res.ok is True
    assert res.text == "OK123"


def test_omni_no_solvers_uses_fallback():
    omni = OmniSolver([], timeout=5.0)
    res = omni.solve_text_image(b"image", fallback=lambda b: None)
    assert res is None


def test_omni_timeout_falls_back():
    slow = _FakeSolver("slow", result="LATE", delay=5.0)
    omni = OmniSolver([slow], timeout=0.01)
    res = omni.solve_text_image(b"image", fallback=lambda b: CaptchaResult(solver="none"))
    assert res is not None and res.solver == "none"


# --------------------------------------------------------------------------- #
# CLI / WebUI raw parsing
# --------------------------------------------------------------------------- #

def test_cli_brutality_enters_void():
    from ticket_booker.cli import build_parser

    args = build_parser().parse_args(
        ["tool", "live", "--train", "12430", "--brutality", "void"])
    assert args.brutality == VOID_THRESHOLD
    assert is_void(args.brutality)

    args = build_parser().parse_args(
        ["tool", "live", "--train", "12430", "--brutality", "god of god of god of god"])
    assert args.brutality > INT64_MAX  # raw: four gods deep breaks the ceiling

    with pytest.raises(SystemExit):
        build_parser().parse_args(["tool", "live", "--brutality", "banana"])


def test_dashboard_offers_void():
    pytest.importorskip("flask")
    from ticket_booker.webui.server import create_app
    from pathlib import Path

    EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(EXAMPLE.read_text(encoding="utf-8"))
        cfg = f.name
    try:
        client = create_app(cfg).test_client()
        html = client.get("/").get_data(as_text=True)
        assert "INFINITE VOID" in html and "void" in html
    finally:
        Path(cfg).unlink(missing_ok=True)
