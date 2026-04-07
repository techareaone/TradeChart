"""Financial performance heatmap renderer.

Produces a grid of coloured tiles — one per ticker — where the tile colour
encodes the percentage change over the requested duration.  Designed to work
with ticker groups (``tc.SECTOR_GROUPS``) so an entire sector can be visualised
in a single call.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

from tradechart.config.logger import get_logger
from tradechart.config.settings import get_settings
from tradechart.charts.themes import get_theme
from tradechart.charts.watermark import stamp_logo
from tradechart.utils.exceptions import RenderError


# ── Colour map: deep-red → slate-neutral → deep-green ───────────────────────

_HEATMAP_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "tradechart_heatmap",
    [
        "#8b1a1a",  # deep red   (large loss)
        "#c62828",  # red
        "#ef5350",  # light red
        "#546e7a",  # slate-grey (neutral / near zero)
        "#26a69a",  # teal-green
        "#00897b",  # green
        "#004d40",  # deep green (large gain)
    ],
    N=256,
)

_NORM_CACHE: dict[float, mcolors.Normalize] = {}


def _tile_color(pct: float, vrange: float) -> str:
    """Map *pct* to a hex colour centred at zero with ±*vrange* bounds."""
    key = round(vrange, 4)
    if key not in _NORM_CACHE:
        _NORM_CACHE[key] = mcolors.Normalize(vmin=-vrange, vmax=vrange)
    norm = _NORM_CACHE[key]
    return mcolors.to_hex(_HEATMAP_CMAP(norm(pct)))


def _font_sizes(ncols: int) -> tuple[int, int, int]:
    """Return (ticker_fs, pct_fs, price_fs) scaled for the grid width."""
    if ncols <= 2:
        return 13, 10, 8
    if ncols <= 3:
        return 11, 9, 7
    if ncols <= 4:
        return 9, 7, 6
    if ncols <= 5:
        return 8, 6, 5
    return 7, 5, 4


class HeatmapRenderer:
    """Stateless renderer — call :meth:`render` to produce a heatmap image."""

    def render(
        self,
        tickers: list[str],
        perf: dict[str, float],    # ticker → % change over duration
        prices: dict[str, float],  # ticker → last close price
        label: str,
        duration: str,
        output_path: Path,
        fmt: str = "png",
        provider: str | None = None,
    ) -> Path:
        log = get_logger()
        settings = get_settings()
        theme = get_theme(settings.theme)

        if not tickers:
            raise RenderError("Cannot render heatmap with no tickers.")

        n = len(tickers)
        ncols = math.ceil(math.sqrt(n))
        nrows = math.ceil(n / ncols)

        # Dynamic colour range — symmetrical, at least ±2 %
        values = [perf.get(t, 0.0) for t in tickers]
        abs_max = max((abs(v) for v in values), default=5.0)
        vrange = max(round(abs_max * 1.15, 1), 2.0)

        fs_ticker, fs_pct, fs_price = _font_sizes(ncols)

        fig, ax = plt.subplots(figsize=settings.fig_size)
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.bg_color)
        ax.set_xlim(0, ncols)
        ax.set_ylim(0, nrows)
        ax.axis("off")

        for i, ticker in enumerate(tickers):
            row = nrows - 1 - (i // ncols)
            col = i % ncols
            pct = perf.get(ticker, 0.0)
            price = prices.get(ticker)
            color = _tile_color(pct, vrange)

            # ── Rounded-rectangle tile ──────────────────────────────────────
            rect = mpatches.FancyBboxPatch(
                (col + 0.04, row + 0.04), 0.92, 0.92,
                boxstyle="round,pad=0.03",
                facecolor=color,
                edgecolor=theme.bg_color,
                linewidth=2.5,
                zorder=2,
            )
            ax.add_patch(rect)

            cx = col + 0.50
            cy = row + 0.50

            # ── Text layout (3 rows: ticker / pct / price) ──────────────────
            has_price = price is not None
            if has_price:
                ty, py, pry = cy + 0.17, cy - 0.03, cy - 0.22
            else:
                ty, py = cy + 0.08, cy - 0.11
                pry = None  # unused

            ax.text(cx, ty, ticker,
                    ha="center", va="center",
                    fontsize=fs_ticker, fontweight="bold",
                    color="white", zorder=3)

            sign = "+" if pct >= 0 else ""
            ax.text(cx, py, f"{sign}{pct:.2f}%",
                    ha="center", va="center",
                    fontsize=fs_pct, color="white", alpha=0.95, zorder=3)

            if has_price and pry is not None:
                price_str = (
                    f"${price:,.0f}" if price >= 1_000
                    else f"${price:.2f}" if price >= 1
                    else f"${price:.4f}"
                )
                ax.text(cx, pry, price_str,
                        ha="center", va="center",
                        fontsize=fs_price, color="white", alpha=0.75, zorder=3)

        # ── Title ────────────────────────────────────────────────────────────
        ax.set_title(
            f"{label}  •  {duration}  •  Performance Heatmap",
            color=theme.text_color, fontsize=13, fontweight="bold", pad=14,
        )

        # ── Colour-bar legend ────────────────────────────────────────────────
        sm = plt.cm.ScalarMappable(
            cmap=_HEATMAP_CMAP,
            norm=mcolors.Normalize(vmin=-vrange, vmax=vrange),
        )
        sm.set_array([])
        cbar = fig.colorbar(
            sm, ax=ax, orientation="horizontal",
            fraction=0.025, pad=0.03, aspect=45,
        )
        cbar.set_label("% Change", color=theme.text_color, fontsize=9)
        cbar.ax.tick_params(colors=theme.text_color, labelsize=8)
        for spine in cbar.ax.spines.values():
            spine.set_visible(False)

        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig, provider=provider)

        out_file = output_path.with_suffix(f".{fmt}")
        fig.savefig(out_file, dpi=settings.dpi,
                    facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        log.detail("Saved heatmap → %s", out_file)
        return out_file
