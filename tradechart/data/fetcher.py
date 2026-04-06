"""Orchestrates data fetching across multiple providers with fallback."""

from __future__ import annotations

import time
from typing import Sequence

from tradechart.config.logger import get_logger
from tradechart.config.settings import get_settings
from tradechart.data.models import MarketData
from tradechart.data.provider_base import BaseProvider
from tradechart.utils.exceptions import DataFetchError


class _Cache:
    """Simple TTL-based in-memory cache."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, MarketData]] = {}

    @staticmethod
    def _key(ticker: str, duration: str) -> str:
        return f"{ticker}|{duration}"

    def get(self, ticker: str, duration: str) -> MarketData | None:
        key = self._key(ticker, duration)
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > get_settings().cache_ttl:
            del self._store[key]
            return None
        return data

    def put(self, data: MarketData) -> None:
        key = self._key(data.ticker, data.duration)
        self._store[key] = (time.monotonic(), data)

    def clear(self) -> None:
        self._store.clear()


class DataFetcher:
    """Try each provider in priority order; cache successful results."""

    def __init__(self, providers: Sequence[BaseProvider]) -> None:
        self._providers = list(providers)
        self._cache = _Cache()
        self._log = get_logger()

    def fetch(self, ticker: str, duration: str) -> MarketData:
        cached = self._cache.get(ticker, duration)
        if cached is not None:
            self._log.detail("Cache hit for %s/%s", ticker, duration)
            self._log.summary(f"✓ Data loaded from cache ({cached.provider})")
            return cached

        errors: list[str] = []
        for provider in self._providers:
            self._log.section(f"Trying provider: {provider.name}")
            try:
                data = provider.fetch(ticker, duration)
                if data.is_empty:
                    msg = f"{provider.name} returned empty data"
                    self._log.detail(msg)
                    errors.append(msg)
                    continue
                data.clean().downsample()
                self._cache.put(data)
                self._log.detail("Fetched %d rows from %s", len(data.df), provider.name)
                self._log.summary(f"✓ Data fetched via {provider.name} ({len(data.df)} rows)")
                return data
            except Exception as exc:
                msg = f"{provider.name} failed: {exc}"
                self._log.detail(msg)
                errors.append(msg)

        raise DataFetchError(
            f"All data providers failed for {ticker}/{duration}.\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    def clear_cache(self) -> None:
        """Flush the in-memory data cache."""
        self._cache.clear()
        self._log.detail("Data cache cleared")
