"""Chart colour themes for TradeChart."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """Immutable colour palette for chart rendering."""

    name: str
    bg_color: str
    face_color: str
    grid_color: str
    text_color: str
    up_color: str
    down_color: str
    line_color: str
    volume_alpha: float
    spine_visible: bool


DARK = Theme(
    name="dark",
    bg_color="#1e1e2f",
    face_color="#1e1e2f",
    grid_color="#2e2e44",
    text_color="#c8c8d4",
    up_color="#26a69a",
    down_color="#ef5350",
    line_color="#42a5f5",
    volume_alpha=0.35,
    spine_visible=False,
)

LIGHT = Theme(
    name="light",
    bg_color="#ffffff",
    face_color="#fafafa",
    grid_color="#e0e0e0",
    text_color="#333333",
    up_color="#2e7d32",
    down_color="#c62828",
    line_color="#1565c0",
    volume_alpha=0.30,
    spine_visible=False,
)

CLASSIC = Theme(
    name="classic",
    bg_color="#f5f5dc",
    face_color="#fffef2",
    grid_color="#d4d4aa",
    text_color="#2c2c2c",
    up_color="#006400",
    down_color="#8b0000",
    line_color="#00008b",
    volume_alpha=0.25,
    spine_visible=True,
)

_THEMES: dict[str, Theme] = {
    "dark": DARK,
    "light": LIGHT,
    "classic": CLASSIC,
}


def get_theme(name: str) -> Theme:
    """Return the *Theme* for *name* or raise *ValueError*."""
    theme = _THEMES.get(name)
    if theme is None:
        raise ValueError(f"Unknown theme '{name}'. Allowed: {', '.join(_THEMES)}")
    return theme
