"""Persistent disk store for fetched market data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from tradechart.data.models import MarketData


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

    def load(self, ticker: str, duration: str) -> MarketData | None:
        """Load a previously stored dataset.  Returns *None* on any error."""
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
