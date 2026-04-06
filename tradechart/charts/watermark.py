from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import matplotlib.figure

from tradechart.config.logger import get_logger

_LOGO_URL = "https://doc.tradely.dev/images/watermark_tradely.png"
_CACHE_DIR = Path.home() / ".tradechart" / "cache"
_CACHED_PNG = _CACHE_DIR / "tradely_logo.png"
_LOCK = threading.Lock()
_LOGO_LOADED: object | None = None  # cached matplotlib image array


def _download_png() -> bytes | None:
    """Download the raw PNG bytes from the TRADELY CDN."""
    log = get_logger()
    try:
        import urllib.request

        log.detail("Logo: downloading PNG from %s", _LOGO_URL)
        req = urllib.request.Request(
            _LOGO_URL,
            headers={"User-Agent": "TradeChart/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read()
    except Exception as exc:
        log.detail("Logo: download failed — %s", exc)
        return None


def _ensure_png() -> Path | None:
    """Ensure the PNG exists locally and return its path."""
    log = get_logger()

    # Already cached
    if _CACHED_PNG.exists() and _CACHED_PNG.stat().st_size > 0:
        log.detail("Logo: using cached PNG at %s", _CACHED_PNG)
        return _CACHED_PNG

    # Download PNG directly
    png_bytes = _download_png()
    if png_bytes is None:
        return None

    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

        with open(_CACHED_PNG, "wb") as f:
            f.write(png_bytes)

        log.detail("Logo: downloaded and cached → %s", _CACHED_PNG)
        return _CACHED_PNG

    except Exception as exc:
        log.detail("Logo: write failed — %s", exc)
        return None


def _load_image():
    """Load the logo PNG into a matplotlib-compatible array (RGBA)."""
    global _LOGO_LOADED

    if _LOGO_LOADED is not None:
        return _LOGO_LOADED

    png_path = _ensure_png()
    if png_path is None or not png_path.exists():
        return None

    try:
        import matplotlib.image as mimage

        _LOGO_LOADED = mimage.imread(str(png_path))
        return _LOGO_LOADED
    except Exception as exc:
        get_logger().detail("Logo: imread failed — %s", exc)
        return None


def stamp_logo(fig: "matplotlib.figure.Figure", provider: str | None = None) -> None:
    """Overlay the TRADELY logo and data source in the bottom-left corner of *fig*."""
    with _LOCK:
        logo = _load_image()

    if logo is None:
        get_logger().detail("Logo: skipped (unavailable)")
        return

    logo_ax = fig.add_axes([0.008, 0.040, 0.05, 0.05], anchor="SW")
    logo_ax.imshow(logo, aspect="equal", interpolation="lanczos")
    logo_ax.axis("off")

    # Add data source text if provider is specified
    if provider:
        text_ax = fig.add_axes([0.008, 0.008, 0.1, 0.015], anchor="SW")
        text_ax.text(0, 0.5, f"Source: {provider}",
                    fontsize=7, color="#999999", va="center",
                    fontfamily="monospace")
        text_ax.axis("off")

    get_logger().detail("Logo: stamped on chart%s", f" with source '{provider}'" if provider else "")


def clear_cache() -> None:
    """Delete the cached PNG so the next render re-downloads it."""
    global _LOGO_LOADED
    _LOGO_LOADED = None
    if _CACHED_PNG.exists():
        _CACHED_PNG.unlink()
        get_logger().detail("Logo: cache cleared")