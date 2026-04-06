"""Thread-safe global settings for TradeChart."""

from __future__ import annotations

import threading
from typing import Literal

TerminalMode = Literal["full", "on_done", "none"]
ThemeName = Literal["dark", "light", "classic"]

_VALID_MODES: frozenset[str] = frozenset({"full", "on_done", "none"})
_VALID_THEMES: frozenset[str] = frozenset({"dark", "light", "classic"})


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
                    inst._watermark_enabled: bool = True
                    inst._overwrite: bool = False
                    inst._dpi: int = 150
                    inst._fig_width: int = 14
                    inst._fig_height: int = 7
                    inst._cache_ttl: int = 300
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


def get_settings() -> Settings:
    """Return the global *Settings* singleton."""
    return Settings()
