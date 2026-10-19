"""SelectorMemory — self-healing locators.

Every brute finder records WHICH strategy worked ("text engine", "xpath", ...).
Next run, winners go first — the tool literally learns IRCTC's layout and
adapts when it changes. Corrupt/missing file = start fresh (never crashes).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("ticket_booker.god.memory")


class SelectorMemory:
    def __init__(self, path: str | Path = "./profiles/selector_memory.json") -> None:
        self.path = Path(path)
        self.counts: dict[str, dict[str, int]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                if isinstance(data, dict):
                    self.counts = {k: v for k, v in data.items() if isinstance(v, dict)}
                    log.debug("SelectorMemory loaded %d keys from %s", len(self.counts), self.path)
        except Exception as exc:
            log.debug("SelectorMemory starting fresh (%s): %s", self.path, exc)
            self.counts = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if len(self.counts) > 1000:  # prune oldest half, stay tiny
                keys = list(self.counts)[:500]
                for k in keys:
                    del self.counts[k]
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.counts, f)
            os.replace(tmp, self.path)
        except Exception as exc:
            log.debug("SelectorMemory save failed: %s", exc)

    def record(self, key: str, strategy: str) -> None:
        try:
            bucket = self.counts.setdefault(key, {})
            bucket[strategy] = bucket.get(strategy, 0) + 1
            self._save()
        except Exception:
            pass

    def preferred(self, key: str) -> str | None:
        bucket = self.counts.get(key) or {}
        if not bucket:
            return None
        return max(bucket.items(), key=lambda kv: kv[1])[0]

    def order(self, key: str, strategies: list[str]) -> list[str]:
        """Winners first (stable for the rest)."""
        pref = self.preferred(key)
        if pref not in strategies:
            return strategies
        return [pref] + [s for s in strategies if s != pref]
