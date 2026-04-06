"""Custom exception hierarchy for TradeChart."""

from __future__ import annotations


class TradeChartError(Exception):
    """Base exception for all TradeChart errors."""


class DataFetchError(TradeChartError):
    """Raised when no data provider can return data for the request."""


class InvalidTickerError(TradeChartError, ValueError):
    """Raised for malformed or unrecognised ticker symbols."""


class RenderError(TradeChartError):
    """Raised when chart rendering fails."""


class OutputError(TradeChartError, OSError):
    """Raised for file-system issues when saving output."""


class ConfigError(TradeChartError, ValueError):
    """Raised for invalid configuration values."""
