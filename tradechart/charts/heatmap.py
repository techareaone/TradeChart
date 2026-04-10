"""Financial performance heatmap renderer.

Tiles are sized by market capitalisation using a squarified treemap algorithm —
large-cap stocks occupy more space, exactly like professional tools (Finviz,
Bloomberg).  Tile colour encodes percentage change over the requested duration.

When market-cap data is unavailable for all tickers (e.g. commodities futures
or indices) the renderer falls back to an equal-area grid.
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

# Fixed gap between tiles in data-coordinate units.
# The canvas spans [0, fig_aspect] × [0, 1], and since fig_aspect = fw/fh the
# x and y data units are identical in physical size (both = fh inches/unit).
# A single constant therefore produces visually uniform gaps on all four sides.
_TILE_GAP = 0.006


# ── Colour map: deep-red → slate-neutral → deep-green ───────────────────────

_HEATMAP_CMAP = mcolors.LinearSegmentedColormap.from_list(
    "tradechart_heatmap",
    [
        "#8b1a1a",  # deep red   (large loss)
        "#c62828",
        "#ef5350",  # light red
        "#546e7a",  # slate-grey (near zero)
        "#26a69a",  # teal-green
        "#00897b",
        "#004d40",  # deep green (large gain)
    ],
    N=256,
)

_NORM_CACHE: dict[float, mcolors.Normalize] = {}


def _tile_color(pct: float, vrange: float) -> str:
    key = round(vrange, 4)
    if key not in _NORM_CACHE:
        _NORM_CACHE[key] = mcolors.Normalize(vmin=-vrange, vmax=vrange)
    return mcolors.to_hex(_HEATMAP_CMAP(_NORM_CACHE[key](pct)))


# ── Squarified treemap ───────────────────────────────────────────────────────

def _worst_aspect(areas: list[float], strip_dim: float) -> float:
    """Worst tile aspect ratio for a candidate row.

    For a strip of length *strip_dim*, items are arranged along the perpendicular
    axis.  The strip width = sum(areas) / strip_dim; each item's other dimension
    = area / strip_width.  Aspect ratio = max(w/h, h/w).
    """
    s = sum(areas)
    if s == 0 or strip_dim == 0:
        return float("inf")
    return max(
        max(strip_dim ** 2 * a / s ** 2, s ** 2 / (strip_dim ** 2 * a))
        for a in areas
    )


def _squarify_layout(
    items: list[str],
    weights: list[float],
    x0: float, y0: float,
    x1: float, y1: float,
) -> list[tuple[str, float, float, float, float]]:
    """Squarified treemap layout.

    Returns a list of ``(item, x0, y0, x1, y1)`` in the coordinate space
    [x0..x1] × [y0..y1].  Weights are normalised internally.
    """
    results: list[tuple[str, float, float, float, float]] = []
    _layout(list(items), list(weights), x0, y0, x1, y1, results)
    return results


def _layout(
    items: list[str],
    weights: list[float],
    x0: float, y0: float,
    x1: float, y1: float,
    results: list,
) -> None:
    if not items:
        return

    W = x1 - x0
    H = y1 - y0

    if W <= 0 or H <= 0:
        return

    if len(items) == 1:
        results.append((items[0], x0, y0, x1, y1))
        return

    # Normalise weights to fill W×H
    total_w = sum(weights)
    area = W * H
    normed = [w * area / total_w for w in weights]

    # Strip runs along the shorter dimension to minimise aspect ratios
    landscape = W >= H
    strip_dim = W if landscape else H

    # Greedily grow the current row while aspect ratio improves
    row_items: list[str] = [items[0]]
    row_normed: list[float] = [normed[0]]

    for i in range(1, len(items)):
        candidate = row_normed + [normed[i]]
        if _worst_aspect(candidate, strip_dim) <= _worst_aspect(row_normed, strip_dim):
            row_items.append(items[i])
            row_normed.append(normed[i])
        else:
            break

    n_row = len(row_items)
    remaining_items = items[n_row:]
    remaining_weights = weights[n_row:]

    s = sum(row_normed)

    if landscape:
        # Horizontal strip: full width W, height h_strip = s / W
        h_strip = s / W
        cx = x0
        for item, a in zip(row_items, row_normed):
            tile_w = a / h_strip
            results.append((item, cx, y0, cx + tile_w, y0 + h_strip))
            cx += tile_w
        _layout(remaining_items, remaining_weights, x0, y0 + h_strip, x1, y1, results)
    else:
        # Vertical strip: full height H, width w_strip = s / H
        w_strip = s / H
        cy = y0
        for item, a in zip(row_items, row_normed):
            tile_h = a / w_strip
            results.append((item, x0, cy, x0 + w_strip, cy + tile_h))
            cy += tile_h
        _layout(remaining_items, remaining_weights, x0 + w_strip, y0, x1, y1, results)


def _equal_grid_layout(
    items: list[str],
    x0: float, y0: float,
    x1: float, y1: float,
) -> list[tuple[str, float, float, float, float]]:
    """Fallback equal-area grid when no market-cap data is available."""
    n = len(items)
    W = x1 - x0
    H = y1 - y0
    # Choose grid proportional to the canvas aspect ratio
    aspect = W / H if H > 0 else 1.0
    ncols = max(1, round(math.sqrt(n * aspect)))
    nrows = math.ceil(n / ncols)
    cell_w = W / ncols
    cell_h = H / nrows
    results = []
    for i, item in enumerate(items):
        col = i % ncols
        row = nrows - 1 - (i // ncols)
        results.append((
            item,
            x0 + col * cell_w, y0 + row * cell_h,
            x0 + (col + 1) * cell_w, y0 + (row + 1) * cell_h,
        ))
    return results


# ── Renderer ─────────────────────────────────────────────────────────────────

class HeatmapRenderer:
    """Stateless renderer — call :meth:`render` to produce a heatmap image."""

    def render(
        self,
        tickers: list[str],
        perf: dict[str, float],          # ticker → % change over duration
        prices: dict[str, float],        # ticker → last close price
        market_caps: dict[str, float],   # ticker → market cap (0 = unknown)
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

        # ── Colour range ──────────────────────────────────────────────────────
        values = [perf.get(t, 0.0) for t in tickers]
        abs_max = max((abs(v) for v in values), default=5.0)
        vrange = max(round(abs_max * 1.15, 1), 2.0)

        # ── Layout ───────────────────────────────────────────────────────────
        # Use figure aspect ratio as the root rectangle so tile aspect ratios
        # computed in data coordinates match what the viewer sees.
        fw, fh = settings.fig_size
        fig_aspect = fw / fh

        weights = [market_caps.get(t, 0.0) for t in tickers]
        has_caps = sum(weights) > 0

        if has_caps:
            # Tickers with unknown cap get the smallest known cap as a floor
            known = [w for w in weights if w > 0]
            floor = min(known) * 0.5
            weights = [w if w > 0 else floor for w in weights]
            layout = _squarify_layout(tickers, weights, 0.0, 0.0, fig_aspect, 1.0)
            weight_note = "market-cap weighted"
        else:
            layout = _equal_grid_layout(tickers, 0.0, 0.0, fig_aspect, 1.0)
            weight_note = "equal weight"

        log.detail("Heatmap layout: %s (%d tiles)", weight_note, len(layout))

        # ── Figure ───────────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(fw, fh))
        fig.patch.set_facecolor(theme.bg_color)
        ax.set_facecolor(theme.bg_color)
        ax.set_xlim(0, fig_aspect)
        ax.set_ylim(0, 1.0)
        ax.set_aspect("auto")
        ax.axis("off")

        # Pre-compute figure height in typographic points for font sizing
        fig_h_pt = fh * 72.0

        for ticker, tx0, ty0, tx1, ty1 in layout:
            pct = perf.get(ticker, 0.0)
            price = prices.get(ticker)
            color = _tile_color(pct, vrange)

            rect = mpatches.Rectangle(
                (tx0 + _TILE_GAP, ty0 + _TILE_GAP),
                (tx1 - tx0) - 2 * _TILE_GAP,
                (ty1 - ty0) - 2 * _TILE_GAP,
                facecolor=color,
                edgecolor="none",
                linewidth=0,
                zorder=2,
            )
            ax.add_patch(rect)

            # ── Font sizes — scale with tile height in points ─────────────────
            tile_h_pt = (ty1 - ty0) * fig_h_pt
            tile_w_pt = (tx1 - tx0) / fig_aspect * fw * 72.0
            min_dim_pt = min(tile_h_pt, tile_w_pt)

            fs_ticker = max(5, min(15, int(min_dim_pt / 7)))
            fs_pct    = max(4, min(13, int(min_dim_pt / 9)))
            fs_price  = max(4, min(11, int(min_dim_pt / 12)))

            show_ticker = tile_h_pt >= 18
            show_pct    = tile_h_pt >= 32
            show_price  = tile_h_pt >= 55 and price is not None

            if not show_ticker:
                continue

            cx = (tx0 + tx1) / 2
            cy = (ty0 + ty1) / 2

            # Vertically distribute text within the tile
            if show_price and show_pct:
                ty_t, ty_p, ty_pr = cy + 0.34 * (ty1 - ty0) * 0.5, cy, cy - 0.34 * (ty1 - ty0) * 0.5
            elif show_pct:
                ty_t, ty_p = cy + 0.22 * (ty1 - ty0) * 0.5, cy - 0.18 * (ty1 - ty0) * 0.5
                ty_pr = None
            else:
                ty_t = cy
                ty_p = ty_pr = None

            ax.text(cx, ty_t, ticker,
                    ha="center", va="center",
                    fontsize=fs_ticker, fontweight="bold",
                    color="white", zorder=3, clip_on=True)

            if show_pct and ty_p is not None:
                sign = "+" if pct >= 0 else ""
                ax.text(cx, ty_p, f"{sign}{pct:.2f}%",
                        ha="center", va="center",
                        fontsize=fs_pct, color="white", alpha=0.92,
                        zorder=3, clip_on=True)

            if show_price and ty_pr is not None:
                price_str = (
                    f"${price:,.0f}" if price >= 1_000
                    else f"${price:.2f}" if price >= 1
                    else f"${price:.4f}"
                )
                ax.text(cx, ty_pr, price_str,
                        ha="center", va="center",
                        fontsize=fs_price, color="white", alpha=0.72,
                        zorder=3, clip_on=True)

        # ── Title ─────────────────────────────────────────────────────────────
        subtitle = f"market-cap weighted" if has_caps else "equal weight"
        ax.set_title(
            f"{label}  •  {duration}  •  Performance Heatmap  ({subtitle})",
            color=theme.text_color, fontsize=12, fontweight="bold", pad=12,
        )

        # ── Colour-bar legend ──────────────────────────────────────────────────
        sm = plt.cm.ScalarMappable(
            cmap=_HEATMAP_CMAP,
            norm=mcolors.Normalize(vmin=-vrange, vmax=vrange),
        )
        sm.set_array([])
        cbar = fig.colorbar(
            sm, ax=ax, orientation="horizontal",
            fraction=0.025, pad=0.03, aspect=50,
        )
        cbar.set_label("% Change", color=theme.text_color, fontsize=9)
        cbar.ax.tick_params(colors=theme.text_color, labelsize=8)
        for spine in cbar.ax.spines.values():
            spine.set_visible(False)

        fig.tight_layout(pad=1.5)

        if settings.watermark_enabled:
            stamp_logo(fig, provider=provider)

        out_file = output_path.with_suffix(f".{fmt}")
        pil_kwargs: dict = {}
        if fmt == "png":
            pil_kwargs = {"compress_level": 6, "optimize": True}
        elif fmt in ("jpg", "jpeg", "webp"):
            pil_kwargs = {"quality": 82, "optimize": True}
        save_kwargs: dict = {"dpi": settings.dpi, "facecolor": fig.get_facecolor(), "bbox_inches": "tight"}
        if pil_kwargs:
            save_kwargs["pil_kwargs"] = pil_kwargs
        fig.savefig(out_file, **save_kwargs)
        plt.close(fig)
        log.detail("Saved heatmap → %s", out_file)
        return out_file
