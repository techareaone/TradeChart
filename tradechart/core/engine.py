"""Central orchestration — wires providers, fetcher, and renderer together."""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from tradechart.config.logger import get_logger
from tradechart.config.settings import get_settings
from tradechart.data.fetcher import DataFetcher
from tradechart.data.models import MarketData
from tradechart.data.provider_base import BaseProvider
from tradechart.charts.renderer import ChartRenderer
from tradechart.charts.themes import get_theme
from tradechart.charts.watermark import stamp_logo
from tradechart.providers.yfinance_provider import YFinanceProvider
from tradechart.providers.tradingview_provider import TradingViewProvider
from tradechart.providers.stooq_provider import StooqProvider
from tradechart.utils.exceptions import OutputError
from tradechart.utils.formatting import build_default_filename, sanitize_filename
from tradechart.utils.validation import (
    validate_ticker, validate_duration, validate_chart_type,
    validate_output_path, validate_indicators, validate_format,
)


def _default_providers() -> list[BaseProvider]:
    return [YFinanceProvider(), TradingViewProvider(), StooqProvider()]


class Engine:
    """Single entry-point used by the public API functions."""

    def __init__(self) -> None:
        self._fetcher = DataFetcher(_default_providers())
        self._renderer = ChartRenderer()
        self._log = get_logger()

    # ── tc.chart() ───────────────────────────────────────────────────────

    def run(
        self,
        ticker: str,
        duration: str = "1mo",
        chart_type: str = "candle",
        output_location: str | None = None,
        output_name: str | None = None,
        fmt: str = "png",
        indicators: list[str] | None = None,
        show_volume: bool = True,
    ) -> Path:
        self._log.section("TradeChart — starting")

        ticker = validate_ticker(ticker)
        duration = validate_duration(duration)
        chart_type = validate_chart_type(chart_type)
        fmt = validate_format(fmt)
        ind_list = validate_indicators(indicators)

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()
        filename = output_name or build_default_filename(ticker, duration, chart_type, fmt)
        out_path = self._safe_path(out_dir, filename)

        self._log.detail("Ticker: %s | Duration: %s | Type: %s | Format: %s",
                         ticker, duration, chart_type, fmt)
        self._log.detail("Indicators: %s", ", ".join(ind_list) if ind_list else "none")
        self._log.detail("Output: %s", out_path)

        self._log.section("Fetching market data")
        data = self._fetcher.fetch(ticker, duration)

        self._log.section("Rendering chart")
        try:
            result_path = self._renderer.render(
                data=data, chart_type=chart_type, output_path=out_path,
                fmt=fmt, indicators=ind_list, show_volume=show_volume,
            )
        except Exception as exc:
            raise OutputError(f"Failed to save chart: {exc}") from exc

        self._log.summary(f"✓ Chart saved → {result_path}")
        self._log.flush_summary()
        return result_path

    # ── tc.compare() ─────────────────────────────────────────────────────

    def compare(
        self,
        tickers: list[str],
        duration: str = "1mo",
        output_location: str | None = None,
        output_name: str | None = None,
        fmt: str = "png",
        normalise: bool = True,
    ) -> Path:
        self._log.section("TradeChart — compare")

        tickers = [validate_ticker(t) for t in tickers]
        duration = validate_duration(duration)
        fmt = validate_format(fmt)

        if len(tickers) < 2:
            raise ValueError("compare() requires at least 2 tickers.")
        if len(tickers) > 8:
            raise ValueError("compare() supports at most 8 tickers.")

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()
        filename = output_name or f"compare_{'_'.join(tickers)}_{duration}.{fmt}"
        out_path = self._safe_path(out_dir, sanitize_filename(filename))

        settings = get_settings()
        theme = get_theme(settings.theme)

        colours = ["#42a5f5", "#ef5350", "#26a69a", "#ffab40",
                    "#ab47bc", "#ff7043", "#66bb6a", "#ec407a"]

        fig, ax = plt.subplots(figsize=settings.fig_size)
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.face_color)

        for i, ticker in enumerate(tickers):
            self._log.section(f"Fetching {ticker}")
            data = self._fetcher.fetch(ticker, duration)
            series = data.df["Close"]
            if normalise:
                series = (series / series.iloc[0] - 1) * 100  # percent change
            ax.plot(series.index, series, color=colours[i % len(colours)],
                    linewidth=1.4, label=ticker)

        ylabel = "Change (%)" if normalise else "Price"
        ax.set_title(f"Comparison  •  {duration}",
                     color=theme.text_color, fontsize=14, fontweight="bold", pad=12)
        ax.set_ylabel(ylabel, color=theme.text_color, fontsize=11)
        ax.tick_params(colors=theme.text_color, labelsize=9)
        ax.grid(True, color=theme.grid_color, linestyle="--", linewidth=0.5, alpha=0.7)
        ax.legend(loc="upper left", fontsize=9,
                  facecolor=theme.face_color, edgecolor=theme.grid_color,
                  labelcolor=theme.text_color)
        if not theme.spine_visible:
            for spine in ax.spines.values():
                spine.set_visible(False)

        fig.autofmt_xdate(rotation=30)
        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig)

        out_file = out_path.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)

        self._log.summary(f"✓ Comparison chart saved → {out_file}")
        self._log.flush_summary()
        return out_file

    # ── tc.data() ────────────────────────────────────────────────────────

    def fetch_data(self, ticker: str, duration: str = "1mo") -> pd.DataFrame:
        ticker = validate_ticker(ticker)
        duration = validate_duration(duration)
        data = self._fetcher.fetch(ticker, duration)
        return data.df.copy()

    # ── tc.export() ──────────────────────────────────────────────────────

    def export(
        self,
        ticker: str,
        duration: str = "1mo",
        fmt: str = "csv",
        output_location: str | None = None,
        output_name: str | None = None,
    ) -> Path:
        self._log.section("TradeChart — export data")

        ticker = validate_ticker(ticker)
        duration = validate_duration(duration)
        if fmt not in ("csv", "json", "xlsx"):
            raise ValueError(f"Export format must be csv, json, or xlsx — got '{fmt}'")

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()
        filename = output_name or f"{sanitize_filename(ticker)}_{duration}.{fmt}"
        out_path = self._safe_path(out_dir, filename)

        data = self._fetcher.fetch(ticker, duration)
        df = data.df.copy()

        if fmt == "csv":
            df.to_csv(out_path)
        elif fmt == "json":
            df.to_json(out_path, orient="index", date_format="iso", indent=2)
        elif fmt == "xlsx":
            df.to_excel(out_path, engine="openpyxl")

        self._log.summary(f"✓ Data exported → {out_path}")
        self._log.flush_summary()
        return out_path

    # ── tc.clear_cache() ─────────────────────────────────────────────────

    def clear_cache(self) -> None:
        self._fetcher.clear_cache()
        self._log.summary("✓ Cache cleared")
        self._log.flush_summary()

    # ── Helpers ──────────────────────────────────────────────────────────

    def _safe_path(self, out_dir: Path, filename: str) -> Path:
        """Return a non-colliding output path unless overwrite is enabled."""
        out_path = out_dir / filename
        if get_settings().overwrite or not out_path.exists():
            return out_path

        stem = out_path.stem
        suffix = out_path.suffix
        counter = 1
        while out_path.exists():
            out_path = out_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        self._log.detail("File existed; saving as %s instead", out_path.name)
        return out_path
