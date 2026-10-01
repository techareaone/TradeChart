"""Thread-safe global settings for TradeChart."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from tradechart.data.store import DiskStore

TerminalMode = Literal["full", "on_done", "none"]
ThemeName = Literal["dark", "light", "classic"]
ChartEngine = Literal["native", "mplfinance"]
FontName = Literal["sans", "serif", "mono"]

_VALID_MODES: frozenset[str] = frozenset({"full", "on_done", "none"})
_VALID_THEMES: frozenset[str] = frozenset({"dark", "light", "classic"})
_VALID_ENGINES: frozenset[str] = frozenset({"native", "mplfinance"})
_FONT_ALIASES: dict[str, FontName] = {
    "sans": "sans",
    "sans-serif": "sans",
    "sans serif": "sans",
    "serif": "serif",
    "mono": "mono",
    "monospace": "mono",
}
# Matplotlib ships these faces, so charts render with no extra font install.
_FONT_FACES: dict[FontName, tuple[str, str]] = {
    "sans": ("DejaVu Sans", "DejaVu Sans Mono"),
    "serif": ("DejaVu Serif", "DejaVu Sans Mono"),
    "mono": ("DejaVu Sans Mono", "DejaVu Sans Mono"),
}


class Settings:
    """Thread-safe singleton holding global configuration."""

    _instance: Settings | None = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> Settings:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._mode_lock = threading.Lock()
                    inst._terminal_mode: TerminalMode = "on_done"
                    inst._theme: ThemeName = "dark"
                    inst._chart_engine: ChartEngine = "native"
                    inst._font: FontName = "sans"
                    inst._watermark_enabled: bool = True
                    inst._overwrite: bool = False
                    inst._dpi: int = 100
                    inst._fig_width: int = 12
                    inst._fig_height: int = 6
                    inst._cache_ttl: int = 300
                    inst._disk_store: DiskStore | None = None
                    cls._instance = inst
        return cls._instance

    # -- terminal mode --------------------------------------------------------

    @property
    def terminal_mode(self) -> TerminalMode:
        with self._mode_lock:
            return self._terminal_mode

    @terminal_mode.setter
    def terminal_mode(self, value: str) -> None:
        if value not in _VALID_MODES:
            raise ValueError(
                f"Invalid terminal mode '{value}'. "
                f"Allowed: {', '.join(sorted(_VALID_MODES))}"
            )
        with self._mode_lock:
            self._terminal_mode = value  # type: ignore[assignment]

    # -- theme ----------------------------------------------------------------

    @property
    def theme(self) -> ThemeName:
        with self._mode_lock:
            return self._theme

    @theme.setter
    def theme(self, value: str) -> None:
        if value not in _VALID_THEMES:
            raise ValueError(
                f"Invalid theme '{value}'. "
                f"Allowed: {', '.join(sorted(_VALID_THEMES))}"
            )
        with self._mode_lock:
            self._theme = value  # type: ignore[assignment]

    # -- chart engine ---------------------------------------------------------

    @property
    def chart_engine(self) -> ChartEngine:
        with self._mode_lock:
            return self._chart_engine

    @chart_engine.setter
    def chart_engine(self, value: str) -> None:
        cleaned = value.strip().lower()
        if cleaned not in _VALID_ENGINES:
            raise ValueError(
                f"Invalid chart engine '{value}'. "
                f"Allowed: {', '.join(sorted(_VALID_ENGINES))}"
            )
        with self._mode_lock:
            self._chart_engine = cleaned  # type: ignore[assignment]

    # -- font -----------------------------------------------------------------

    @property
    def font(self) -> FontName:
        with self._mode_lock:
            return self._font

    @font.setter
    def font(self, value: str) -> None:
        cleaned = _FONT_ALIASES.get(value.strip().lower())
        if cleaned is None:
            raise ValueError(
                f"Invalid font '{value}'. "
                f"Allowed: {', '.join(sorted(set(_FONT_ALIASES)))}"
            )
        with self._mode_lock:
            self._font = cleaned

    def font_faces(self) -> tuple[str, str]:
        """Return ``(label face, figure face)`` for the selected font."""
        with self._mode_lock:
            return _FONT_FACES[self._font]

    # -- watermark ------------------------------------------------------------

    @property
    def watermark_enabled(self) -> bool:
        with self._mode_lock:
            return self._watermark_enabled

    @watermark_enabled.setter
    def watermark_enabled(self, value: bool) -> None:
        with self._mode_lock:
            self._watermark_enabled = bool(value)

    # -- overwrite ------------------------------------------------------------

    @property
    def overwrite(self) -> bool:
        with self._mode_lock:
            return self._overwrite

    @overwrite.setter
    def overwrite(self, value: bool) -> None:
        with self._mode_lock:
            self._overwrite = bool(value)

    # -- dpi ------------------------------------------------------------------

    @property
    def dpi(self) -> int:
        with self._mode_lock:
            return self._dpi

    @dpi.setter
    def dpi(self, value: int) -> None:
        if not (50 <= value <= 600):
            raise ValueError(f"DPI must be 50–600, got {value}")
        with self._mode_lock:
            self._dpi = int(value)

    # -- figure size ----------------------------------------------------------

    @property
    def fig_size(self) -> tuple[int, int]:
        with self._mode_lock:
            return (self._fig_width, self._fig_height)

    @fig_size.setter
    def fig_size(self, value: tuple[int, int]) -> None:
        w, h = value
        if w < 4 or h < 3:
            raise ValueError(f"Figure size must be at least 4×3, got {w}×{h}")
        with self._mode_lock:
            self._fig_width = int(w)
            self._fig_height = int(h)

    # -- cache TTL ------------------------------------------------------------

    @property
    def cache_ttl(self) -> int:
        with self._mode_lock:
            return self._cache_ttl

    @cache_ttl.setter
    def cache_ttl(self, value: int) -> None:
        with self._mode_lock:
            self._cache_ttl = max(0, int(value))

    # -- disk store -----------------------------------------------------------

    @property
    def disk_store(self) -> DiskStore | None:
        with self._mode_lock:
            return self._disk_store

    def set_store_path(self, path: Path) -> None:
        """Create (or update) the persistent disk store at *path*."""
        from tradechart.data.store import DiskStore  # lazy import avoids cycle
        store = DiskStore(path)
        with self._mode_lock:
            self._disk_store = store


def get_settings() -> Settings:
    """Return the global *Settings* singleton."""
    return Settings()
