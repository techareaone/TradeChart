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
    muted_color: str
    accent_color: str


DARK = Theme(
    name="dark",
    bg_color="#0e1117",
    face_color="#0e1117",
    grid_color="#243044",
    text_color="#e8edf5",
    up_color="#3dd68c",
    down_color="#f07178",
    line_color="#7aa2f7",
    volume_alpha=0.55,
    spine_visible=False,
    muted_color="#8b97a8",
    accent_color="#7aa2f7",
)

LIGHT = Theme(
    name="light",
    bg_color="#f4f6f8",
    face_color="#f4f6f8",
    grid_color="#e1e6ee",
    text_color="#1a1f29",
    up_color="#1a9f6b",
    down_color="#e24b4b",
    line_color="#3d6bf5",
    volume_alpha=0.5,
    spine_visible=False,
    muted_color="#5c6b7e",
    accent_color="#3d6bf5",
)

CLASSIC = Theme(
    name="classic",
    bg_color="#f3efe2",
    face_color="#f7f4ea",
    grid_color="#e0d8c4",
    text_color="#2a261e",
    up_color="#1f7a3a",
    down_color="#a32020",
    line_color="#1d4e89",
    volume_alpha=0.45,
    spine_visible=True,
    muted_color="#6d6456",
    accent_color="#1d4e89",
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
