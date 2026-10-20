"""Typed configuration (pydantic) with JSON/YAML loading + env overrides.

Secrets can live in the config file OR in environment variables (recommended):
  IRCTC_USER, IRCTC_PASS, IRCTC_MOBILE, IRCTC_UPI, CAPTCHA_API_KEY
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .timing import parse_journey_date

log = logging.getLogger("ticket_booker.config")

GENDERS = {"M", "F", "O", "T", "MALE", "FEMALE", "TRANSGENDER"}
BERTHS = {"LB", "UB", "MB", "SL", "SU", "WS", "CP", "SM", "CB", "NP", "NO PREFERENCE", ""}
FOODS = {"VEG", "NON VEG", "NONVEG", "NO FOOD", "NOFOOD", ""}
CLASSES = {
    "1A", "2A", "3A", "3E", "CC", "EC", "EA", "EV", "VC", "VS",
    "SL", "2S", "FC",
}
QUOTAS = {"GN", "TQ", "PT", "LD", "HO", "DF", "PH", "YU", "SS", "DP", "HP"}


class Passenger(BaseModel):
    name: str = Field(..., min_length=3, max_length=30)
    age: int = Field(..., ge=1, le=125)
    gender: str = "M"
    berth: str = ""
    food: str = ""
    senior_citizen: bool = False
    id_card_type: str = ""
    id_card_no: str = ""

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in GENDERS:
            raise ValueError(f"gender must be one of {sorted(GENDERS)}")
        return {"MALE": "M", "FEMALE": "F", "TRANSGENDER": "T"}.get(v, v)

    @field_validator("berth")
    @classmethod
    def _berth(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in BERTHS:
            raise ValueError(f"berth must be one of {sorted(b for b in BERTHS if b)}")
        return "NP" if v in ("NO PREFERENCE", "") else v

    @field_validator("food")
    @classmethod
    def _food(cls, v: str) -> str:
        v = v.strip().upper().replace("-", " ").replace("_", " ")
        v = {"NONVEG": "NON VEG", "NOFOOD": "NO FOOD"}.get(v, v)
        if v not in FOODS:
            raise ValueError(f"food must be one of {sorted(f for f in FOODS if f)}")
        return v


class Journey(BaseModel):
    from_station: str
    to_station: str
    date: str  # YYYY-MM-DD (also accepts DD-MM-YYYY / DD/MM/YYYY)
    train_no: str = ""  # 5-digit number; empty = first matching train
    class_code: str = "SL"
    quota: str = "GN"
    flexible_date: bool = False

    @field_validator("from_station", "to_station")
    @classmethod
    def _station(cls, v: str) -> str:
        v = v.strip().upper()
        if not (2 <= len(v) <= 5) or not v.isalpha():
            raise ValueError(f"station code looks invalid: {v!r} (e.g. NDLS, CNB)")
        return v

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        return parse_journey_date(v).isoformat()  # normalised to YYYY-MM-DD

    @field_validator("train_no")
    @classmethod
    def _train(cls, v: str) -> str:
        v = v.strip()
        if v and (not v.isdigit() or len(v) != 5):
            raise ValueError("train_no must be a 5-digit number like 12430")
        return v

    @field_validator("class_code")
    @classmethod
    def _class(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in CLASSES:
            raise ValueError(f"class_code must be one of {sorted(CLASSES)}")
        return v

    @field_validator("quota")
    @classmethod
    def _quota(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in QUOTAS:
            raise ValueError(f"quota must be one of {sorted(QUOTAS)}")
        return v


class IrctcAuth(BaseModel):
    username: str = ""
    password: str = ""
    mobile: str = ""
    email: str = ""


class Preferences(BaseModel):
    mobile: str = ""
    auto_upgrade: bool = False
    confirm_berths: bool = True
    travel_insurance: bool = False
    coach_preference: str = ""


class Payment(BaseModel):
    method: Literal["manual", "upi"] = "manual"
    upi_id: str = ""
    wait_minutes: int = Field(10, ge=1, le=30)


class Tatkal(BaseModel):
    enabled: bool = False
    arrive_minutes_early: int = Field(15, ge=1, le=120)
    refresh_interval_ms: int = Field(1200, ge=300, le=10000)


class GeoLocation(BaseModel):
    latitude: float = 28.6139
    longitude: float = 77.209


class BrowserCfg(BaseModel):
    headless: bool = False
    humanize: bool | float = True
    profile_dir: str = "./profiles/irctc"
    locale: str = "en-IN"
    timezone: str = "Asia/Kolkata"
    geolocation: GeoLocation = GeoLocation()
    proxy: dict[str, str] | None = None  # {"server": "...", "username": "..", "password": ".."}
    block_images: bool = False
    addons: list[str] = []  # optional .xpi paths (e.g. Buster) loaded into Camoufox


# ---------------- captcha ----------------

class OcrCfg(BaseModel):
    enabled: bool = True
    psm_modes: list[int] = [7, 8]
    min_confidence: float = 25.0
    max_variants: int = 6


class RecaptchaAudioCfg(BaseModel):
    enabled: bool = True
    language: str = "en"
    max_audio_attempts: int = 3


class CaptchaServiceCfg(BaseModel):
    enabled: bool = False
    provider: Literal["twocaptcha", "anticaptcha"] = "twocaptcha"
    api_key: str = ""  # or CAPTCHA_API_KEY env
    poll_timeout: int = Field(120, ge=10, le=300)


class GeminiCfg(BaseModel):
    """Gemini captcha settings: on-device Nano and/or cloud vision."""

    enabled: bool = True
    api_key: str = ""  # or GEMINI_API_KEY env (empty = Nano only)
    model: str = "gemini-2.5-flash"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    mode: Literal["auto", "api", "nano"] = "auto"
    timeout: float = Field(25.0, ge=3.0, le=120.0)
    max_variants: int = Field(2, ge=1, le=6)
    repair_ocr: bool = True
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    cache: str = "./profiles/captcha_cache.json"


class BusterCfg(BaseModel):
    """Buster extension bridge: click the icon, then PLAY."""

    enabled: bool = True
    mode: Literal["auto", "extension", "native"] = "auto"
    extension_path: str = "./profiles/buster/buster.xpi"
    auto_load_extension: bool = True
    timeout: float = Field(60.0, ge=5.0, le=300.0)
    max_attempts: int = Field(3, ge=1, le=10)
    solve_checkbox: bool = True
    language: str = "en"


class CaptchaCfg(BaseModel):
    mode: Literal["auto", "manual", "assist"] = "auto"
    max_attempts: int = Field(6, ge=1, le=15)
    ocr: OcrCfg = OcrCfg()
    gemini: GeminiCfg = GeminiCfg()
    buster: BusterCfg = BusterCfg()
    recaptcha_audio: RecaptchaAudioCfg = RecaptchaAudioCfg()
    service: CaptchaServiceCfg = CaptchaServiceCfg()
    on_failure: Literal["manual", "error"] = "manual"
    debug_dir: str = "./screenshots/captcha"


class BruteCfg(BaseModel):
    """GOD dial: 1-5 classic, 6-9 OMEGA, 10+ RADIOACTIVE. Default 4 (GOD)."""
    level: int = Field(4, ge=1)  # unbounded; cross INT64_MAX -> VOID
    hydra_heads: int = Field(0, ge=0, le=3)  # 0 = auto by tier
    max_tool_minutes: int = Field(25, ge=0, le=180)  # 0 = immortal, no doomsday
    memory_file: str = "./profiles/selector_memory.json"
    diagnostics: bool = True
    keepalive_checks: bool = True
    arm_at: str = ""  # CHRONOS warbell: "09:59:55" or "" (off)
    arm_lead_seconds: int = Field(5, ge=0, le=600)
    proxy_list: list[dict[str, str]] = []


class AppConfig(BaseModel):
    irctc: IrctcAuth = IrctcAuth()
    journey: Journey
    passengers: list[Passenger] = Field(..., min_length=1, max_length=6)
    preferences: Preferences = Preferences()
    payment: Payment = Payment()
    tatkal: Tatkal = Tatkal()
    browser: BrowserCfg = BrowserCfg()
    captcha: CaptchaCfg = CaptchaCfg()
    brute: BruteCfg = BruteCfg()

    @field_validator("passengers")
    @classmethod
    def _max_tatkal(cls, v: list[Passenger]) -> list[Passenger]:
        if len(v) > 6:
            raise ValueError("IRCTC allows max 6 passengers per PNR")
        return v


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path) -> AppConfig:
    """Load JSON/YAML config file, apply env overrides, validate."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}. Run `ticket-booker init-config` first."
        )
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Config root must be an object")

    # Env overrides (env wins over file)
    env_map = {
        ("irctc", "username"): "IRCTC_USER",
        ("irctc", "password"): "IRCTC_PASS",
        ("irctc", "mobile"): "IRCTC_MOBILE",
        ("preferences", "mobile"): "IRCTC_MOBILE",
        ("payment", "upi_id"): "IRCTC_UPI",
        ("captcha", "service", "api_key"): "CAPTCHA_API_KEY",
        ("captcha", "gemini", "api_key"): "GEMINI_API_KEY",
    }
    for keys, env in env_map.items():
        val = os.environ.get(env)
        if val:
            node = data
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = val
            log.debug("Config override from $%s", env)

    data.pop("_comment", None)
    cfg = AppConfig.model_validate(data)

    # If Buster's .xpi is on disk, make sure the browser actually loads it.
    if cfg.captcha.buster.enabled and cfg.captcha.buster.auto_load_extension:
        from pathlib import Path as _Path

        _xpi = _Path(cfg.captcha.buster.extension_path)
        if _xpi.exists():
            _xs = str(_xpi)
            if _xs not in cfg.browser.addons:
                cfg.browser.addons.append(_xs)
                log.info("Buster extension queued for the browser: %s", _xs)
        elif cfg.captcha.buster.mode == "extension":
            log.warning(
                "Buster mode=extension but %s is missing - run "
                "`ticket-booker buster --install`. Falling back to native.",
                _xpi,
            )

    if cfg.tatkal.enabled and len(cfg.passengers) > 4:
        log.warning("Tatkal allows max 4 passengers per PNR; you have %d.", len(cfg.passengers))
    if cfg.journey.quota == "TQ" and not cfg.tatkal.enabled:
        log.info("Quota is TQ but tatkal.enabled=false; enabling Tatkal timing.")
        cfg.tatkal.enabled = True
    return cfg
