"""Chart rendering layer."""

from tradechart.charts.renderer import ChartRenderer, render_chart, render_comparison
from tradechart.charts.watermark import stamp_logo, clear_cache as clear_logo_cache
from tradechart.charts.themes import Theme, get_theme
from tradechart.charts.indicators import apply_indicators

__all__ = [
    "ChartRenderer", "render_chart", "render_comparison",
    "stamp_logo", "clear_logo_cache", "Theme", "get_theme", "apply_indicators",
]
