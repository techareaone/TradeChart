"""Native chart engine.

Entry points
------------
``render_chart`` and ``render_comparison`` are what the library calls.
``ChartRenderer`` still exposes ``render`` / ``render_compare`` so older
imports keep working.

The native path draws candles as two collections (wicks + bodies), lays the
figure out once, and saves it in a single pass. ``bbox_inches="tight"`` is
not used — that option renders the figure twice. mplfinance remains an
opt-in candlestick backend via ``tc.config(engine="mplfinance")``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import to_rgba
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator

from tradechart.charts.indicators import apply_indicators
from tradechart.charts.themes import Theme, get_theme
from tradechart.charts.watermark import stamp_logo
from tradechart.config.logger import get_logger
from tradechart.config.settings import get_settings
from tradechart.data.models import MarketData
from tradechart.utils.exceptions import RenderError

# Layout is in figure fractions. The header sits above the axes; saving does
# not crop, so these margins are the whole padding budget.
_MARGIN_L = 0.055
_MARGIN_R = 0.915
_MARGIN_T = 0.80
_MARGIN_B = 0.13

_BODY = 0.62

_RC = {
    "font.size": 9,
    "axes.unicode_minus": False,
    "path.simplify": True,
    "path.simplify_threshold": 0.25,
    "agg.path.chunksize": 20000,
    "savefig.bbox": None,
    "savefig.pad_inches": 0.0,
    # Keep SVG text as text. Outlining every glyph is slower and much larger.
    "svg.fonttype": "none",
}


def _faces() -> tuple[str, str]:
    """Label face and figure face for the current font setting."""
    return get_settings().font_faces()


def _rc() -> dict:
    text, _figures = _faces()
    return {**_RC, "font.family": text}


_OVERLAYS = {
    "sma": ("#e6b450", "SMA 20"),
    "ema": ("#7aa2f7", "EMA 20"),
    "bollinger": ("#8b97a8", "Bollinger"),
    "vwap": ("#c792ea", "VWAP"),
}
_COMPARE_COLORS = ["#f07178", "#3dd68c", "#e6b450", "#c792ea", "#2bb3c0", "#ff8a4c", "#9aa7b8"]
_TYPE_LABEL = {
    "candle": "Candles",
    "heikin_ashi": "Heikin-Ashi",
    "ohlc": "OHLC",
    "line": "Line",
    "area": "Area",
}
_COLUMN_INDICATORS = {"sma", "ema", "bollinger", "vwap", "rsi", "macd"}
_PANEL_RATIO = {"price": 3.5, "volume": 0.78, "rsi": 0.92, "macd": 0.92}


def save_figure(fig: plt.Figure, out_file: Path, fmt: str, dpi: int) -> None:
    """Write *fig* once. PNG/JPEG skip Pillow's extra optimize pass."""
    kwargs: dict = {
        "dpi": dpi,
        "facecolor": fig.get_facecolor(),
        "edgecolor": "none",
    }
    if fmt == "png":
        kwargs["pil_kwargs"] = {"compress_level": 3}
    elif fmt in ("jpg", "jpeg", "webp"):
        kwargs["pil_kwargs"] = {"quality": 82}
    fig.savefig(out_file, **kwargs)


def render_chart(
    data: MarketData,
    chart_type: str,
    output_path: Path,
    fmt: str = "png",
    indicators: list[str] | None = None,
    show_volume: bool = True,
) -> Path:
    """Draw one instrument and return the saved file path."""
    log = get_logger()
    log.section("Rendering chart")

    if data.df.empty:
        raise RenderError("Cannot render an empty dataset.")

    fmt = _normalise_fmt(fmt)
    ind_list = list(indicators or [])
    df = _prepare_frame(data, chart_type, ind_list)
    if df.empty:
        raise RenderError("Cannot render an empty dataset.")
    if ind_list:
        log.detail("Applied indicators: %s", ", ".join(ind_list))

    try:
        with plt.rc_context(_rc()):
            if _wants_mplfinance(chart_type):
                try:
                    theme = get_theme(get_settings().theme)
                    return _render_mplfinance(df, data, output_path, fmt, theme, ind_list, show_volume)
                except RenderError:
                    raise
                except Exception as exc:
                    log.detail("mplfinance engine failed (%s); using native engine", exc)
            elif get_settings().chart_engine == "mplfinance" and chart_type not in ("candle", "heikin_ashi"):
                log.detail("mplfinance engine draws candles only; using native engine for %s", chart_type)
            return _render_native(df, data, chart_type, output_path, fmt, ind_list, show_volume)
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f"Rendering failed: {exc}") from exc


def render_comparison(
    series: list[tuple[str, pd.Series]],
    duration: str,
    normalise: bool,
    output_path: Path,
    fmt: str = "png",
    provider: str | None = None,
) -> Path:
    """Overlay several close series on one chart."""
    log = get_logger()
    if not series:
        raise RenderError("Cannot render a comparison with no series.")

    fmt = _normalise_fmt(fmt)
    settings = get_settings()
    theme = get_theme(settings.theme)

    try:
        with plt.rc_context(_rc()):
            fig = _compose_comparison(series, duration, normalise, theme)
            try:
                if settings.watermark_enabled:
                    stamp_logo(fig, provider=provider)
                out_file = output_path.with_suffix(f".{fmt}")
                save_figure(fig, out_file, fmt, settings.dpi)
            finally:
                plt.close(fig)
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(f"Rendering failed: {exc}") from exc

    log.detail("Saved comparison chart → %s", out_file)
    return out_file


class ChartRenderer:
    """Back-compatible wrapper. New code should call :func:`render_chart`."""

    def render(
        self,
        data: MarketData,
        chart_type: str,
        output_path: Path,
        fmt: str = "png",
        indicators: list[str] | None = None,
        show_volume: bool = True,
    ) -> Path:
        return render_chart(
            data=data,
            chart_type=chart_type,
            output_path=output_path,
            fmt=fmt,
            indicators=indicators,
            show_volume=show_volume,
        )

    def render_compare(
        self,
        series: list[tuple[str, pd.Series]],
        duration: str,
        normalise: bool,
        output_path: Path,
        fmt: str = "png",
        provider: str | None = None,
    ) -> Path:
        return render_comparison(
            series=series,
            duration=duration,
            normalise=normalise,
            output_path=output_path,
            fmt=fmt,
            provider=provider,
        )


# ── Data prep ────────────────────────────────────────────────────────────────

def _prepare_frame(data: MarketData, chart_type: str, indicators: list[str]) -> pd.DataFrame:
    """Return a frame safe to mutate. Heikin-Ashi never touches the source."""
    writes_columns = any(name in _COLUMN_INDICATORS for name in indicators)
    if chart_type == "heikin_ashi":
        holder = MarketData(
            ticker=data.ticker, duration=data.duration,
            provider=data.provider, df=data.df,
        )
        holder.to_heikin_ashi()
        df = holder.df
    elif writes_columns:
        df = data.df.copy()
    else:
        df = data.df
    if writes_columns:
        apply_indicators(df, indicators)
    return df


def _wants_mplfinance(chart_type: str) -> bool:
    return chart_type in ("candle", "heikin_ashi") and get_settings().chart_engine == "mplfinance"


def _normalise_fmt(fmt: str) -> str:
    cleaned = (fmt or "png").lower().lstrip(".")
    return "jpg" if cleaned == "jpeg" else cleaned


# ── Native price chart ───────────────────────────────────────────────────────

def _render_native(
    df: pd.DataFrame,
    meta: MarketData,
    chart_type: str,
    output_path: Path,
    fmt: str,
    indicators: list[str],
    show_volume: bool,
) -> Path:
    settings = get_settings()
    theme = get_theme(settings.theme)
    fig = _compose_price(df, meta, chart_type, indicators, show_volume, theme, settings.fig_size, settings.dpi)
    try:
        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)
        out_file = output_path.with_suffix(f".{fmt}")
        save_figure(fig, out_file, fmt, settings.dpi)
    finally:
        plt.close(fig)
    get_logger().detail("Saved %s chart → %s", chart_type, out_file)
    return out_file


def _compose_price(
    df: pd.DataFrame,
    meta: MarketData,
    chart_type: str,
    indicators: list[str],
    show_volume: bool,
    theme: Theme,
    fig_size: tuple[int, int],
    dpi: int,
) -> plt.Figure:
    panels = _panels(chart_type, indicators, show_volume)
    ratios = [_PANEL_RATIO[name] for name in panels]
    fig, axes = plt.subplots(
        len(panels), 1,
        figsize=fig_size,
        dpi=dpi,
        sharex=True,
        gridspec_kw={"height_ratios": ratios},
    )
    if len(panels) == 1:
        axes = [axes]
    else:
        axes = list(axes)

    try:
        fig.patch.set_facecolor(theme.bg_color)
        fig.subplots_adjust(
            left=_MARGIN_L, right=_MARGIN_R, top=_MARGIN_T, bottom=_MARGIN_B, hspace=0.06,
        )
        for ax in axes:
            ax.set_facecolor(theme.face_color)

        x = np.arange(len(df), dtype=float)
        price_ax = axes[0]
        _draw_price(price_ax, df, x, chart_type, indicators, theme)
        _scale_price(price_ax, df, chart_type)
        if chart_type == "area":
            _shade_close(price_ax, df, x, theme)
        _draw_last_line(price_ax, df, theme)

        for ax, name in zip(axes, panels):
            if name == "volume":
                _draw_volume(ax, df, x, theme)
                _panel_tag(ax, theme, "Volume")
            elif name == "rsi":
                _draw_rsi(ax, df, x, theme)
                _panel_tag(ax, theme, "RSI")
            elif name == "macd":
                _draw_macd(ax, df, x, theme)
                _panel_tag(ax, theme, "MACD")
            _style_axis(ax, theme, grid=(name == "price"))

        if chart_type == "area":
            price_ax.set_axisbelow(False)
            for gridline in price_ax.yaxis.get_gridlines():
                gridline.set_zorder(2)

        _date_ticks(axes[-1], df, meta.duration, theme)
        price_ax.set_xlim(-0.65, len(df) - 0.35)

        price, change, change_color = _header_stats(df, theme)
        _draw_header(
            fig, theme,
            title=meta.ticker,
            subtitle=f"{meta.duration}   ·   {_TYPE_LABEL.get(chart_type, chart_type)}",
            right_title=price,
            right_sub=change,
            right_color=change_color,
        )
        return fig
    except Exception:
        plt.close(fig)
        raise


def _panels(chart_type: str, indicators: list[str], show_volume: bool) -> list[str]:
    panels = ["price"]
    volume_types = chart_type in ("candle", "heikin_ashi", "ohlc")
    if volume_types and (show_volume or "volume" in indicators):
        panels.append("volume")
    if "rsi" in indicators:
        panels.append("rsi")
    if "macd" in indicators:
        panels.append("macd")
    return panels


def _draw_price(ax, df, x, chart_type: str, indicators: list[str], theme: Theme) -> None:
    if chart_type in ("candle", "heikin_ashi"):
        _draw_candles(ax, df, x, theme)
    elif chart_type == "ohlc":
        _draw_ohlc_bars(ax, df, x, theme)
    elif chart_type in ("area", "line"):
        _draw_close(ax, df, x, theme)
    _draw_overlays(ax, df, x, indicators, theme)


def _draw_candles(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    opens = df["Open"].to_numpy(dtype=float, copy=False)
    highs = df["High"].to_numpy(dtype=float, copy=False)
    lows = df["Low"].to_numpy(dtype=float, copy=False)
    closes = df["Close"].to_numpy(dtype=float, copy=False)
    up = closes >= opens
    colors = np.where(up, theme.up_color, theme.down_color)

    wicks = np.empty((len(x), 2, 2), dtype=float)
    wicks[:, 0, 0] = x
    wicks[:, 0, 1] = lows
    wicks[:, 1, 0] = x
    wicks[:, 1, 1] = highs
    ax.add_collection(LineCollection(wicks, colors=colors, linewidths=0.8, zorder=2, antialiaseds=True))

    span = float(np.nanmax(highs) - np.nanmin(lows)) or 1.0
    bottom = np.minimum(opens, closes)
    top = np.maximum(opens, closes)
    flat = (top - bottom) < span * 1e-4
    top = np.where(flat, bottom + span * 1.5e-3, top)
    bodies = _rect_verts(x, bottom, top - bottom, _BODY)
    ax.add_collection(PolyCollection(
        bodies, facecolors=colors, edgecolors=colors, linewidths=0.3, zorder=3, antialiased=False,
    ))


def _draw_ohlc_bars(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    opens = df["Open"].to_numpy(dtype=float, copy=False)
    highs = df["High"].to_numpy(dtype=float, copy=False)
    lows = df["Low"].to_numpy(dtype=float, copy=False)
    closes = df["Close"].to_numpy(dtype=float, copy=False)
    colors = np.where(closes >= opens, theme.up_color, theme.down_color)
    tick = 0.22
    n = len(x)
    segs = np.empty((n * 3, 2, 2), dtype=float)
    segs[0::3, 0, 0] = x
    segs[0::3, 0, 1] = lows
    segs[0::3, 1, 0] = x
    segs[0::3, 1, 1] = highs
    segs[1::3, 0, 0] = x - tick
    segs[1::3, 0, 1] = opens
    segs[1::3, 1, 0] = x
    segs[1::3, 1, 1] = opens
    segs[2::3, 0, 0] = x
    segs[2::3, 0, 1] = closes
    segs[2::3, 1, 0] = x + tick
    segs[2::3, 1, 1] = closes
    repeated = np.repeat(colors, 3)
    ax.add_collection(LineCollection(segs, colors=repeated, linewidths=1.05, zorder=3, antialiaseds=True))


def _series_color(close: np.ndarray, theme: Theme) -> str:
    finite = close[np.isfinite(close)]
    if finite.size == 0:
        return theme.line_color
    return theme.up_color if float(finite[-1]) >= float(finite[0]) else theme.down_color


def _draw_close(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    close = df["Close"].to_numpy(dtype=float, copy=False)
    ax.plot(
        x, close, color=_series_color(close, theme), linewidth=1.7,
        solid_capstyle="round", solid_joinstyle="round", zorder=4,
    )


def _shade_close(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    """One fill down to the pane floor. A second band reads as a step, not a gradient."""
    close = df["Close"].to_numpy(dtype=float, copy=False)
    floor = ax.get_ylim()[0]
    ax.fill_between(x, close, floor, color=_series_color(close, theme), alpha=0.16, linewidth=0, zorder=1)


def _draw_overlays(ax, df: pd.DataFrame, x, indicators: list[str], theme: Theme) -> None:
    drew = False
    for name in indicators:
        spec = _OVERLAYS.get(name)
        if spec is None:
            continue
        color, label = spec
        if name == "sma" and "SMA_20" in df.columns:
            ax.plot(
                x, df["SMA_20"].to_numpy(dtype=float, copy=False),
                color=color, linewidth=1.15, label=label, zorder=4,
            )
            drew = True
        elif name == "ema" and "EMA_20" in df.columns:
            ax.plot(
                x, df["EMA_20"].to_numpy(dtype=float, copy=False),
                color=color, linewidth=1.15, label=label, zorder=4,
            )
            drew = True
        elif name == "bollinger" and "BB_Upper" in df.columns:
            upper = df["BB_Upper"].to_numpy(dtype=float, copy=False)
            lower = df["BB_Lower"].to_numpy(dtype=float, copy=False)
            ax.plot(x, upper, color=color, linewidth=0.8, linestyle=(0, (3, 2)), label=label, zorder=4)
            ax.plot(x, lower, color=color, linewidth=0.8, linestyle=(0, (3, 2)), zorder=4)
            ax.fill_between(x, upper, lower, color=color, alpha=0.08, linewidth=0, zorder=1)
            drew = True
        elif name == "vwap" and "VWAP" in df.columns:
            ax.plot(
                x, df["VWAP"].to_numpy(dtype=float, copy=False),
                color=color, linewidth=1.05, linestyle=(0, (1, 1.6)), label=label, zorder=4,
            )
            drew = True
    if not drew:
        return
    legend = ax.legend(
        loc="upper left", frameon=False, fontsize=8, labelcolor=theme.text_color,
        borderaxespad=0.3, handlelength=1.6,
    )
    label_face, _figure_face = _faces()
    for text in legend.get_texts():
        text.set_fontfamily(label_face)


def _draw_volume(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    volume = df["Volume"].to_numpy(dtype=float, copy=False)
    up = df["Close"].to_numpy(dtype=float, copy=False) >= df["Open"].to_numpy(dtype=float, copy=False)
    up_rgba = np.array(to_rgba(theme.up_color, theme.volume_alpha))
    down_rgba = np.array(to_rgba(theme.down_color, theme.volume_alpha))
    facecolors = np.where(up[:, None], up_rgba, down_rgba)
    positive = np.isfinite(volume) & (volume > 0)
    if not positive.any():
        ax.set_ylim(0, 1)
        return
    verts = _rect_verts(x[positive], np.zeros(int(positive.sum())), volume[positive], _BODY)
    ax.add_collection(PolyCollection(
        verts, facecolors=facecolors[positive], edgecolors="none",
        linewidths=0, antialiased=False, zorder=2,
    ))
    peak = float(np.nanmax(volume))
    ax.set_ylim(0, peak * 1.28 if peak else 1)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=2, prune="lower", min_n_ticks=1))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_volume))


def _draw_rsi(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    if "RSI" not in df.columns:
        return
    rsi = df["RSI"].to_numpy(dtype=float, copy=False)
    ax.fill_between(x, 30, 70, color=theme.grid_color, alpha=0.45, linewidth=0, zorder=1)
    ax.axhline(70, color=theme.down_color, linewidth=0.6, alpha=0.55, linestyle=(0, (3, 2)), zorder=2)
    ax.axhline(30, color=theme.up_color, linewidth=0.6, alpha=0.55, linestyle=(0, (3, 2)), zorder=2)
    ax.plot(x, rsi, color=theme.accent_color, linewidth=1.15, zorder=3)
    ax.set_ylim(0, 100)
    ax.set_yticks([30, 70])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.0f}"))


def _draw_macd(ax, df: pd.DataFrame, x: np.ndarray, theme: Theme) -> None:
    if "MACD" not in df.columns:
        return
    hist = df["MACD_Hist"].to_numpy(dtype=float, copy=False)
    macd = df["MACD"].to_numpy(dtype=float, copy=False)
    signal = df["MACD_Signal"].to_numpy(dtype=float, copy=False)
    up = hist >= 0
    bottom = np.minimum(hist, 0.0)
    height = np.abs(hist)
    finite = np.isfinite(hist)
    if finite.any():
        up_rgba = np.array(to_rgba(theme.up_color, 0.7))
        down_rgba = np.array(to_rgba(theme.down_color, 0.7))
        facecolors = np.where(up[:, None], up_rgba, down_rgba)
        verts = _rect_verts(x[finite], bottom[finite], height[finite], _BODY)
        ax.add_collection(PolyCollection(
            verts, facecolors=facecolors[finite], edgecolors="none", linewidths=0, antialiased=False, zorder=2,
        ))
    ax.axhline(0, color=theme.grid_color, linewidth=0.7, zorder=1)
    ax.plot(x, macd, color=theme.accent_color, linewidth=1.05, label="MACD", zorder=3)
    ax.plot(x, signal, color="#e6b450", linewidth=1.0, label="Signal", zorder=3)
    stacked = np.concatenate([hist, macd, signal])
    stacked = stacked[np.isfinite(stacked)]
    if stacked.size:
        pad = (float(stacked.max()) - float(stacked.min())) * 0.18 or 0.1
        ax.set_ylim(float(stacked.min()) - pad, float(stacked.max()) + pad)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=3, prune="both"))
    ax.yaxis.set_major_formatter(FuncFormatter(_fmt_macd))
    legend = ax.legend(
        loc="upper right", frameon=False, fontsize=7.5, labelcolor=theme.muted_color,
        borderaxespad=0.2, handlelength=1.4,
    )
    label_face, _figure_face = _faces()
    for text in legend.get_texts():
        text.set_fontfamily(label_face)


def _scale_price(ax, df: pd.DataFrame, chart_type: str) -> None:
    cols = ["Open", "High", "Low", "Close"] if chart_type in ("candle", "heikin_ashi", "ohlc") else ["Close"]
    chunks = [df[col].to_numpy(dtype=float, copy=False) for col in cols if col in df.columns]
    for col in ("SMA_20", "EMA_20", "BB_Upper", "BB_Lower", "VWAP"):
        if col in df.columns:
            chunks.append(df[col].to_numpy(dtype=float, copy=False))
    values = np.concatenate(chunks) if chunks else np.array([0.0])
    values = values[np.isfinite(values)]
    if values.size == 0:
        return
    lo = float(values.min())
    hi = float(values.max())
    pad = (hi - lo) * 0.08 or abs(hi) * 0.02 or 1.0
    ax.set_ylim(lo - pad, hi + pad)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(_axis_price_formatter(ax))


def _draw_last_line(ax, df: pd.DataFrame, theme: Theme) -> None:
    close = df["Close"].to_numpy(dtype=float, copy=False)
    finite = close[np.isfinite(close)]
    if finite.size == 0:
        return
    last = float(finite[-1])
    first = float(finite[0])
    color = theme.up_color if last >= first else theme.down_color
    ax.axhline(last, color=color, linewidth=0.7, linestyle=(0, (2, 3)), alpha=0.45, zorder=1)


# ── Comparison ───────────────────────────────────────────────────────────────

def _compose_comparison(
    series: list[tuple[str, pd.Series]],
    duration: str,
    normalise: bool,
    theme: Theme,
) -> plt.Figure:
    settings = get_settings()
    fig, ax = plt.subplots(figsize=settings.fig_size, dpi=settings.dpi)
    try:
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.face_color)
        fig.subplots_adjust(left=_MARGIN_L, right=_MARGIN_R, top=_MARGIN_T, bottom=_MARGIN_B)

        palette: list[str] = []
        for color in (theme.line_color, *_COMPARE_COLORS):
            if color not in palette:
                palette.append(color)

        dated = True
        for i, (name, values) in enumerate(series):
            if not isinstance(values.index, pd.DatetimeIndex):
                dated = False
            ax.plot(
                values.index, values.to_numpy(dtype=float, copy=False),
                color=palette[i % len(palette)], linewidth=1.7, label=name,
                solid_capstyle="round", solid_joinstyle="round", zorder=3 + i,
            )

        if normalise:
            ax.axhline(0, color=theme.muted_color, linewidth=0.7, alpha=0.45, zorder=1)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.1f}%"))
        else:
            ax.yaxis.set_major_formatter(_axis_price_formatter(ax))
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))

        _style_axis(ax, theme, grid=True)
        if dated:
            locator = mdates.AutoDateLocator(minticks=4, maxticks=6)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.margins(x=0.02, y=0.12)

        ncol = 2 if len(series) > 4 else 1
        legend = ax.legend(
            loc="upper left", frameon=False, fontsize=8.5, labelcolor=theme.text_color,
            borderaxespad=0.2, handlelength=1.7, ncol=ncol,
        )
        label_face, _figure_face = _faces()
        for text in legend.get_texts():
            text.set_fontfamily(label_face)

        names = "   ".join(name for name, _ in series)
        title = names if len(names) <= 42 else "Comparison"
        kind = "change from start" if normalise else "price"
        _draw_header(
            fig, theme,
            title=title,
            subtitle=f"{duration}   ·   {kind}",
        )
        return fig
    except Exception:
        plt.close(fig)
        raise


# ── mplfinance compatibility path ────────────────────────────────────────────

def _render_mplfinance(
    df: pd.DataFrame,
    meta: MarketData,
    out: Path,
    fmt: str,
    theme: Theme,
    indicators: list[str],
    show_volume: bool,
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
            "font.family": _faces()[0],
            "axes.labelcolor": theme.text_color,
            "xtick.color": theme.text_color,
            "ytick.color": theme.text_color,
        },
    )

    addplots = []
    color_i = 0
    overlay_colors = ["#e6b450", "#7aa2f7", "#8b97a8", "#c792ea"]
    for ind in indicators:
        if ind == "sma" and "SMA_20" in df.columns:
            addplots.append(mpf.make_addplot(df["SMA_20"], color=overlay_colors[color_i % len(overlay_colors)]))
            color_i += 1
        elif ind == "ema" and "EMA_20" in df.columns:
            addplots.append(mpf.make_addplot(df["EMA_20"], color=overlay_colors[color_i % len(overlay_colors)]))
            color_i += 1
        elif ind == "bollinger" and "BB_Upper" in df.columns:
            band = overlay_colors[color_i % len(overlay_colors)]
            addplots.append(mpf.make_addplot(df["BB_Upper"], color=band, linestyle="--"))
            addplots.append(mpf.make_addplot(df["BB_Lower"], color=band, linestyle="--"))
            color_i += 1
        elif ind == "rsi" and "RSI" in df.columns:
            addplots.append(mpf.make_addplot(df["RSI"], panel=2, color=theme.accent_color, ylabel="RSI"))
        elif ind == "macd" and "MACD" in df.columns:
            panel = 3 if "rsi" in indicators else 2
            addplots.append(mpf.make_addplot(df["MACD"], panel=panel, color=theme.accent_color, ylabel="MACD"))
            addplots.append(mpf.make_addplot(df["MACD_Signal"], panel=panel, color="#e6b450"))

    settings = get_settings()
    fig, _axes = mpf.plot(
        df, type="candle", style=style,
        volume=show_volume,
        title=f"{meta.ticker}  ·  {meta.duration}",
        figsize=settings.fig_size,
        addplot=addplots if addplots else None,
        returnfig=True,
    )
    try:
        if settings.watermark_enabled:
            stamp_logo(fig, provider=meta.provider)
        out_file = out.with_suffix(f".{fmt}")
        save_figure(fig, out_file, fmt, settings.dpi)
    finally:
        plt.close(fig)
    get_logger().detail("Saved mplfinance chart → %s", out_file)
    return out_file


# ── Shared chrome ────────────────────────────────────────────────────────────

def _draw_header(
    fig: plt.Figure,
    theme: Theme,
    *,
    title: str,
    subtitle: str,
    right_title: str = "",
    right_sub: str = "",
    right_color: str | None = None,
) -> None:
    label_face, figure_face = _faces()
    color = right_color or theme.text_color
    fig.text(
        _MARGIN_L, 0.968, title, fontsize=15, fontweight="bold", color=theme.text_color,
        ha="left", va="top", fontfamily=label_face,
    )
    fig.text(
        _MARGIN_L, 0.912, subtitle, fontsize=8.5, color=theme.muted_color,
        ha="left", va="top", fontfamily=label_face,
    )
    if right_title:
        fig.text(
            _MARGIN_R, 0.968, right_title, fontsize=15, fontweight="bold", color=color,
            ha="right", va="top", fontfamily=figure_face,
        )
    if right_sub:
        fig.text(
            _MARGIN_R, 0.912, right_sub, fontsize=8.5, color=color,
            ha="right", va="top", fontfamily=figure_face,
        )
    fig.add_artist(Line2D(
        [_MARGIN_L, _MARGIN_R], [0.862, 0.862],
        transform=fig.transFigure, color=theme.muted_color, alpha=0.35, linewidth=0.8, zorder=5,
    ))


def _style_axis(ax, theme: Theme, *, grid: bool) -> None:
    _label_face, figure_face = _faces()
    kwargs = dict(axis="both", labelsize=8, length=0, pad=5, colors=theme.muted_color)
    try:
        ax.tick_params(labelfontfamily=figure_face, **kwargs)
    except TypeError:
        ax.tick_params(**kwargs)
    ax.yaxis.tick_right()
    for spine in ax.spines.values():
        spine.set_visible(False)
    if theme.spine_visible:
        ax.spines["bottom"].set_visible(True)
        ax.spines["bottom"].set_color(theme.grid_color)
        ax.spines["bottom"].set_linewidth(0.6)
    if grid:
        ax.grid(True, axis="y", color=theme.grid_color, linewidth=0.6, zorder=0)
    else:
        ax.grid(False)
    ax.grid(False, axis="x")
    ax.set_axisbelow(True)


def _panel_tag(ax, theme: Theme, label: str) -> None:
    ax.text(
        0.0, 0.96, label, transform=ax.transAxes, fontsize=7.5, color=theme.muted_color,
        ha="left", va="top", fontfamily=_faces()[0], zorder=5,
    )


def _date_ticks(ax, df: pd.DataFrame, duration: str, theme: Theme) -> None:
    n = len(df)
    if n == 0:
        return
    step = max(1, n // 6)
    ticks = list(range(0, n, step))
    if not ticks:
        ticks = [0]
    if ticks[-1] != n - 1:
        if n - 1 - ticks[-1] < step * 0.55 and len(ticks) > 1:
            ticks[-1] = n - 1
        else:
            ticks.append(n - 1)
    if duration in {"1d", "5d"}:
        fmt = "%d %b %H:%M"
    elif duration in {"1y", "2y", "5y", "10y", "max"}:
        fmt = "%b %Y"
    else:
        fmt = "%d %b"
    labels = []
    for i in ticks:
        idx = df.index[i]
        labels.append(idx.strftime(fmt) if hasattr(idx, "strftime") else str(idx))
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels)
    _label_face, figure_face = _faces()
    kwargs = dict(axis="x", colors=theme.muted_color, labelsize=8, length=0, pad=6)
    try:
        ax.tick_params(labelfontfamily=figure_face, **kwargs)
    except TypeError:
        ax.tick_params(**kwargs)


def _header_stats(df: pd.DataFrame, theme: Theme) -> tuple[str, str, str]:
    close = df["Close"].to_numpy(dtype=float, copy=False)
    finite = close[np.isfinite(close)]
    if finite.size == 0:
        return "—", "", theme.muted_color
    last = float(finite[-1])
    first = float(finite[0])
    color = theme.up_color if last >= first else theme.down_color
    if first == 0 or not np.isfinite(first):
        change = _fmt_signed(last - first)
    else:
        pct = (last - first) / first * 100.0
        change = f"{_fmt_signed(last - first)}   {pct:+.2f}%"
    return _fmt_quote(last), change, color


def _fmt_quote(value: float) -> str:
    """Header price. Keeps cents so the quote is not rounded to a tick."""
    if not np.isfinite(value):
        return "—"
    av = abs(value)
    if av >= 1000:
        return f"{value:,.2f}"
    if av >= 1:
        return f"{value:.2f}"
    if av >= 0.01:
        return f"{value:.4f}"
    return f"{value:.6f}"


def _axis_price_formatter(ax):
    """One precision for every tick, chosen from the visible span."""

    def _fmt(value: float, _pos=None) -> str:
        if not np.isfinite(value):
            return ""
        lo, hi = ax.get_ylim()
        span = abs(hi - lo) or abs(value) or 1.0
        av = max(abs(value), abs(lo), abs(hi))
        if av >= 1000 and span >= 50:
            return f"{value:,.0f}"
        if av >= 10 and span >= 8:
            return f"{value:.0f}"
        if av >= 10 and span >= 1:
            return f"{value:.1f}"
        if av >= 1 or span >= 0.05:
            return f"{value:.2f}"
        if av >= 0.01:
            return f"{value:.4f}"
        return f"{value:.6f}"

    return FuncFormatter(_fmt)


def _fmt_macd(value: float, _pos=None) -> str:
    if not np.isfinite(value):
        return ""
    av = abs(value)
    if av >= 10:
        return f"{value:.1f}"
    if av >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _fmt_signed(value: float) -> str:
    av = abs(value)
    if av >= 1000:
        return f"{value:+,.2f}"
    if av >= 1:
        return f"{value:+.2f}"
    if av >= 0.01:
        return f"{value:+.4f}"
    return f"{value:+.6f}"


def _fmt_volume(value: float, _pos=None) -> str:
    av = abs(value)
    if av >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if av >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if av >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"


def _rect_verts(x: np.ndarray, bottom: np.ndarray, height: np.ndarray, width: float) -> np.ndarray:
    half = width / 2.0
    left = x - half
    right = x + half
    top = bottom + height
    verts = np.empty((len(x), 4, 2), dtype=float)
    verts[:, 0, 0] = left
    verts[:, 0, 1] = bottom
    verts[:, 1, 0] = right
    verts[:, 1, 1] = bottom
    verts[:, 2, 0] = right
    verts[:, 2, 1] = top
    verts[:, 3, 0] = left
    verts[:, 3, 1] = top
    return verts
