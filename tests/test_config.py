import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ticket_booker.config import AppConfig, load_config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.json"


def _base_data():
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    data["irctc"] = {"username": "u", "password": "p", "mobile": "9876543210"}
    data["journey"]["date"] = "2026-10-20"
    return data


def test_example_config_validates():
    cfg = AppConfig.model_validate(_base_data())
    assert cfg.journey.from_station == "NDLS"
    assert cfg.journey.date == "2026-10-20"
    assert len(cfg.passengers) == 2
    # quota TQ auto-enables tatkal only via load_config; model itself is neutral
    assert cfg.captcha.max_attempts >= 1


def test_load_config_enables_tatkal_for_tq(tmp_path):
    data = _base_data()
    data["tatkal"]["enabled"] = False
    data["journey"]["quota"] = "TQ"
    f = tmp_path / "c.json"
    f.write_text(json.dumps(data))
    cfg = load_config(f)
    assert cfg.tatkal.enabled is True


def test_bad_station_rejected():
    data = _base_data()
    data["journey"]["from_station"] = "XYZ123"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_bad_train_no_rejected():
    data = _base_data()
    data["journey"]["train_no"] = "12AB"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_env_override(tmp_path, monkeypatch):
    data = _base_data()
    f = tmp_path / "c.json"
    f.write_text(json.dumps(data))
    monkeypatch.setenv("IRCTC_USER", "envuser")
    monkeypatch.setenv("IRCTC_PASS", "envpass")
    cfg = load_config(f)
    assert cfg.irctc.username == "envuser"
    assert cfg.irctc.password == "envpass"
