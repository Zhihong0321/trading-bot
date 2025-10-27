"""Indicator calculations used by the strategy."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Iterable, Optional

import numpy as np


@dataclass
class EMA:
    """Incremental exponential moving average."""

    period: int
    value: Optional[float] = None

    def update(self, price: float) -> float:
        alpha = 2 / (self.period + 1)
        if self.value is None:
            self.value = price
        else:
            self.value = alpha * price + (1 - alpha) * self.value
        return self.value


@dataclass
class RSI:
    """Relative Strength Index computed incrementally."""

    period: int = 14
    avg_gain: Optional[float] = None
    avg_loss: Optional[float] = None
    prev_close: Optional[float] = None

    def update(self, close: float) -> Optional[float]:
        if self.prev_close is None:
            self.prev_close = close
            return None

        change = close - self.prev_close
        gain = max(change, 0)
        loss = abs(min(change, 0))

        if self.avg_gain is None or self.avg_loss is None:
            self.avg_gain = gain
            self.avg_loss = loss
        else:
            alpha = 1 / self.period
            self.avg_gain = (1 - alpha) * self.avg_gain + alpha * gain
            self.avg_loss = (1 - alpha) * self.avg_loss + alpha * loss

        self.prev_close = close

        if self.avg_loss == 0:
            return 100.0

        rs = self.avg_gain / self.avg_loss
        return 100 - (100 / (1 + rs))


@dataclass
class RollingWindow:
    """Maintains a fixed length rolling window of numeric values."""

    length: int
    values: Deque[float]

    def __init__(self, length: int):
        self.length = length
        self.values = deque(maxlen=length)

    def append(self, value: float) -> None:
        self.values.append(value)

    def mean(self) -> Optional[float]:
        if not self.values:
            return None
        return float(np.mean(self.values))

    def sum(self) -> float:
        return float(np.sum(self.values))

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self.values)


def atr(highs: Iterable[float], lows: Iterable[float], closes: Iterable[float]) -> float:
    """Compute the average true range for the provided bars."""

    highs = np.array(list(highs))
    lows = np.array(list(lows))
    closes = np.array(list(closes))
    true_ranges = np.maximum(highs[1:], closes[:-1]) - np.minimum(lows[1:], closes[:-1])
    return float(np.mean(true_ranges))


__all__ = ["EMA", "RSI", "RollingWindow", "atr"]
