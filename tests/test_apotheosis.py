"""Offline APOTHEOSIS tests — BRUTE ALGEBRA, titles, GENOME, CHRONOS, wiring."""

import random
import threading
from argparse import Namespace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ticket_booker.god.algebra import (
    DEFAULT_BRUTALITY,
    INT64_MAX,
    BruteAlgebraError,
    evaluate,
    parse_level,
    sat_fact,
    sat_mul,
    sat_pow,
    try_parse_level,
)
from ticket_booker.god.apotheosis import (
    apotheosis_title,
    god_depth,
    repeat_count,
    report,
    tier_name,
    warcry,
)
from ticket_booker.god.chronos import (
    ChronosError,
    arm_until,
    next_arm_datetime,
    parse_hhmm,
    seconds_until,
    wait,
)
from ticket_booker.god.genome import DEFAULT_ARMS, Genome

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


# --------------------------------------------------------------------------- #
# BRUTE ALGEBRA
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("expr", [
    "god of god of god of god",
    "god^god",
    "god**god",
    "ultimate brute god",
    "radioactive",
    "apotheosis",
    "max",
    "infinity",
    "inf",
    "too much brute",
    "9,223,372,036,854,775,807",
    "9223372036854775808",  # one past int64: saturates, never wraps
    "god!",
    "brute god!",
    "GOD OF GOD OF GOD OF GOD",
    "the ultimate brute god",
    "ultimate-brute-god",
])
def test_expressions_hit_int64_max(expr):
    assert evaluate(expr) == INT64_MAX


def test_plain_numbers_are_still_numbers():
    assert evaluate(4) == 4
    assert evaluate("4") == 4
    assert evaluate("1,000") == 1000
    assert evaluate("0") == 1  # clamped: the dial never stops
    assert evaluate(-100) == 1


def test_arithmetic_and_right_associativity():
    assert evaluate("2^10") == 1024
    assert evaluate("god * 2") == 2_000_000
    assert evaluate("god * god * god") == 10**18  # below int64 max: no false saturation
    assert evaluate("2^3^2") == 512  # 2^(3^2), not (2^3)^2
    assert evaluate("3!") == 6
    assert evaluate("(brute)!") == 120
    assert evaluate("(god of god) * god!") == INT64_MAX


def test_saturating_math_never_wraps():
    assert sat_pow(2, 63) == INT64_MAX
    assert sat_pow(2, 62) == 2 ** 62
    assert sat_mul(INT64_MAX, 2) == INT64_MAX
    assert sat_fact(20) == 2432902008176640000
    assert sat_fact(21) == INT64_MAX


def test_unknown_garbage_is_rejected():
    for bad in ("", "   ", "god of", "god of banana", "god - god", "(god", "god)",
                "2 $ 3", "of god", "god 2", "x" * 300):
        with pytest.raises(BruteAlgebraError):
            evaluate(bad)


def test_parse_level_fallback_for_webui():
    assert parse_level("7") == 7
    assert try_parse_level("nonsense", fallback=9) == 9
    assert try_parse_level(None, fallback=4) == 4
    with pytest.raises(BruteAlgebraError):
        parse_level("nonsense")


def test_default_warcry_is_the_whole_dial():
    assert evaluate(DEFAULT_BRUTALITY) == INT64_MAX


# --------------------------------------------------------------------------- #
# APOTHEOSIS titles
# --------------------------------------------------------------------------- #

def test_classic_titles_unchanged():
    assert apotheosis_title(4) == "GOD"
    assert apotheosis_title(5) == "ULTIMATE GOD"
    assert apotheosis_title(7) == "OMEGA GOD^3"


def test_titles_stack_one_god_per_digit():
    assert apotheosis_title(10).count("ULTIMATE BRUTE GOD") == 1
    assert apotheosis_title(99).count("ULTIMATE BRUTE GOD") == 1
    assert apotheosis_title(100).count("ULTIMATE BRUTE GOD") == 2
    assert apotheosis_title(10_000).count("ULTIMATE BRUTE GOD") == 4


def test_max_title_is_nine_gods_deep():
    title = apotheosis_title(INT64_MAX)
    assert title.count("ULTIMATE BRUTE GOD") == 9
    assert "OF THE ULTIMATE BRUTE GOD" in title
    assert title.endswith("RADIOACTIVE LVL 9223372036854775807")
    assert god_depth(INT64_MAX) == 8
    assert repeat_count(INT64_MAX) == 9


def test_report_for_default_warcry():
    r = report(None)
    assert r["expression"] == DEFAULT_BRUTALITY
    assert r["level"] == INT64_MAX and r["at_max"] is True
    assert r["tier"] == "RADIOACTIVE"
    assert r["level_text"] == "9,223,372,036,854,775,807"
    assert "WITHOUT END" in r["warcry"]
    assert "9x THE ULTIMATE BRUTE GOD" in r["warcry"]


def test_report_for_smaller_expression():
    r = report("brute god")
    assert r["level"] == 1_000_000_000 and r["at_max"] is False
    assert r["tier"] == "RADIOACTIVE"
    assert r["title"].endswith("RADIOACTIVE LVL 1,000,000,000")
    assert tier_name(INT64_MAX) == "RADIOACTIVE"


# --------------------------------------------------------------------------- #
# GENOME — strategy DNA
# --------------------------------------------------------------------------- #

def test_genome_explores_untried_strategies(tmp_path):
    g = Genome(tmp_path / "genome.json")
    assert g.best() is None
    picks = {g.choose(rng=random.Random(seed)) for seed in range(20)}
    assert picks <= set(DEFAULT_ARMS)
    assert len(picks) >= 2  # random exploration, not stuck on one arm


def test_genome_learns_and_persists(tmp_path):
    path = tmp_path / "genome.json"
    g = Genome(path)
    for _ in range(5):
        g.record("text", 1.0)
    g.record("xpath", 0.0)
    assert g.best() == "text"
    reloaded = Genome(path)
    assert reloaded.stats["text"]["plays"] == 5
    assert reloaded.stats["text"]["wins"] == 5
    assert reloaded.best() == "text"
    assert reloaded.summary()["plays"] == 6


def test_genome_ucb_prefers_winner(tmp_path):
    g = Genome(tmp_path / "genome.json")
    for _ in range(10):
        g.record("text", 1.0)
    for _ in range(2):
        g.record("xpath", 0.0)
    assert g.choose(arms=["text", "xpath"]) == "text"
    assert g.mean("text") == 1.0 and g.mean("xpath") == 0.0


def test_genome_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "genome.json"
    path.write_text("{not json", encoding="utf-8")
    g = Genome(path)
    assert all(v["plays"] == 0 for v in g.stats.values())
    g.record("css", 1.0)
    assert Genome(path).best() == "css"


def test_genome_decay_and_reset(tmp_path):
    path = tmp_path / "genome.json"
    g = Genome(path)
    g.record("js", 1.0)
    g.decay(0.5)
    assert g.mean("js") == 0.5
    g.reset()
    assert g.best() is None
    assert Genome(path).summary()["plays"] == 0


def test_genome_rank_orders_by_mean(tmp_path):
    g = Genome(tmp_path / "genome.json")
    g.record("text", 1.0)
    g.record("text", 1.0)
    g.record("xpath", 0.0)
    rows = g.rank()
    assert rows[0]["arm"] == "text" and rows[0]["plays"] == 2


# --------------------------------------------------------------------------- #
# CHRONOS — the warbell
# --------------------------------------------------------------------------- #

def test_parse_hhmm_variants():
    assert parse_hhmm("09:59:55") == (9, 59, 55)
    assert parse_hhmm("10:00") == (10, 0, 0)
    assert parse_hhmm("1000") == (10, 0, 0)
    assert parse_hhmm("100055") == (10, 0, 55)
    assert parse_hhmm("10") == (10, 0, 0)
    assert parse_hhmm("10.00") == (10, 0, 0)
    for bad in ("", "25:00", "10:99", "abc", "1:2:3:4"):
        with pytest.raises(ChronosError):
            parse_hhmm(bad)


def test_seconds_until_and_tomorrow_rollover():
    now = datetime(2026, 10, 20, 9, 50, 0)
    assert seconds_until("10:00", now=now) == 600
    assert seconds_until("10:00", now=now, lead=5) == 595
    assert seconds_until("09:00", now=now) > 23 * 3600  # tomorrow
    assert next_arm_datetime("10:00", now=datetime(2026, 10, 20, 10, 0, 0)) == \
        datetime(2026, 10, 21, 10, 0, 0)
    assert seconds_until("10:00", now=now, lead=99999) == 0


def test_wait_sleeps_in_chunks():
    slept = []
    assert wait(70, sleep_fn=slept.append, chunk=30) == 70
    assert slept == [30, 30, 10]
    ticks = []
    wait(5, sleep_fn=lambda s: None, on_tick=ticks.append, chunk=2)
    assert ticks[-1] == 0


def test_arm_until_fires_with_fake_clock():
    class Clock:
        def __init__(self):
            self.now = datetime(2026, 10, 20, 9, 59, 0)
            self.slept = 0.0

        def now_fn(self):
            return self.now

        def sleep(self, seconds):
            self.slept += seconds
            self.now += timedelta(seconds=seconds)

    clock = Clock()
    ticks = []
    waited = arm_until("10:00", lead=5, now_fn=clock.now_fn,
                       sleep_fn=clock.sleep, on_tick=ticks.append, chunk=20)
    assert waited == 55
    assert clock.now == datetime(2026, 10, 20, 9, 59, 55)
    assert ticks and ticks[-1] == 0


def test_arm_until_blank_is_noop():
    assert arm_until("") == 0.0
    assert arm_until(None) == 0.0


# --------------------------------------------------------------------------- #
# CLI + WebUI + base wiring
# --------------------------------------------------------------------------- #

def test_cli_accepts_expressions():
    from ticket_booker.cli import build_parser

    args = build_parser().parse_args(
        ["tool", "live", "--train", "12430", "--brutality", "god of god of god of god"])
    assert args.brutality == INT64_MAX
    assert build_parser().parse_args(["ascend", "god^god"]).expression == "god^god"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["tool", "live", "--brutality", "banana"])


def test_cli_ascend_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from ticket_booker.cli import cmd_ascend

    assert cmd_ascend(Namespace(expression="god of god of god of god")) == 0
    out = capsys.readouterr().out
    assert "9,223,372,036,854,775,807" in out and "APOTHEOSIS" in out
    assert cmd_ascend(Namespace(expression="banana")) == 2


def test_dashboard_offers_apotheosis(tmp_path):
    pytest.importorskip("flask")
    from ticket_booker.webui.server import create_app

    cfg = tmp_path / "config.json"
    cfg.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    client = create_app(str(cfg)).test_client()
    html = client.get("/").get_data(as_text=True)
    assert "APOTHEOSIS" in html and "god of god of god of god" in html


def test_webui_parses_expression_and_rejects_garbage(tmp_path, monkeypatch):
    pytest.importorskip("flask")
    import ticket_booker.webui.server as server

    seen = {}
    done = threading.Event()

    def fake_job(app, job_id, kind, payload):
        seen.update(payload)
        done.set()

    monkeypatch.setattr(server, "_run_job", fake_job)
    cfg = tmp_path / "config.json"
    cfg.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    client = server.create_app(str(cfg)).test_client()

    bad = client.post("/api/run", json={"kind": "login", "brutality": "banana"})
    assert bad.status_code == 400 and "bad GOD dial" in bad.get_json()["error"]

    ok = client.post("/api/run", json={"kind": "login",
                                       "brutality": "god of god of god of god"})
    assert ok.status_code == 200 and done.wait(2)
    assert seen["brutality"] == INT64_MAX


def test_preflight_warbell_check():
    from ticket_booker.config import load_config
    from ticket_booker.god.preflight import preflight

    cfg = load_config(EXAMPLE)
    cfg.journey.date = (date.today() + timedelta(days=3)).isoformat()
    cfg.brute.arm_at = "09:59:55"
    res = preflight(cfg)
    arm = next(c for c in res.checks if c["name"] == "arm.warbell")
    assert arm["ok"] is True and "09:59:55" in arm["msg"]

    cfg.brute.arm_at = "99:99"
    res = preflight(cfg)
    arm = next(c for c in res.checks if c["name"] == "arm.warbell")
    assert arm["ok"] is False

    cfg.brute.arm_at = ""
    res = preflight(cfg)
    assert all(c["name"] != "arm.warbell" for c in res.checks)


def test_brute_context_wires_genome_at_radioactive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from types import SimpleNamespace

    from ticket_booker.config import BruteCfg, CaptchaCfg
    from ticket_booker.god.chaos import ScriptedPage
    from ticket_booker.tools.base import BruteContext

    cfg = SimpleNamespace(captcha=CaptchaCfg(), brute=BruteCfg(level=INT64_MAX))
    ctx = BruteContext(cfg, ScriptedPage("x"), False)
    assert ctx.genome is not None
    ctx._record_win("login", "text")
    assert ctx.genome.best() == "text"
    assert (tmp_path / "profiles" / "genome.json").exists()
