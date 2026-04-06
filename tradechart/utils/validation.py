"""Input validation helpers for TradeChart."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union

# ── Constants ────────────────────────────────────────────────────────────────

VALID_DURATIONS: frozenset[str] = frozenset(
    {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"}
)

VALID_CHART_TYPES: frozenset[str] = frozenset(
    {"candle", "line", "ohlc", "area", "heikin_ashi"}
)

VALID_INDICATORS: frozenset[str] = frozenset(
    {"sma", "ema", "bollinger", "vwap", "rsi", "macd", "volume"}
)

VALID_FORMATS: frozenset[str] = frozenset({"png", "jpg", "svg", "pdf", "webp"})

_TICKER_RE = re.compile(r"^[A-Za-z0-9\-/.^=]{1,20}$")


# ── Public helpers ───────────────────────────────────────────────────────────

def validate_ticker(ticker: str) -> str:
    """Return a normalised ticker string or raise *ValueError*."""
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("Ticker must be a non-empty string.")
    cleaned = ticker.strip().upper()
    if not _TICKER_RE.match(cleaned):
        raise ValueError(
            f"Invalid ticker format: '{ticker}'. "
            "Expected 1–20 alphanumeric characters, with optional '-', '/', '.', '^', '='."
        )
    return cleaned


# TickerInput covers a single symbol or a group of symbols to be averaged.
TickerInput = Union[str, list, tuple]


def validate_ticker_input(ticker: TickerInput) -> "str | list[str]":
    """Validate a single ticker string or a sequence of tickers to be averaged.

    Parameters
    ----------
    ticker : str | list | tuple
        A single symbol such as ``"AAPL"``, or a sequence such as
        ``["AAPL", "MSFT", "AMZN"]``.  When a sequence is supplied the
        library fetches each ticker and renders the averaged OHLCV series.

    Returns
    -------
    str
        Normalised symbol when a single ticker is given.
    list[str]
        List of normalised symbols when a group is given.

    Notes
    -----
    Python's type system resolves the apparent naming collision automatically.
    ``"DNUT"`` (a string literal) refers to the Krispy Kreme ticker; a variable
    called ``DNUT`` that holds a list is simply passed as a list — the library
    inspects the *type*, not the name.
    """
    if isinstance(ticker, str):
        return validate_ticker(ticker)
    if isinstance(ticker, (list, tuple)):
        items = list(ticker)
        if len(items) == 0:
            raise ValueError(
                "Ticker group must contain at least one symbol. "
                "Pass a non-empty list, e.g. ['AAPL', 'MSFT']."
            )
        validated = []
        errors = []
        for item in items:
            if not isinstance(item, str):
                errors.append(f"  • {item!r} — expected str, got {type(item).__name__}")
                continue
            try:
                validated.append(validate_ticker(item))
            except ValueError as exc:
                errors.append(f"  • {item!r} — {exc}")
        if errors:
            raise ValueError(
                "One or more tickers in the group are invalid:\n"
                + "\n".join(errors)
            )
        return validated
    raise TypeError(
        f"ticker must be a str, list, or tuple — got {type(ticker).__name__!r}. "
        "Pass a single symbol (e.g. 'AAPL') or a group "
        "(e.g. ['AAPL', 'MSFT', 'AMZN'])."
    )


def validate_duration(duration: str) -> str:
    if duration not in VALID_DURATIONS:
        raise ValueError(
            f"Unsupported duration '{duration}'. "
            f"Allowed: {', '.join(sorted(VALID_DURATIONS))}"
        )
    return duration


def validate_chart_type(chart_type: str) -> str:
    if chart_type not in VALID_CHART_TYPES:
        raise ValueError(
            f"Unsupported chart_type '{chart_type}'. "
            f"Allowed: {', '.join(sorted(VALID_CHART_TYPES))}"
        )
    return chart_type


def validate_indicators(indicators: list[str] | None) -> list[str]:
    """Validate and return a list of indicator names."""
    if indicators is None:
        return []
    invalid = set(indicators) - VALID_INDICATORS
    if invalid:
        raise ValueError(
            f"Unknown indicators: {invalid}. "
            f"Allowed: {', '.join(sorted(VALID_INDICATORS))}"
        )
    return list(indicators)


def validate_format(fmt: str) -> str:
    if fmt not in VALID_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. "
            f"Allowed: {', '.join(sorted(VALID_FORMATS))}"
        )
    return fmt


def validate_output_path(directory: str | Path) -> Path:
    """Ensure *directory* is writable; create it if needed."""
    path = Path(directory).resolve()
    if path.exists() and not path.is_dir():
        raise FileExistsError(
            f"Output location '{path}' exists but is not a directory."
        )
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(
                f"Cannot create output directory '{path}': {exc}"
            ) from exc
    if not os.access(path, os.W_OK):
        raise PermissionError(f"Output directory '{path}' is not writable.")
    return path
