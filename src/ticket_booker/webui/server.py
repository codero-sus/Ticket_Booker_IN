"""Flask dashboard backend: jobs, logs (SSE), config, tools, captcha test."""

from __future__ import annotations

import itertools
import json
import logging
import queue
import shutil
import threading
import time
from collections import deque
from pathlib import Path

from .. import __version__

log = logging.getLogger("ticket_booker.webui")

DEFAULT_PORT = 8765


class _LogBuffer(logging.Handler):
    """Fan-out root ticket_booker logs to an in-memory deque + SSE queues."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.entries: deque = deque(maxlen=800)
        self.counter = itertools.count(1)
        self.subscribers: set[queue.Queue] = set()
        # NOTE: must NOT be named `self.lock` — logging.Handler.handle()
        # already holds Handler.lock (RLock) while emit() runs, so reusing
        # that name with a plain Lock deadlocks. Separate buffer lock:
        self.buf_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        item = {"id": next(self.counter), "time": time.strftime("%H:%M:%S"),
                "level": record.levelname, "msg": msg}
        with self.buf_lock:
            self.entries.append(item)
            dead = []
            for q in self.subscribers:
                try:
                    q.put_nowait(item)
                except Exception:
                    dead.append(q)
            for q in dead:
                self.subscribers.discard(q)


LOGS = _LogBuffer()
LOGS.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
JOB_COUNTER = itertools.count(1)


def _attach_logs() -> None:
    root = logging.getLogger("ticket_booker")
    if LOGS not in root.handlers:
        root.addHandler(LOGS)
    root.setLevel(logging.INFO)


def doctor_data(config_path: str | None = None) -> dict:
    """JSON version of the `doctor` checks (offline-safe)."""
    import importlib.util

    checks: list[dict] = []
    ok_all = True

    def check(name: str, good: bool, hint: str = ""):
        nonlocal ok_all
        if not good:
            ok_all = False
        checks.append({"name": name, "ok": good, "hint": hint})

    for mod, pip_name in (
        ("camoufox", "camoufox"), ("playwright", "playwright"),
        ("pydantic", "pydantic"), ("PIL", "pillow"),
        ("cv2", "opencv-python-headless"), ("pytesseract", "pytesseract"),
        ("speech_recognition", "SpeechRecognition"), ("ntplib", "ntplib"),
    ):
        check(f"py:{pip_name}", importlib.util.find_spec(mod) is not None,
              f"pip install {pip_name}")
    check("bin:tesseract", shutil.which("tesseract") is not None,
          "sudo apt install tesseract-ocr")
    try:
        from camoufox.pkgman import installed_verstr

        check(f"camoufox:{installed_verstr()}", True)
    except Exception:
        check("camoufox binaries", False, "run: camoufox fetch")
    if config_path and Path(config_path).exists():
        try:
            from ..config import load_config

            cfg = load_config(config_path)
            check(f"config:{config_path}", True)
            j = cfg.journey
            extra = (f"{j.from_station}->{j.to_station} {j.date} "
                     f"{j.train_no or 'any'}/{j.class_code}/{j.quota}")
            checks.append({"name": f"journey:{extra}", "ok": True, "hint": ""})
        except Exception as exc:
            check(f"config:{config_path}", False, str(exc)[:200])
    try:
        from ..god.session_vault import vault_status
        mem_keys = 0
        _mp = Path("./profiles/selector_memory.json")
        if _mp.exists():
            try:
                mem_keys = len(json.loads(_mp.read_text(encoding="utf-8") or "{}"))
            except Exception:
                mem_keys = 0
        god = {"memory_keys": mem_keys, "vault": vault_status()}
    except Exception:
        god = {}
    return {"ok": ok_all, "checks": checks, "version": __version__, "god": god}


def create_app(config_path: str | None = None):
    from flask import Flask, jsonify, request, Response

    _attach_logs()
    app = Flask(__name__)
    app.config["TB_CONFIG"] = config_path or "config.json"
    dashboard = (Path(__file__).with_name("dashboard.html")).read_text(encoding="utf-8")

    # ---------------- pages ----------------
    @app.get("/")
    def index():
        return Response(dashboard, mimetype="text/html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "version": __version__})

    @app.get("/api/doctor")
    def doctor():
        return jsonify(doctor_data(app.config["TB_CONFIG"]))

    @app.get("/api/tools")
    def tools():
        from ..tools import TOOLS

        return jsonify({k: v[1] for k, v in TOOLS.items()})

    # ---------------- config ----------------
    @app.get("/api/config")
    def get_config():
        p = Path(app.config["TB_CONFIG"])
        if not p.exists():
            return jsonify({"ok": False, "error": f"{p} not found. Run init-config first."}), 404
        return jsonify({"ok": True, "path": str(p), "content": p.read_text(encoding="utf-8")})

    @app.post("/api/config")
    def save_config():
        body = request.get_json(force=True, silent=True) or {}
        content = body.get("content", "")
        try:
            data = json.loads(content)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Invalid JSON: {exc}"}), 400
        try:
            from ..config import AppConfig

            AppConfig.model_validate({k: v for k, v in data.items() if not k.startswith("_")})
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Config invalid: {exc}"}), 400
        p = Path(app.config["TB_CONFIG"])
        p.write_text(content, encoding="utf-8")
        log.info("Config saved via WebUI -> %s", p)
        return jsonify({"ok": True, "path": str(p)})

    # ---------------- jobs ----------------
    def _start_job(kind: str, payload: dict) -> dict:
        job_id = f"job-{next(JOB_COUNTER)}"
        job = {"id": job_id, "kind": kind, "status": "queued",
               "message": "", "started": time.strftime("%H:%M:%S"),
               "finished": "", "data": {}}
        with JOBS_LOCK:
            JOBS[job_id] = job
        t = threading.Thread(target=_run_job, args=(app, job_id, kind, payload), daemon=True)
        t.start()
        return job

    @app.post("/api/run")
    def run_booking():
        body = request.get_json(force=True, silent=True) or {}
        kind = str(body.get("kind", "book"))
        if kind not in ("login", "search", "book", "tatkal"):
            return jsonify({"ok": False, "error": f"unknown kind {kind}"}), 400
        job = _start_job(kind, {"headless": bool(body.get("headless", False)), "brutality": int(body.get("brutality") or 0)})
        return jsonify({"ok": True, "job": job})

    @app.post("/api/tool")
    def run_tool():
        body = request.get_json(force=True, silent=True) or {}
        from ..tools import TOOLS

        name = str(body.get("name", ""))
        if name not in TOOLS:
            return jsonify({"ok": False, "error": f"unknown tool {name}"}), 400
        job = _start_job(f"tool:{name}", {"args": body.get("args", {}), "brutality": int(body.get("brutality") or 0), "heads": int(body.get("heads") or 0),
                                          "headless": bool(body.get("headless", False))})
        return jsonify({"ok": True, "job": job})

    @app.get("/api/jobs")
    def jobs():
        with JOBS_LOCK:
            items = sorted(JOBS.values(), key=lambda j: j["id"], reverse=True)[:30]
        return jsonify({"ok": True, "jobs": items})

    @app.get("/api/jobs/<job_id>")
    def job_one(job_id: str):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "no such job"}), 404
        return jsonify({"ok": True, "job": job})

    # ---------------- logs (SSE live stream) ----------------
    @app.get("/api/logs")
    def logs_since():
        since = int(request.args.get("since", 0))
        with LOGS.buf_lock:
            items = [e for e in LOGS.entries if e["id"] > since]
        nxt = items[-1]["id"] if items else since
        return jsonify({"ok": True, "logs": items[-200:], "next": nxt})

    @app.get("/api/stream")
    def stream():
        def gen():
            q: queue.Queue = queue.Queue(maxsize=500)
            with LOGS.buf_lock:
                LOGS.subscribers.add(q)
                initial = list(LOGS.entries)[-30:]
            for e in initial:  # replay outside the lock (never yield while locked)
                yield f"data: {json.dumps(e)}\n\n"
            try:
                while True:
                    try:
                        item = q.get(timeout=15)
                        yield f"data: {json.dumps(item)}\n\n"
                    except queue.Empty:
                        yield ": heartbeat\n\n"
            finally:
                with LOGS.buf_lock:
                    LOGS.subscribers.discard(q)

        return Response(gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------- captcha tester ----------------
    @app.post("/api/solve-captcha")
    def solve_captcha():
        f = request.files.get("image")
        if not f:
            return jsonify({"ok": False, "error": "no image uploaded"}), 400
        from ..captcha.manager import AutoCaptcha
        from ..config import CaptchaCfg, load_config

        try:
            p = Path(app.config["TB_CONFIG"])
            captcha_cfg = load_config(p).captcha if p.exists() else CaptchaCfg()
        except Exception:
            captcha_cfg = CaptchaCfg()
        res = AutoCaptcha(captcha_cfg).solve_text_image(f.read())
        return jsonify({"ok": bool(res.ok), "text": res.text,
                        "confidence": round(res.confidence, 1), "solver": res.solver})

    # ---------------- reports ----------------
    @app.get("/api/reports")
    def reports():
        rep = Path("./reports")
        files = []
        if rep.exists():
            files = sorted([f.name for f in rep.iterdir() if f.is_file()],
                           reverse=True)[:40]
        return jsonify({"ok": True, "reports": files})

    return app


def _run_job(app, job_id: str, kind: str, payload: dict) -> None:
    def update(**kw):
        with JOBS_LOCK:
            JOBS[job_id].update(kw)

    update(status="running")
    log.info("▶️ Job %s started (%s)", job_id, kind)
    try:
        from ..config import load_config

        cfg = load_config(app.config["TB_CONFIG"])
        brut = payload.get("brutality") or 0
        if brut:
            from ..god.signals import title_for_level
            cfg.brute.level = int(brut)
            log.info("GOD dial set: %s", title_for_level(cfg.brute.level))
        heads = payload.get("heads") or 0
        if heads:
            cfg.brute.hydra_heads = max(0, min(3, int(heads)))
        headless = payload.get("headless") or None
        if kind in ("login", "search", "book", "tatkal"):
            from ..irctc.booker import IRCTCBooker

            if kind == "tatkal":
                cfg.tatkal.enabled = True
                if cfg.journey.quota == "GN":
                    cfg.journey.quota = "TQ"
            booker = IRCTCBooker(cfg, headless=headless)
            if kind == "login":
                ok = booker.login_only()
                update(status="done" if ok else "failed",
                       message="Login OK — session saved." if ok else "Login failed.")
            elif kind == "search":
                booker.search_only()
                update(status="done", message="Search done — see screenshots/.")
            else:
                res = booker.book()
                update(status="done" if res.success else "failed",
                       message=res.message, data={"pnr": res.pnr or ""})
        elif kind.startswith("tool:"):
            from ..tools import TOOLS

            name = kind.split(":", 1)[1]
            fn, _desc = TOOLS[name]
            args = dict(payload.get("args", {}) or {})
            if headless is not None:
                args["headless"] = headless
            res = fn(cfg, **args)
            update(status="done" if res.ok else "failed",
                   message=res.message, data=res.data)
        else:
            update(status="failed", message=f"unknown job kind {kind}")
    except Exception as exc:
        log.exception("Job %s crashed: %s", job_id, exc)
        update(status="failed", message=f"Crashed: {exc}")
    finally:
        with JOBS_LOCK:
            JOBS[job_id]["finished"] = time.strftime("%H:%M:%S")
        log.info("🏁 Job %s %s: %s", job_id, JOBS[job_id]["status"], JOBS[job_id]["message"])
