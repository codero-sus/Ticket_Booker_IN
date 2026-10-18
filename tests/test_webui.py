"""Offline WebUI tests — Flask test client (no browser, no network)."""

import io
import json
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

from ticket_booker.webui.launcher import find_chrome, free_port  # noqa: E402
from ticket_booker.webui.server import create_app, doctor_data  # noqa: E402

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _client(tmp_path, with_config: bool = True):
    cfg_path = tmp_path / "config.json"
    if with_config:
        cfg_path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return create_app(str(cfg_path)).test_client(), cfg_path


def test_health_and_index(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/api/health").get_json()["ok"] is True
    html = c.get("/").get_data(as_text=True)
    assert "Ticket_Booker_IN" in html and "Live Log" in html


def test_tools_and_doctor_endpoints(tmp_path):
    c, _ = _client(tmp_path)
    tools = c.get("/api/tools").get_json()
    assert set(tools) == {"pnr", "availability", "schedule", "fare", "live"}
    doc = c.get("/api/doctor").get_json()
    assert "checks" in doc and any("config:" in ch["name"] for ch in doc["checks"])


def test_doctor_data_offline_safe(tmp_path):
    d = doctor_data(str(tmp_path / "nope.json"))
    assert isinstance(d["ok"], bool) and d["checks"]


def test_config_get_save_roundtrip(tmp_path):
    c, path = _client(tmp_path)
    got = c.get("/api/config").get_json()
    assert got["ok"] is True and "NDLS" in got["content"]
    # invalid JSON rejected
    bad = c.post("/api/config", json={"content": "{oops"})
    assert bad.status_code == 400
    # invalid schema rejected
    bad2 = c.post("/api/config", json={"content": json.dumps({"journey": {}})})
    assert bad2.status_code == 400
    # valid roundtrip
    data = json.loads(got["content"])
    data["journey"]["to_station"] = "LKO"
    ok = c.post("/api/config", json={"content": json.dumps(data)})
    assert ok.get_json()["ok"] is True
    assert "LKO" in path.read_text(encoding="utf-8")


def test_config_missing_404(tmp_path):
    c, _ = _client(tmp_path, with_config=False)
    assert c.get("/api/config").status_code == 404


def test_solve_captcha_endpoint_graceful(tmp_path):
    """Works with or without the tesseract binary (never 500s)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (200, 70), "white")
    ImageDraw.Draw(img).text((25, 15), "X4K9P2", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c, _ = _client(tmp_path)
    r = c.post("/api/solve-captcha", data={"image": (buf, "c.png")},
               content_type="multipart/form-data")
    j = r.get_json()
    assert r.status_code == 200 and "solver" in j and "text" in j


def test_jobs_and_reports_empty(tmp_path):
    c, _ = _client(tmp_path)
    jobs = c.get("/api/jobs").get_json()
    assert jobs["ok"] is True and isinstance(jobs["jobs"], list)
    assert c.get("/api/jobs/job-999").status_code == 404
    rep = c.get("/api/reports").get_json()
    assert rep["ok"] is True and isinstance(rep["reports"], list)


def test_logs_endpoint(tmp_path):
    c, _ = _client(tmp_path)
    j = c.get("/api/logs?since=0").get_json()
    assert j["ok"] is True and "logs" in j and "next" in j


def test_launcher_helpers():
    chrome = find_chrome()  # None in sandbox is fine — must not crash
    assert chrome is None or Path(chrome).exists() or isinstance(chrome, str)
    port = free_port(8787)
    assert isinstance(port, int) and port >= 8787
