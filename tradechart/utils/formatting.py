"""Formatting and filename helpers."""

from __future__ import annotations

import re


def sanitize_filename(name: str) -> str:
    """Replace characters unsafe for filenames with underscores."""
    return re.sub(r"[^A-Za-z0-9_\-.]", "_", name)


def build_default_filename(
    ticker: str,
    duration: str,
    chart_type: str,
    extension: str = "png",
) -> str:
    base = f"{ticker}_{duration}_{chart_type}"
    return f"{sanitize_filename(base)}.{extension}"


def build_group_label(tickers: list[str]) -> str:
    """Build a human-readable label for an averaged ticker group.

    Keeps the label concise when the group is large.

    Examples
    --------
    >>> build_group_label(["AAPL", "MSFT"])
    'AVG(AAPL,MSFT)'
    >>> build_group_label(["AAPL", "MSFT", "AMZN", "GOOG", "META", "NVDA"])
    'AVG(AAPL,MSFT,AMZN,GOOG,+2more)'
    """
    if len(tickers) <= 4:
        return f"AVG({','.join(tickers)})"
    head = ",".join(tickers[:4])
    extra = len(tickers) - 4
    return f"AVG({head},+{extra}more)"
