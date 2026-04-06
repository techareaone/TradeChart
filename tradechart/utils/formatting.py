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
