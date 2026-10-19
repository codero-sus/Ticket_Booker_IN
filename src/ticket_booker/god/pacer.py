"""Radioactive pacer — the bot feels the site's pulse and matches it.

Slow IRCTC evening? The pacer stretches delays so actions don't trip over
half-loaded pages. Fast 3 AM IRCTC? It tightens delays for maximum Tatkal
velocity. Pure logic + unit-tested; only `sleep()` touches time.
"""

from __future__ import annotations

import random
import time
from collections import deque


class Pacer:
    def __init__(self, lo: float = 0.3, hi: float = 1.2,
                 min_lo: float = 0.1, max_hi: float = 8.0) -> None:
        self.lo = lo
        self.hi = hi
        self.min_lo = min_lo
        self.max_hi = max_hi
        self.samples: deque[float] = deque(maxlen=20)

    def record(self, seconds: float) -> None:
        """Feed one action latency; adapt the delay window."""
        try:
            s = min(30.0, max(0.01, float(seconds)))
        except (TypeError, ValueError):
            return
        self.samples.append(s)
        if len(self.samples) < 5:
            return
        avg = sum(self.samples) / len(self.samples)
        target = min(self.max_hi, max(0.4, avg * 1.6))
        self.hi += (target - self.hi) * 0.35  # glide, don't jump
        self.lo = min(max(self.min_lo, self.hi * 0.3), 2.0)

    def delay(self) -> tuple[float, float]:
        return (self.lo, self.hi)

    def sleep(self) -> None:
        time.sleep(random.uniform(self.lo, self.hi))
