"""Offline tool tests — pure parsers + registry (no browser)."""

import json
from pathlib import Path

from ticket_booker.tools import TOOLS
from ticket_booker.tools.availability import parse_train_rows
from ticket_booker.tools.fare import parse_fare_body
from ticket_booker.tools.live_status import parse_live_body
from ticket_booker.tools.pnr import parse_pnr_body
from ticket_booker.tools.schedule import parse_schedule_tables

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _cfg():
    from ticket_booker.config import load_config

    return load_config(EXAMPLE)


def test_registry_has_five_tools():
    assert set(TOOLS) == {"pnr", "availability", "schedule", "fare", "live"}
    for _fn, desc in TOOLS.values():
        assert isinstance(desc, str) and desc


def test_pnr_parser():
    text = """
    PNR Number: 1234567890
    Train: 12430 / NDLS - CNB
    Chart Status: CHART NOT PREPARED
    Passenger 1: Booking Status WL 12, Current Status RAC 3
    Passenger 2: Booking Status CNF, Current Status CNF
    """
    d = parse_pnr_body(text)
    assert d["pnr"] == "1234567890"
    assert d["chart_status"] == "NOT PREPARED"
    assert "CNF" in d["statuses"]
    assert any("RAC" in s for s in d["statuses"])


def test_pnr_parser_never_raises():
    assert parse_pnr_body("")["pnr"] is None
    assert parse_pnr_body(None)["statuses"] == []


def test_availability_parser():
    rows = [
        "12430 NDLS 19:00 CNB 05:00 3A AVAILABLE-0042 2A RAC-0015 SL WL-0120",
        "12582 DELHI LUCKNOW MAIL 3A REGRET SL AVAILABLE 30",
        "garbage row with no train",
    ]
    out = parse_train_rows(rows, "3A")
    assert [t["train_no"] for t in out] == ["12430", "12582"]
    assert out[0]["classes"]["3A"] == {"status": "AVAILABLE", "count": 42}
    assert out[0]["classes"]["SL"]["status"] == "WL"
    assert out[1]["classes"]["3A"]["status"] == "REGRET"


def test_schedule_parser():
    tables = [
        [[ "SNo", "Station", "Arr", "Dep" ],
         [ "1", "New Delhi (NDLS)", "Starts", "19:00" ],
         [ "2", "Kanpur Central (CNB)", "05:00", "05:10" ]],
        [["unrelated", "junk"]],
    ]
    halts = parse_schedule_tables(tables)
    assert len(halts) == 2
    assert "NDLS" in halts[0]["text"]


def test_fare_parser():
    d = parse_fare_body("Ticket Fare Rs.1,240.50\nTotal Fare Rs.1,265.60 payable")
    assert d["total_fare"] == 1265.60


def test_fare_parser_empty():
    assert parse_fare_body("no fare here")["total_fare"] is None


def test_live_parser():
    d = parse_live_body("Train 12430 delayed by 1 hrs 20 mins\nLast location: At Kanpur (CNB)")
    assert d["delay"] is not None
    assert d["status_lines"]


def test_tool_input_validation_without_browser():
    """Bad inputs fail BEFORE any browser launches."""
    from ticket_booker.tools import live_status, pnr, schedule

    cfg = _cfg()
    assert pnr.run_tool(cfg, "123").ok is False
    assert schedule.run_tool(cfg, "abc").ok is False
    assert live_status.run_tool(cfg, "99").ok is False


def test_example_config_json_parseable():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert data["journey"]["from_station"] == "NDLS"
