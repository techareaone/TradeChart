"""Canonical data models used across TradeChart."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Maps user-facing duration → (yfinance period, yfinance interval)
DURATION_RESOLUTION_MAP: dict[str, tuple[str, str]] = {
    "1d":   ("1d",  "5m"),
    "5d":   ("5d",  "15m"),
    "1mo":  ("1mo", "1d"),
    "3mo":  ("3mo", "1d"),
    "6mo":  ("6mo", "1d"),
    "1y":   ("1y",  "1wk"),
    "2y":   ("2y",  "1wk"),
    "5y":   ("5y",  "1wk"),
    "10y":  ("10y", "1mo"),
    "max":  ("max", "1mo"),
}


@dataclass(frozen=False)
class MarketData:
    """Normalised OHLCV market data returned by any provider."""

    ticker: str
    duration: str
    provider: str
    df: pd.DataFrame
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_empty(self) -> bool:
        return self.df.empty

    def clean(self) -> MarketData:
        """Sort, drop NaN rows, ensure correct columns in-place."""
        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(self.df.columns)
        if missing:
            raise ValueError(f"MarketData missing columns: {missing}")
        self.df = self.df.sort_index()
        self.df = self.df.dropna(subset=["Open", "High", "Low", "Close"])
        self.df["Volume"] = self.df["Volume"].fillna(0)
        return self

    def downsample(self, max_rows: int = 2000) -> MarketData:
        """Reduce row count if dataset is very large."""
        if len(self.df) <= max_rows:
            return self
        step = len(self.df) // max_rows
        self.df = self.df.iloc[::step]
        return self

    def to_heikin_ashi(self) -> MarketData:
        """Convert OHLC data to Heikin-Ashi candles in-place."""
        opens  = self.df["Open"].values.astype(float)
        highs  = self.df["High"].values.astype(float)
        lows   = self.df["Low"].values.astype(float)
        closes = self.df["Close"].values.astype(float)

        ha_close = (opens + highs + lows + closes) / 4

        # HA open is recursive — cannot be fully vectorised; raw numpy loop
        # is ~50x faster than pandas .iloc per-row assignment.
        ha_open = np.empty(len(opens), dtype=float)
        ha_open[0] = opens[0]
        for i in range(1, len(opens)):
            ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2

        ha_high = np.maximum(np.maximum(highs, ha_open), ha_close)
        ha_low  = np.minimum(np.minimum(lows,  ha_open), ha_close)

        df = self.df.copy()
        df["Open"]  = ha_open
        df["High"]  = ha_high
        df["Low"]   = ha_low
        df["Close"] = ha_close
        self.df = df
        return self
