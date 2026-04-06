"""Abstract base class for market-data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from tradechart.data.models import MarketData


class BaseProvider(ABC):
    """Every data provider must implement this interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @abstractmethod
    def fetch(self, ticker: str, duration: str) -> MarketData:
        """Fetch OHLCV data. Must raise on failure."""
