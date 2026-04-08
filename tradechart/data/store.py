"""Persistent disk store for fetched market data."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from tradechart.data.models import MarketData

# Maximum age (seconds) for a stored file before it is considered stale and
# re-fetched from a live provider.  Keyed by the user-facing duration string;
# the value matches the bar resolution so a daily-bar file never goes more
# than one trading day without refreshing.
_MAX_AGE: dict[str, int] = {
    "1d":  4  * 3_600,        # intraday (5-min bars)  → 4 hours
    "5d":  4  * 3_600,        # intraday (15-min bars) → 4 hours
    "1mo": 24 * 3_600,        # daily bars             → 1 day
    "3mo": 24 * 3_600,        # daily bars             → 1 day
    "6mo": 24 * 3_600,        # daily bars             → 1 day
    "1y":  7  * 24 * 3_600,   # weekly bars            → 1 week
    "2y":  7  * 24 * 3_600,
    "5y":  7  * 24 * 3_600,
    "10y": 30 * 24 * 3_600,   # monthly bars           → 30 days
    "max": 30 * 24 * 3_600,
}


class DiskStore:
    """Saves and loads MarketData as CSV files under a dedicated folder.

    Layout::

        <base_path>/
        └── tradechart_FetchData/
            ├── AAPL_1mo.csv
            ├── MSFT_3mo.csv
            └── ...

    A CSV per (ticker, duration) pair is written on every fresh provider
    fetch and read back on subsequent requests, avoiding redundant network
    calls across sessions.
    """

    FOLDER_NAME = "tradechart_FetchData"

    def __init__(self, base_path: Path) -> None:
        self._root = base_path / self.FOLDER_NAME
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_path(self, ticker: str, duration: str) -> Path:
        # Sanitise characters that are invalid in filenames
        safe = ticker.replace("/", "_").replace("^", "").replace("=", "")
        return self._root / f"{safe}_{duration}.csv"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def has(self, ticker: str, duration: str) -> bool:
        """Return True if data for this (ticker, duration) pair is on disk."""
        return self._file_path(ticker, duration).exists()

    def is_stale(self, ticker: str, duration: str) -> bool:
        """Return True if the stored file is older than the bar-resolution threshold.

        A fresh file is served as-is.  A stale file still holds valid
        historical rows — the caller should merge fresh provider data on top
        rather than discarding it.
        """
        path = self._file_path(ticker, duration)
        if not path.exists():
            return True
        max_age = _MAX_AGE.get(duration, 24 * 3_600)
        return time.time() - path.stat().st_mtime > max_age

    def load(self, ticker: str, duration: str) -> MarketData | None:
        """Load a previously stored dataset regardless of age.

        Returns *None* only if the file is missing or unreadable.  Staleness
        is a separate concern handled by :meth:`is_stale`.
        """
        path = self._file_path(ticker, duration)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index, utc=True)
            for col in ("Open", "High", "Low", "Close", "Volume"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if df.empty:
                return None
            return MarketData(ticker=ticker, duration=duration, provider="disk", df=df)
        except Exception:
            return None

    def save(self, data: MarketData) -> None:
        """Persist *data* to disk (silently overwrites any existing file)."""
        try:
            path = self._file_path(data.ticker, data.duration)
            data.df.to_csv(path)
        except Exception:
            pass  # Never let a storage failure break the main workflow

    def clear(self) -> None:
        """Delete all stored CSV files (the folder itself is kept)."""
        for csv in self._root.glob("*.csv"):
            try:
                csv.unlink()
            except Exception:
                pass

    def list_stored(self) -> list[tuple[str, str]]:
        """Return a sorted list of (ticker, duration) pairs present on disk."""
        results: list[tuple[str, str]] = []
        for csv in sorted(self._root.glob("*.csv")):
            stem = csv.stem                   # e.g. "AAPL_1mo"
            parts = stem.rsplit("_", 1)
            if len(parts) == 2:
                results.append((parts[0], parts[1]))
        return results
