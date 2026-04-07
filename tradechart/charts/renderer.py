"""Chart rendering — produces PNG/SVG/PDF from MarketData."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from tradechart.data.models import MarketData
from tradechart.config.logger import get_logger
from tradechart.config.settings import get_settings
from tradechart.utils.exceptions import RenderError
from tradechart.charts.themes import Theme, get_theme
from tradechart.charts.watermark import stamp_logo
from tradechart.charts.indicators import apply_indicators

# ── Indicator overlay colours ────────────────────────────────────────────────

_OVERLAY_COLORS = ["#ffab40", "#ab47bc", "#26c6da", "#ff7043", "#66bb6a", "#ec407a"]


class ChartRenderer:
    """Stateless renderer — call :meth:`render` to produce a chart file."""

    def render(
        self,
        data: MarketData,
        chart_type: str,
        output_path: Path,
        fmt: str = "png",
        indicators: list[str] | None = None,
        show_volume: bool = True,
    ) -> Path:
        log = get_logger()
        log.section("Rendering chart")

        df = data.df.copy()
        if df.empty:
            raise RenderError("Cannot render an empty dataset.")

        # Convert Heikin-Ashi before indicators
        if chart_type == "heikin_ashi":
            data_copy = MarketData(
                ticker=data.ticker, duration=data.duration,
                provider=data.provider, df=df,
            )
            data_copy.to_heikin_ashi()
            df = data_copy.df

        # Apply indicators
        ind_list = indicators or []
        if ind_list:
            apply_indicators(df, ind_list)
            log.detail("Applied indicators: %s", ", ".join(ind_list))

        settings = get_settings()
        theme = get_theme(settings.theme)

        try:
            if chart_type in ("candle", "heikin_ashi"):
                path = self._render_candlestick(df, data, output_path, fmt, theme, ind_list, show_volume)
            elif chart_type == "ohlc":
                path = self._render_ohlc(df, data, output_path, fmt, theme, ind_list, show_volume)
            elif chart_type == "area":
                path = self._render_area(df, data, output_path, fmt, theme, ind_list)
            else:  # line
                path = self._render_line(df, data, output_path, fmt, theme, ind_list)

            return path
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"Rendering failed: {exc}") from exc

    # ── Candlestick ──────────────────────────────────────────────────────

    def _render_candlestick(
        self, df: pd.DataFrame, meta: MarketData, out: Path,
        fmt: str, theme: Theme, indicators: list[str], show_volume: bool,
    ) -> Path:
        log = get_logger()

        # Try mplfinance first
        try:
            return self._render_mplfinance(df, meta, out, fmt, theme, indicators, show_volume)
        except Exception as exc:
            log.detail("mplfinance unavailable (%s), using matplotlib fallback", exc)

        settings = get_settings()
        has_vol = show_volume and "volume" not in [i for i in indicators if i == "volume"]
        has_rsi = "rsi" in indicators
        has_macd = "macd" in indicators

        # Determine subplot layout
        n_panels = 1
        ratios = [4]
        if has_vol:
            n_panels += 1
            ratios.append(1)
        if has_rsi:
            n_panels += 1
            ratios.append(1)
        if has_macd:
            n_panels += 1
            ratios.append(1)

        fig, axes = plt.subplots(
            n_panels, 1,
            figsize=settings.fig_size,
            gridspec_kw={"height_ratios": ratios},
            sharex=True,
        )
        if n_panels == 1:
            axes = [axes]

        fig.patch.set_facecolor(theme.bg_color)
        for ax in axes:
            ax.set_facecolor(theme.face_color)

        ax_price = axes[0]
        opens, closes = df["Open"].values, df["Close"].values
        highs, lows = df["High"].values, df["Low"].values
        volumes = df["Volume"].values
        x_arr = np.arange(len(df))
        up_mask = closes >= opens

        # Wicks — two batch vlines calls instead of N individual plot() calls
        ax_price.vlines(x_arr[up_mask],   lows[up_mask],   highs[up_mask],
                        colors=theme.up_color,   linewidth=0.6)
        ax_price.vlines(x_arr[~up_mask],  lows[~up_mask],  highs[~up_mask],
                        colors=theme.down_color, linewidth=0.6)

        # Bodies — two batch bar calls instead of N individual bar() calls
        body_w = max(0.4, min(0.8, 60 / max(len(df), 1)))
        bottoms = np.minimum(opens, closes)
        heights = np.abs(closes - opens)
        heights = np.where(heights == 0, (highs - lows) * 0.01, heights)
        ax_price.bar(x_arr[up_mask],  heights[up_mask],  bottom=bottoms[up_mask],
                     width=body_w, color=theme.up_color,   edgecolor=theme.up_color,   linewidth=0.5)
        ax_price.bar(x_arr[~up_mask], heights[~up_mask], bottom=bottoms[~up_mask],
                     width=body_w, color=theme.down_color, edgecolor=theme.down_color, linewidth=0.5)

        # Overlay indicators on price axis
        self._draw_overlays(ax_price, df, x_arr, indicators, theme)

        # Subplots
        panel_idx = 1
        if has_vol:
            vol_colors = np.where(up_mask, theme.up_color, theme.down_color)
            axes[panel_idx].bar(x_arr, volumes, width=body_w, color=vol_colors, alpha=theme.volume_alpha)
            self._style_ax(axes[panel_idx], theme, ylabel="Volume")
            panel_idx += 1
        if has_rsi and "RSI" in df.columns:
            axes[panel_idx].plot(x_arr, df["RSI"].values, color="#ab47bc", linewidth=1.0)
            axes[panel_idx].axhline(70, color=theme.grid_color, linestyle="--", linewidth=0.5)
            axes[panel_idx].axhline(30, color=theme.grid_color, linestyle="--", linewidth=0.5)
            axes[panel_idx].set_ylim(0, 100)
            self._style_ax(axes[panel_idx], theme, ylabel="RSI")
            panel_idx += 1
        if has_macd and "MACD" in df.columns:
            axes[panel_idx].plot(x_arr, df["MACD"].values, color="#26c6da", linewidth=1.0, label="MACD")
            axes[panel_idx].plot(x_arr, df["MACD_Signal"].values, color="#ff7043", linewidth=1.0, label="Signal")
            hist_colors = np.where(df["MACD_Hist"].values >= 0, theme.up_color, theme.down_color)
            axes[panel_idx].bar(x_arr, df["MACD_Hist"].values, width=body_w,
                                color=hist_colors, alpha=0.6)
            self._style_ax(axes[panel_idx], theme, ylabel="MACD")
            panel_idx += 1

        # Title + styling
        ax_price.set_title(
            f"{meta.ticker}  •  {meta.duration}",
            color=theme.text_color, fontsize=14, fontweight="bold", pad=12,
        )
        self._style_ax(ax_price, theme, ylabel="Price")

        # X-axis date labels on bottom axis
        self._set_date_labels(axes[-1], df, theme)

        fig.tight_layout(pad=1.5)
        if get_settings().watermark_enabled:
            stamp_logo(fig, provider=meta.provider)

        out_file = out.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=get_settings().dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        log.detail("Saved candlestick chart → %s", out_file)
        return out_file

    def _render_mplfinance(
        self, df: pd.DataFrame, meta: MarketData, out: Path,
        fmt: str, theme: Theme, indicators: list[str], show_volume: bool,
    ) -> Path:
        from tradechart.utils.install import ensure_package
        ensure_package("mplfinance")
        import mplfinance as mpf

        mc = mpf.make_marketcolors(
            up=theme.up_color, down=theme.down_color,
            wick={"up": theme.up_color, "down": theme.down_color},
            edge={"up": theme.up_color, "down": theme.down_color},
            volume={"up": theme.up_color, "down": theme.down_color},
        )
        style = mpf.make_mpf_style(
            marketcolors=mc,
            facecolor=theme.face_color,
            figcolor=theme.bg_color,
            gridcolor=theme.grid_color,
            gridstyle="--", gridaxis="both",
            rc={
                "axes.labelcolor": theme.text_color,
                "xtick.color": theme.text_color,
                "ytick.color": theme.text_color,
            },
        )

        # Build addplots for overlays
        addplots = []
        ci = 0
        for ind in indicators:
            if ind == "sma" and f"SMA_20" in df.columns:
                addplots.append(mpf.make_addplot(df["SMA_20"], color=_OVERLAY_COLORS[ci % len(_OVERLAY_COLORS)]))
                ci += 1
            elif ind == "ema" and "EMA_20" in df.columns:
                addplots.append(mpf.make_addplot(df["EMA_20"], color=_OVERLAY_COLORS[ci % len(_OVERLAY_COLORS)]))
                ci += 1
            elif ind == "bollinger" and "BB_Upper" in df.columns:
                addplots.append(mpf.make_addplot(df["BB_Upper"], color=_OVERLAY_COLORS[ci % len(_OVERLAY_COLORS)], linestyle="--"))
                addplots.append(mpf.make_addplot(df["BB_Lower"], color=_OVERLAY_COLORS[ci % len(_OVERLAY_COLORS)], linestyle="--"))
                ci += 1
            elif ind == "rsi" and "RSI" in df.columns:
                addplots.append(mpf.make_addplot(df["RSI"], panel=2, color="#ab47bc", ylabel="RSI"))
            elif ind == "macd" and "MACD" in df.columns:
                p = 3 if "rsi" in indicators else 2
                addplots.append(mpf.make_addplot(df["MACD"], panel=p, color="#26c6da", ylabel="MACD"))
                addplots.append(mpf.make_addplot(df["MACD_Signal"], panel=p, color="#ff7043"))

        settings = get_settings()
        title = f"{meta.ticker}  •  {meta.duration}"

        fig, axes = mpf.plot(
            df, type="candle", style=style,
            volume=show_volume, title=title,
            figsize=settings.fig_size,
            addplot=addplots if addplots else None,
            returnfig=True,
        )

        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)

        out_file = out.with_suffix(f".{fmt}")
        fig.savefig(str(out_file), dpi=settings.dpi,
                    bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        get_logger().detail("Saved mplfinance chart → %s", out_file)
        return out_file

    # ── OHLC bars ────────────────────────────────────────────────────────

    def _render_ohlc(
        self, df: pd.DataFrame, meta: MarketData, out: Path,
        fmt: str, theme: Theme, indicators: list[str], show_volume: bool,
    ) -> Path:
        settings = get_settings()
        n_panels = 1 + (1 if show_volume else 0)
        ratios = [3] + ([1] if show_volume else [])

        fig, axes = plt.subplots(
            n_panels, 1, figsize=settings.fig_size,
            gridspec_kw={"height_ratios": ratios}, sharex=True,
        )
        if n_panels == 1:
            axes = [axes]
        fig.patch.set_facecolor(theme.bg_color)
        for ax in axes:
            ax.set_facecolor(theme.face_color)

        ax_price = axes[0]
        opens, closes = df["Open"].values, df["Close"].values
        highs, lows = df["High"].values, df["Low"].values
        x_arr = np.arange(len(df))
        up_mask = closes >= opens
        tick_w = max(0.15, min(0.4, 30 / max(len(df), 1)))

        # High-low wicks — batch vlines instead of N plot() calls
        ax_price.vlines(x_arr[up_mask],  lows[up_mask],  highs[up_mask],
                        colors=theme.up_color,   linewidth=0.8)
        ax_price.vlines(x_arr[~up_mask], lows[~up_mask], highs[~up_mask],
                        colors=theme.down_color, linewidth=0.8)
        # Open ticks (left side) — batch hlines
        ax_price.hlines(opens[up_mask],  x_arr[up_mask]  - tick_w, x_arr[up_mask],
                        colors=theme.up_color,   linewidth=1.0)
        ax_price.hlines(opens[~up_mask], x_arr[~up_mask] - tick_w, x_arr[~up_mask],
                        colors=theme.down_color, linewidth=1.0)
        # Close ticks (right side) — batch hlines
        ax_price.hlines(closes[up_mask],  x_arr[up_mask],  x_arr[up_mask]  + tick_w,
                        colors=theme.up_color,   linewidth=1.0)
        ax_price.hlines(closes[~up_mask], x_arr[~up_mask], x_arr[~up_mask] + tick_w,
                        colors=theme.down_color, linewidth=1.0)

        self._draw_overlays(ax_price, df, x_arr, indicators, theme)

        if show_volume:
            vol_colors = np.where(up_mask, theme.up_color, theme.down_color)
            axes[1].bar(x_arr, df["Volume"].values, width=0.6, color=vol_colors, alpha=theme.volume_alpha)
            self._style_ax(axes[1], theme, ylabel="Volume")

        ax_price.set_title(f"{meta.ticker}  •  {meta.duration}",
                           color=theme.text_color, fontsize=14, fontweight="bold", pad=12)
        self._style_ax(ax_price, theme, ylabel="Price")
        self._set_date_labels(axes[-1], df, theme)
        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)

        out_file = out.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        get_logger().detail("Saved OHLC chart → %s", out_file)
        return out_file

    # ── Line chart ───────────────────────────────────────────────────────

    def _render_line(
        self, df: pd.DataFrame, meta: MarketData, out: Path,
        fmt: str, theme: Theme, indicators: list[str],
    ) -> Path:
        settings = get_settings()
        fig, ax = plt.subplots(figsize=settings.fig_size)
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.face_color)

        ax.plot(df.index, df["Close"], color=theme.line_color, linewidth=1.4)
        self._draw_overlays(ax, df, df.index, indicators, theme)

        ax.set_title(f"{meta.ticker}  •  {meta.duration}",
                     color=theme.text_color, fontsize=14, fontweight="bold", pad=12)
        self._style_ax(ax, theme, ylabel="Price")

        fig.autofmt_xdate(rotation=30)
        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)

        out_file = out.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        get_logger().detail("Saved line chart → %s", out_file)
        return out_file

    # ── Area chart ───────────────────────────────────────────────────────

    def _render_area(
        self, df: pd.DataFrame, meta: MarketData, out: Path,
        fmt: str, theme: Theme, indicators: list[str],
    ) -> Path:
        settings = get_settings()
        fig, ax = plt.subplots(figsize=settings.fig_size)
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.face_color)

        ax.plot(df.index, df["Close"], color=theme.line_color, linewidth=1.2)
        ax.fill_between(df.index, df["Close"], alpha=0.15, color=theme.line_color)
        self._draw_overlays(ax, df, df.index, indicators, theme)

        ax.set_title(f"{meta.ticker}  •  {meta.duration}",
                     color=theme.text_color, fontsize=14, fontweight="bold", pad=12)
        self._style_ax(ax, theme, ylabel="Price")

        fig.autofmt_xdate(rotation=30)
        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)

        out_file = out.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        get_logger().detail("Saved area chart → %s", out_file)
        return out_file

    # ── Helpers ──────────────────────────────────────────────────────────

    def _draw_overlays(
        self, ax: plt.Axes, df: pd.DataFrame,
        x_data, indicators: list[str], theme: Theme,
    ) -> None:
        """Draw SMA/EMA/Bollinger/VWAP overlays on a price axis."""
        ci = 0
        for ind in indicators:
            c = _OVERLAY_COLORS[ci % len(_OVERLAY_COLORS)]
            if ind == "sma" and "SMA_20" in df.columns:
                ax.plot(x_data, df["SMA_20"].values, color=c, linewidth=1.0,
                        label="SMA 20", linestyle="-")
                ci += 1
            elif ind == "ema" and "EMA_20" in df.columns:
                ax.plot(x_data, df["EMA_20"].values, color=c, linewidth=1.0,
                        label="EMA 20", linestyle="-")
                ci += 1
            elif ind == "bollinger" and "BB_Upper" in df.columns:
                ax.plot(x_data, df["BB_Upper"].values, color=c, linewidth=0.7,
                        linestyle="--", label="BB Upper")
                ax.plot(x_data, df["BB_Lower"].values, color=c, linewidth=0.7,
                        linestyle="--", label="BB Lower")
                ax.fill_between(
                    x_data,
                    df["BB_Upper"].values, df["BB_Lower"].values,
                    alpha=0.06, color=c,
                )
                ci += 1
            elif ind == "vwap" and "VWAP" in df.columns:
                ax.plot(x_data, df["VWAP"].values, color=c, linewidth=1.0,
                        label="VWAP", linestyle="-.")
                ci += 1

        if ci > 0:
            ax.legend(loc="upper left", fontsize=8,
                      facecolor=theme.face_color, edgecolor=theme.grid_color,
                      labelcolor=theme.text_color)

    @staticmethod
    def _style_ax(ax: plt.Axes, theme: Theme, ylabel: str = "") -> None:
        if ylabel:
            ax.set_ylabel(ylabel, color=theme.text_color, fontsize=11)
        ax.tick_params(colors=theme.text_color, labelsize=9)
        ax.grid(True, color=theme.grid_color, linestyle="--", linewidth=0.5, alpha=0.7)
        if not theme.spine_visible:
            for spine in ax.spines.values():
                spine.set_visible(False)

    @staticmethod
    def _set_date_labels(ax: plt.Axes, df: pd.DataFrame, theme: Theme) -> None:
        n = len(df)
        step = max(1, n // 12)
        ticks = list(range(0, n, step))
        labels = []
        for i in ticks:
            idx = df.index[i]
            labels.append(idx.strftime("%b %d") if hasattr(idx, "strftime") else str(idx))
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels, rotation=30, ha="right")
