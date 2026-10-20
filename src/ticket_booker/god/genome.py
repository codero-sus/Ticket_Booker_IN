"""GENOME — strategy DNA that mutates itself between runs.

SelectorMemory remembers *which strategy worked for which action*. The Genome
is the next evolution: a persistent bandit over ALL locating strategies
(text/xpath/css/label/placeholder/aria/role/js/keyboard) with UCB1 arm
selection, reward decay and a leaderboard. Winners get promoted. Losers are
not deleted — they are kept with a decaying prior, because IRCTC's DOM
mutates too.

Persisted at `./profiles/genome.json` (atomic writes, corrupt = fresh start,
I/O failure = silence). Pure Python + unit-tested.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import tempfile
from pathlib import Path

log = logging.getLogger("ticket_booker.god.genome")

DEFAULT_ARMS = (
    "text",
    "xpath",
    "css",
    "label",
    "placeholder",
    "aria",
    "role",
    "js",
    "keyboard",
)


class Genome:
    """UCB1 multi-armed bandit over locator strategies, persisted as JSON."""

    def __init__(self, path: str | Path = "./profiles/genome.json",
                 arms: tuple[str, ...] | list[str] | None = None) -> None:
        self.path = Path(path)
        self.arms: tuple[str, ...] = tuple(arms or DEFAULT_ARMS)
        self.stats: dict[str, dict[str, float]] = {
            arm: {"plays": 0, "wins": 0.0, "reward": 0.0} for arm in self.arms
        }
        self._load()

    # ---------------- persistence ----------------

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            raw = data.get("stats") if isinstance(data, dict) else None
            if not isinstance(raw, dict):
                return
            for arm, bucket in raw.items():
                if not isinstance(bucket, dict):
                    continue
                plays = max(0, int(bucket.get("plays", 0) or 0))
                wins = max(0.0, float(bucket.get("wins", 0.0) or 0.0))
                reward = max(0.0, float(bucket.get("reward", 0.0) or 0.0))
                self.stats[str(arm)] = {"plays": plays, "wins": wins, "reward": reward}
            log.debug("Genome loaded %d arms from %s", len(self.stats), self.path)
        except Exception as exc:
            log.debug("Genome starting fresh (%s): %s", self.path, exc)
            self.stats = {arm: {"plays": 0, "wins": 0.0, "reward": 0.0}
                          for arm in self.arms}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": 1, "arms": list(self.arms), "stats": self.stats}
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception as exc:
            log.debug("Genome save failed: %s", exc)

    # ---------------- bandit ----------------

    def _entry(self, arm: str) -> dict[str, float]:
        return self.stats.setdefault(arm, {"plays": 0, "wins": 0.0, "reward": 0.0})

    def choose(self, arms: list[str] | tuple[str, ...] | None = None,
               rng: random.Random | None = None) -> str:
        """Pick the next strategy: explore untried arms, then UCB1."""
        rng = rng or random
        candidates = [a for a in (arms or self.arms)]
        if not candidates:
            return "text"
        untried = [a for a in candidates if self._entry(a)["plays"] <= 0]
        if untried:
            return rng.choice(untried)
        total = max(1.0, sum(self._entry(a)["plays"] for a in candidates))
        best_arm, best_score = candidates[0], -math.inf
        for arm in candidates:
            entry = self._entry(arm)
            plays = max(1.0, entry["plays"])
            mean = entry["reward"] / plays
            bonus = math.sqrt(2.0 * math.log(max(2.0, total)) / plays)
            score = mean + bonus
            if score > best_score:
                best_arm, best_score = arm, score
        return best_arm

    def record(self, arm: str, reward: float = 1.0) -> None:
        """Feed the outcome of one strategy attempt back into the DNA."""
        try:
            entry = self._entry(str(arm))
            entry["plays"] = int(entry["plays"]) + 1
            r = max(0.0, min(1.0, float(reward)))
            entry["reward"] = float(entry["reward"]) + r
            if r >= 0.5:
                entry["wins"] = float(entry.get("wins", 0.0)) + 1.0
            self._save()
        except Exception as exc:
            log.debug("Genome record failed: %s", exc)

    def decay(self, factor: float = 0.97) -> None:
        """Forget old wins slowly (recency weighting), keep the exploration prior."""
        factor = max(0.0, min(1.0, float(factor)))
        for entry in self.stats.values():
            entry["reward"] = float(entry.get("reward", 0.0)) * factor
            entry["wins"] = float(entry.get("wins", 0.0)) * factor
        self._save()

    def reset(self) -> None:
        self.stats = {arm: {"plays": 0, "wins": 0.0, "reward": 0.0}
                      for arm in self.arms}
        self._save()

    # ---------------- reporting ----------------

    def mean(self, arm: str) -> float:
        entry = self._entry(arm)
        plays = float(entry["plays"])
        return float(entry["reward"]) / plays if plays else 0.0

    def rank(self) -> list[dict]:
        rows = [
            {
                "arm": arm,
                "plays": int(entry["plays"]),
                "wins": int(round(float(entry.get("wins", 0.0)))),
                "mean": round(self.mean(arm), 4),
            }
            for arm, entry in self.stats.items()
        ]
        rows.sort(key=lambda r: (-r["mean"], -r["wins"], r["arm"]))
        return rows

    def best(self) -> str | None:
        played = [r for r in self.rank() if r["plays"] > 0]
        return played[0]["arm"] if played else None

    def summary(self) -> dict:
        total = sum(int(e["plays"]) for e in self.stats.values())
        return {
            "best": self.best(),
            "plays": total,
            "arms": len(self.stats),
            "leaderboard": [r for r in self.rank() if r["plays"] > 0][:5],
        }


__all__ = ["Genome", "DEFAULT_ARMS"]
