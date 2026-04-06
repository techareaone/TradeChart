"""Logging facade that respects the global terminal mode."""

from __future__ import annotations

import logging
import sys

from tradechart.config.settings import get_settings

_LOGGER_NAME = "TradeChart"
_CONFIGURED = False


def _ensure_handler() -> logging.Logger:
    """Lazily attach a stderr handler with clean formatting."""
    global _CONFIGURED
    logger = logging.getLogger(_LOGGER_NAME)
    if not _CONFIGURED:
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s │ %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        _CONFIGURED = True
    return logger


class _TradeChartLogger:
    """Thin wrapper that gates output on the active terminal mode."""

    def __init__(self) -> None:
        self._logger = _ensure_handler()
        self._summary_lines: list[str] = []

    def _mode(self) -> str:
        return get_settings().terminal_mode

    def detail(self, msg: str, *args: object) -> None:
        if self._mode() == "full":
            self._logger.info(msg, *args)

    def section(self, title: str) -> None:
        if self._mode() == "full":
            self._logger.info("── %s ──", title)

    def summary(self, msg: str) -> None:
        self._summary_lines.append(msg)
        if self._mode() == "full":
            self._logger.info(msg)

    def flush_summary(self) -> None:
        mode = self._mode()
        if mode == "on_done" and self._summary_lines:
            self._logger.info("── Summary ──")
            for line in self._summary_lines:
                self._logger.info(line)
        self._summary_lines.clear()

    def warning(self, msg: str, *args: object) -> None:
        if self._mode() != "none":
            self._logger.warning(msg, *args)

    def error(self, msg: str, *args: object) -> None:
        if self._mode() != "none":
            self._logger.error(msg, *args)


_INSTANCE: _TradeChartLogger | None = None


def get_logger() -> _TradeChartLogger:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = _TradeChartLogger()
    return _INSTANCE
