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
from tradechart.utils.exceptions import OutputError, DataFetchError
from tradechart.utils.formatting import (
    build_default_filename, build_group_label, sanitize_filename,
)
from tradechart.utils.validation import (
    validate_ticker, validate_ticker_input, validate_duration,
    validate_chart_type, validate_output_path, validate_indicators,
    validate_format,
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
        ticker,
        duration: str = "1mo",
        chart_type: str = "candle",
        output_location: str | None = None,
        output_name: str | None = None,
        fmt: str = "png",
        indicators: list[str] | None = None,
        show_volume: bool = True,
    ) -> Path:
        self._log.section("TradeChart — starting")

        ticker_validated = validate_ticker_input(ticker)
        duration = validate_duration(duration)
        chart_type = validate_chart_type(chart_type)
        fmt = validate_format(fmt)
        ind_list = validate_indicators(indicators)

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()

        if isinstance(ticker_validated, list):
            # ── Multi-ticker average path ──────────────────────────────────
            label = build_group_label(ticker_validated)
            filename = output_name or build_default_filename(label, duration, chart_type, fmt)
            out_path = self._safe_path(out_dir, filename)

            self._log.detail("Ticker group: %s | Duration: %s | Type: %s | Format: %s",
                             label, duration, chart_type, fmt)
            self._log.detail("Indicators: %s", ", ".join(ind_list) if ind_list else "none")
            self._log.detail("Output: %s", out_path)

            self._log.section("Fetching and averaging market data")
            data = self._build_averaged_data(ticker_validated, duration)
        else:
            # ── Single-ticker path (unchanged) ─────────────────────────────
            filename = output_name or build_default_filename(
                ticker_validated, duration, chart_type, fmt
            )
            out_path = self._safe_path(out_dir, filename)

            self._log.detail("Ticker: %s | Duration: %s | Type: %s | Format: %s",
                             ticker_validated, duration, chart_type, fmt)
            self._log.detail("Indicators: %s", ", ".join(ind_list) if ind_list else "none")
            self._log.detail("Output: %s", out_path)

            self._log.section("Fetching market data")
            data = self._fetcher.fetch(ticker_validated, duration)

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

        providers: list[str] = []
        for i, ticker in enumerate(tickers):
            self._log.section(f"Fetching {ticker}")
            data = self._fetcher.fetch(ticker, duration)
            providers.append(data.provider)
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

        provider_str = ", ".join(sorted(set(providers))) if providers else None
        if settings.watermark_enabled:
            stamp_logo(fig, provider=provider_str)

        out_file = out_path.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)

        self._log.summary(f"✓ Comparison chart saved → {out_file}")
        self._log.flush_summary()
        return out_file

    # ── tc.heatmap() ─────────────────────────────────────────────────────

    def heatmap(
        self,
        tickers: list[str],
        duration: str = "1mo",
        output_location: str | None = None,
        output_name: str | None = None,
        fmt: str = "png",
    ) -> Path:
        from tradechart.charts.heatmap import HeatmapRenderer

        self._log.section("TradeChart — heatmap")

        if not isinstance(tickers, (list, tuple)):
            raise ValueError("heatmap() requires a list of tickers.")
        tickers = [validate_ticker(t) for t in tickers]
        if len(tickers) < 2:
            raise ValueError("heatmap() requires at least 2 tickers.")

        duration = validate_duration(duration)
        fmt = validate_format(fmt)

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()
        label = build_group_label(tickers)
        filename = output_name or f"heatmap_{sanitize_filename(label)}_{duration}.{fmt}"
        out_path = self._safe_path(out_dir, filename)

        perf: dict[str, float] = {}
        prices: dict[str, float] = {}
        providers: list[str] = []
        failed: list[str] = []

        for ticker in tickers:
            self._log.section(f"Fetching {ticker}")
            try:
                data = self._fetcher.fetch(ticker, duration)
                df = data.df
                last_close = float(df["Close"].iloc[-1])
                prices[ticker] = last_close
                if len(df) >= 2:
                    first_close = float(df["Close"].iloc[0])
                    perf[ticker] = (last_close / first_close - 1) * 100
                else:
                    perf[ticker] = 0.0
                providers.append(data.provider)
            except Exception as exc:
                self._log.detail("Skip %s — %s", ticker, exc)
                failed.append(ticker)

        if not perf:
            raise DataFetchError("No ticker data could be fetched for the heatmap.")

        if failed:
            self._log.detail(
                "Warning — %d ticker(s) skipped: %s", len(failed), ", ".join(failed)
            )

        valid_tickers = [t for t in tickers if t in perf]
        provider_str = ", ".join(sorted(set(providers))) if providers else None

        self._log.section("Fetching market caps")
        market_caps = self._fetch_market_caps(valid_tickers)

        result_path = HeatmapRenderer().render(
            tickers=valid_tickers,
            perf=perf,
            prices=prices,
            market_caps=market_caps,
            label=label,
            duration=duration,
            output_path=out_path,
            fmt=fmt,
            provider=provider_str,
        )

        self._log.summary(f"✓ Heatmap saved → {result_path}")
        self._log.flush_summary()
        return result_path

    # ── tc.data() ────────────────────────────────────────────────────────

    def fetch_data(self, ticker, duration: str = "1mo") -> pd.DataFrame:
        ticker_validated = validate_ticker_input(ticker)
        duration = validate_duration(duration)
        if isinstance(ticker_validated, list):
            data = self._build_averaged_data(ticker_validated, duration)
        else:
            data = self._fetcher.fetch(ticker_validated, duration)
        return data.df.copy()

    # ── tc.export() ──────────────────────────────────────────────────────

    def export(
        self,
        ticker,
        duration: str = "1mo",
        fmt: str = "csv",
        output_location: str | None = None,
        output_name: str | None = None,
    ) -> Path:
        self._log.section("TradeChart — export data")

        ticker_validated = validate_ticker_input(ticker)
        duration = validate_duration(duration)
        if fmt not in ("csv", "json", "xlsx"):
            raise ValueError(f"Export format must be csv, json, or xlsx — got '{fmt}'")

        out_dir = validate_output_path(output_location) if output_location else Path.cwd()

        if isinstance(ticker_validated, list):
            label = build_group_label(ticker_validated)
            filename = output_name or f"{sanitize_filename(label)}_{duration}.{fmt}"
            out_path = self._safe_path(out_dir, filename)
            data = self._build_averaged_data(ticker_validated, duration)
        else:
            filename = output_name or f"{sanitize_filename(ticker_validated)}_{duration}.{fmt}"
            out_path = self._safe_path(out_dir, filename)
            data = self._fetcher.fetch(ticker_validated, duration)

        df = data.df.copy()

        if fmt == "csv":
            df.to_csv(out_path)
        elif fmt == "json":
            df.to_json(out_path, orient="index", date_format="iso", indent=2)
        elif fmt == "xlsx":
            from tradechart.utils.install import ensure_package
            ensure_package("openpyxl")
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

    def _build_averaged_data(self, tickers: list[str], duration: str) -> MarketData:
        """Fetch data for each ticker in *tickers* and return a single
        :class:`~tradechart.data.models.MarketData` whose OHLCV values are
        the mean across all tickers on each overlapping trading date.

        Tickers that fail to fetch are skipped with a warning; if **none**
        succeed a :class:`~tradechart.utils.exceptions.DataFetchError` is raised.
        If the surviving tickers share no common dates (e.g. different exchanges,
        very short durations) a :class:`~tradechart.utils.exceptions.DataFetchError`
        is also raised with an explanatory message.
        """
        frames: list[pd.DataFrame] = []
        failed: list[str] = []

        for t in tickers:
            self._log.section(f"Fetching {t}")
            try:
                md = self._fetcher.fetch(t, duration)
                frames.append(md.df.copy())
            except Exception as exc:
                msg = f"{t}: {exc}"
                self._log.detail("Skip — %s", msg)
                failed.append(msg)

        if not frames:
            raise DataFetchError(
                f"Every ticker in the group failed to return data for "
                f"duration '{duration}'.\n"
                + "\n".join(f"  • {e}" for e in failed)
            )

        if failed:
            self._log.detail(
                "Warning — %d ticker(s) skipped: %s",
                len(failed), "; ".join(failed),
            )

        # Restrict each frame to the shared trading dates
        common_idx = frames[0].index
        for df in frames[1:]:
            common_idx = common_idx.intersection(df.index)

        if common_idx.empty:
            fetched = len(frames)
            raise DataFetchError(
                f"No overlapping trading dates found across {fetched} ticker(s): "
                f"{tickers}. Try a longer duration or verify the tickers trade on "
                "the same exchange / calendar."
            )

        # Concatenate aligned frames and compute column-wise mean per date
        aligned = pd.concat([df.loc[common_idx] for df in frames])
        avg_df = aligned.groupby(level=0).mean()

        label = build_group_label(tickers)
        self._log.detail(
            "Averaged %d ticker(s) over %d common dates → label '%s'",
            len(frames), len(avg_df), label,
        )
        self._log.summary(
            f"✓ Averaged {len(frames)} ticker(s) "
            f"({len(avg_df)} overlapping dates)"
        )
        return MarketData(ticker=label, duration=duration, provider="averaged", df=avg_df)

    def _fetch_market_caps(self, tickers: list[str]) -> dict[str, float]:
        """Return market-cap values for *tickers* via yfinance.

        Returns a dict mapping ticker → market cap in USD.  Tickers for which
        the data is unavailable (indices, futures, etc.) map to ``0``, which
        tells the heatmap renderer to fall back to the minimum-cap floor.
        """
        from tradechart.utils.install import ensure_package
        ensure_package("yfinance")
        import yfinance as yf

        caps: dict[str, float] = {}
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                cap = info.get("marketCap") or info.get("market_cap") or 0
                caps[ticker] = float(cap) if cap else 0.0
                if caps[ticker] > 0:
                    self._log.detail("Market cap %s → $%s", ticker, f"{caps[ticker]:,.0f}")
                else:
                    self._log.detail("Market cap %s → unavailable", ticker)
            except Exception as exc:
                self._log.detail("Market cap %s — failed: %s", ticker, exc)
                caps[ticker] = 0.0
        return caps

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
