"""Run journal — black-box flight recorder (one JSONL file per run).

Every god action (goto/click/fill/captcha/retry) appends a timestamped line to
`./journals/<ts>_run.jsonl`. When something exotic happens at 10:00:03 AM,
the journal tells you EXACTLY what the bot saw and did. The journal can never
kill a run: all I/O failures degrade to silence.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("ticket_booker.god.journal")


class Journal:
    def __init__(self, base_dir: str | Path = "./journals", run_name: str = "run") -> None:
        self.base_dir = Path(base_dir)
        self.run_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", run_name)[:40] or "run"
        self._path: Path | None = None
        self._broken = False

    @property
    def path(self) -> Path | None:
        if self._path is None and not self._broken:
            try:
                self.base_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                self._path = self.base_dir / f"{ts}_{self.run_name}.jsonl"
            except Exception as exc:
                log.debug("journal disabled: %s", exc)
                self._broken = True
        return self._path

    def event(self, kind: str, what: str = "", ok: bool | None = None,
             ms: int | None = None, extra: Any = None) -> None:
        if self._broken:
            return
        try:
            rec: dict[str, Any] = {
                "t": datetime.now().isoformat(timespec="seconds"),
                "kind": str(kind)[:32],
                "what": str(what)[:200],
            }
            if ok is not None:
                rec["ok"] = bool(ok)
            if ms is not None:
                rec["ms"] = int(ms)
            if extra is not None:
                rec["extra"] = extra
            p = self.path
            if p is None:
                return
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            self._broken = True  # journal never kills runs

    def read(self) -> list[dict]:
        """Parse recorded events (tests/debug). Empty list if none."""
        if self._path is None or not self._path.exists():
            return []
        out = []
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            pass
        return out
