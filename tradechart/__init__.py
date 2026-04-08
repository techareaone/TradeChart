"""
TradeChart — production-quality financial chart generator.

A TRADELY project · https://doc.tradely.dev

Public API
----------
tc.terminal(mode)       — Set logging verbosity.
tc.theme(name)          — Set chart colour theme.
tc.watermark(enabled)   — Toggle the TRADELY logo watermark.
tc.config(**kwargs)     — Batch-set global options.
tc.chart(...)           — Fetch data and render a chart.
tc.compare(...)         — Overlay multiple tickers on one chart.
tc.heatmap(...)         — Render a performance heatmap for a ticker group.
tc.data(...)            — Fetch raw OHLCV data as a DataFrame.
tc.export(...)          — Export market data to CSV / JSON / XLSX.
tc.clear_cache()        — Flush the in-memory data cache.
tc.store(path)          — Set persistent data-store directory.
tc.store(ticker, ...)   — Pre-fetch and persist tickers / groups.

Persistent store
----------------
``tc.store()`` enables a two-level cache: in-memory (TTL-based) **and**
on-disk (permanent across sessions).  Set the location once, then list any
tickers or named groups to pre-fetch them:

>>> tc.store("/data/myproject")        # creates /data/myproject/tradechart_FetchData/
>>> tc.store("AAPL", "MSFT", "1mo")   # fetch & persist
>>> tc.store("mag7", "3mo")           # fetch every ticker in the Mag-7 group
>>> tc.chart("AAPL", "1mo")           # served from disk — no network request

Sector groups
-------------
``tc.SECTOR_GROUPS`` is a dict of pre-defined ticker lists for common market
segments.  Pass any value directly into ``heatmap()``, ``compare()``,
``chart()``, or ``export()``:

>>> tc.heatmap(tc.SECTOR_GROUPS["mag7"], "1mo")
>>> tc.heatmap(tc.SECTOR_GROUPS["sp500_etfs"], "3mo")
>>> tc.compare(tc.SECTOR_GROUPS["tech"], "6mo")

Available keys: ``"mag7"``, ``"sp500_etfs"``, ``"tech"``, ``"finance"``,
``"energy"``, ``"healthcare"``, ``"consumer_disc"``, ``"consumer_stap"``,
``"industrials"``, ``"realestate"``, ``"utilities"``, ``"crypto"``,
``"indices"``, ``"commodities"``.

Ticker groups (averaging)
-------------------------
``chart()``, ``data()``, and ``export()`` accept a list or tuple of ticker
symbols in place of a single string.  The library fetches each symbol
independently and averages their OHLCV values across overlapping dates,
then renders or returns that averaged series.

>>> tech = ["AAPL", "MSFT", "AMZN"]
>>> tc.chart(tech, "3mo", "line")   # single line of averaged closes

The variable name does not matter — passing a list is always treated as a
group regardless of whether the name matches a real ticker symbol.

Example
-------
>>> import tradechart as tc
>>> tc.terminal("full")
>>> tc.chart("AAPL", "1mo", "candle", indicators=["sma", "bollinger"])
>>> tc.heatmap(tc.SECTOR_GROUPS["mag7"], "3mo")
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union
import threading

import pandas as pd

from tradechart.config.settings import get_settings
from tradechart.core.engine import Engine
from tradechart.data.groups import SECTOR_GROUPS
from tradechart.utils.exceptions import (
    TradeChartError,
    DataFetchError,
    InvalidTickerError,
    RenderError,
    OutputError,
    ConfigError,
)
from tradechart.utils.validation import VALID_DURATIONS

__version__ = "2.2.0"
__all__ = [
    "terminal", "theme", "watermark", "config",
    "chart", "compare", "heatmap", "data", "export", "clear_cache",
    "store",
    "SECTOR_GROUPS",
]

_engine: Engine | None = None
_engine_lock = threading.Lock()


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = Engine()
    return _engine


# ── Configuration ────────────────────────────────────────────────────────────

def terminal(feedback_type: str) -> None:
    """Set global logging verbosity.

    Parameters
    ----------
    feedback_type : ``"full"`` | ``"on_done"`` | ``"none"``
    """
    get_settings().terminal_mode = feedback_type


def theme(name: str) -> None:
    """Set the chart colour theme.

    Parameters
    ----------
    name : ``"dark"`` | ``"light"`` | ``"classic"``
    """
    get_settings().theme = name


def watermark(enabled: bool = True) -> None:
    """Enable or disable the TRADELY logo watermark on charts.

    Parameters
    ----------
    enabled : bool
        ``True`` to stamp the logo (default), ``False`` to omit it.
    """
    get_settings().watermark_enabled = enabled


def config(**kwargs) -> dict:
    """Batch-set global options. Returns the current settings as a dict.

    Accepted keyword arguments
    --------------------------
    terminal : str          — logging mode
    theme : str             — colour theme
    watermark : bool        — logo watermark on/off
    overwrite : bool        — allow overwriting existing files
    dpi : int               — output resolution (50–600)
    fig_size : tuple[int,int] — figure dimensions in inches
    cache_ttl : int         — data cache time-to-live in seconds

    Example
    -------
    >>> tc.config(theme="light", dpi=200, overwrite=True)
    """
    s = get_settings()
    dispatch = {
        "terminal":  lambda v: setattr(s, "terminal_mode", v),
        "theme":     lambda v: setattr(s, "theme", v),
        "watermark": lambda v: setattr(s, "watermark_enabled", v),
        "overwrite": lambda v: setattr(s, "overwrite", v),
        "dpi":       lambda v: setattr(s, "dpi", v),
        "fig_size":  lambda v: setattr(s, "fig_size", v),
        "cache_ttl": lambda v: setattr(s, "cache_ttl", v),
    }
    for key, value in kwargs.items():
        setter = dispatch.get(key)
        if setter is None:
            raise ConfigError(
                f"Unknown config key '{key}'. "
                f"Allowed: {', '.join(sorted(dispatch))}"
            )
        setter(value)

    return {
        "terminal": s.terminal_mode,
        "theme": s.theme,
        "watermark": s.watermark_enabled,
        "overwrite": s.overwrite,
        "dpi": s.dpi,
        "fig_size": s.fig_size,
        "cache_ttl": s.cache_ttl,
    }


# ── Charting ─────────────────────────────────────────────────────────────────

def chart(
    ticker: Union[str, list, tuple],
    duration: str = "1mo",
    chart_type: str = "candle",
    output_location: Optional[str] = None,
    output_name: Optional[str] = None,
    fmt: str = "png",
    indicators: Optional[list[str]] = None,
    show_volume: bool = True,
) -> Path:
    """Fetch market data and render a chart image.

    Parameters
    ----------
    ticker : str | list[str] | tuple[str, ...]
        Instrument symbol — ``"AAPL"``, ``"BTC-USD"``, ``"EURUSD=X"`` — **or**
        a list/tuple of symbols to be averaged into a single series, e.g.
        ``["AAPL", "MSFT", "AMZN"]``.  When a group is supplied every ticker
        is fetched independently and their OHLCV values are averaged across
        the overlapping trading dates before rendering.

        *Collision note:* Python resolves the ambiguity through types, not
        names.  ``"DNUT"`` (a string) is the Krispy Kreme ticker; a variable
        called ``DNUT`` that holds a list is simply passed as a list — the
        library checks ``isinstance``, not the variable name.
    duration : str
        ``"1d"`` ``"5d"`` ``"1mo"`` ``"3mo"`` ``"6mo"`` ``"1y"`` ``"2y"``
        ``"5y"`` ``"10y"`` ``"max"``
    chart_type : str
        ``"candle"`` ``"line"`` ``"ohlc"`` ``"area"`` ``"heikin_ashi"``
    output_location : str or None
        Directory. Defaults to cwd; created if missing.
    output_name : str or None
        Filename. Defaults to ``{TICKER}_{duration}_{type}.{fmt}``.
    fmt : str
        ``"png"`` ``"jpg"`` ``"svg"`` ``"pdf"`` ``"webp"``
    indicators : list[str] or None
        ``"sma"`` ``"ema"`` ``"bollinger"`` ``"vwap"`` ``"rsi"`` ``"macd"``
        ``"volume"``
    show_volume : bool
        Show volume subplot (default ``True``).

    Returns
    -------
    pathlib.Path
        Absolute path to the saved chart image.
    """
    return _get_engine().run(
        ticker=ticker, duration=duration, chart_type=chart_type,
        output_location=output_location, output_name=output_name,
        fmt=fmt, indicators=indicators, show_volume=show_volume,
    )


def compare(
    tickers: list[str],
    duration: str = "1mo",
    output_location: Optional[str] = None,
    output_name: Optional[str] = None,
    fmt: str = "png",
    normalise: bool = True,
) -> Path:
    """Overlay multiple tickers on a single chart for comparison.

    Parameters
    ----------
    tickers : list[str]
        2–8 ticker symbols to compare.
    duration : str
        Shared time span for all tickers.
    normalise : bool
        If ``True`` (default), show percentage change from period start.
        If ``False``, plot raw prices (useful when scales are similar).

    Returns
    -------
    pathlib.Path
    """
    return _get_engine().compare(
        tickers=tickers, duration=duration,
        output_location=output_location, output_name=output_name,
        fmt=fmt, normalise=normalise,
    )


def heatmap(
    tickers: list,
    duration: str = "1mo",
    output_location: Optional[str] = None,
    output_name: Optional[str] = None,
    fmt: str = "png",
) -> Path:
    """Render a performance heatmap for a group of tickers.

    Each ticker is represented as a coloured tile whose hue encodes the
    percentage change over *duration* — red for losses, green for gains.
    Designed to be used with ``tc.SECTOR_GROUPS`` but accepts any list.

    Parameters
    ----------
    tickers : list[str]
        2 or more ticker symbols, e.g. ``tc.SECTOR_GROUPS["mag7"]``.
    duration : str
        Time span shared by all tickers.
    output_location : str or None
        Directory. Defaults to cwd; created if missing.
    output_name : str or None
        Filename. Defaults to ``heatmap_{group}_{duration}.{fmt}``.
    fmt : str
        ``"png"`` ``"jpg"`` ``"svg"`` ``"pdf"`` ``"webp"``

    Returns
    -------
    pathlib.Path
        Absolute path to the saved heatmap image.

    Examples
    --------
    >>> tc.heatmap(tc.SECTOR_GROUPS["mag7"], "1mo")
    >>> tc.heatmap(tc.SECTOR_GROUPS["sp500_etfs"], "3mo", fmt="png")
    >>> tc.heatmap(["AAPL", "MSFT", "NVDA", "GOOGL"], "6mo")
    """
    return _get_engine().heatmap(
        tickers=tickers, duration=duration,
        output_location=output_location, output_name=output_name,
        fmt=fmt,
    )


def data(
    ticker: Union[str, list, tuple],
    duration: str = "1mo",
) -> pd.DataFrame:
    """Fetch raw OHLCV market data without rendering a chart.

    Parameters
    ----------
    ticker : str | list[str] | tuple[str, ...]
        A single symbol or a group of symbols to average.  See
        :func:`chart` for full details on group behaviour.
    duration : str

    Returns
    -------
    pandas.DataFrame
        Columns: Open, High, Low, Close, Volume.  DatetimeIndex.
        When a group is supplied the DataFrame contains the mean values
        across all tickers on their overlapping trading dates.
    """
    return _get_engine().fetch_data(ticker, duration)


def export(
    ticker: Union[str, list, tuple],
    duration: str = "1mo",
    fmt: str = "csv",
    output_location: Optional[str] = None,
    output_name: Optional[str] = None,
) -> Path:
    """Export market data to a file.

    Parameters
    ----------
    ticker : str | list[str] | tuple[str, ...]
        A single symbol or a group of symbols to average.  See
        :func:`chart` for full details on group behaviour.
        Averaged data is exported with a label such as
        ``AVG_AAPL_MSFT_AMZN_1mo.csv``.
    fmt : ``"csv"`` | ``"json"`` | ``"xlsx"``

    Returns
    -------
    pathlib.Path
    """
    return _get_engine().export(
        ticker=ticker, duration=duration, fmt=fmt,
        output_location=output_location, output_name=output_name,
    )


def clear_cache(disk: bool = False) -> None:
    """Flush the in-memory data cache.

    Parameters
    ----------
    disk : bool
        If ``True``, also delete all CSV files in the persistent disk store
        (the folder itself is kept).  Defaults to ``False``.
    """
    _get_engine().clear_cache()
    if disk:
        ds = get_settings().disk_store
        if ds is not None:
            ds.clear()


# ── Persistent store ─────────────────────────────────────────────────────────

def _is_store_path(s: str) -> bool:
    """Heuristic: does *s* look like a filesystem path rather than a ticker?"""
    p = Path(s).expanduser()
    if p.is_absolute():
        return True
    if s.startswith(".") or s.startswith("~"):
        return True
    if os.sep in s or "/" in s:
        return True
    if len(s) > 20:
        return True
    if p.is_dir():
        return True
    return False


def store(*args: Union[str, list, tuple], duration: str = "1mo") -> Path | None:
    """Set the data-store directory, or pre-fetch and persist tickers/groups.

    **Setting the store location** — pass a single filesystem path::

        tc.store("/data/myproject")
        tc.store(".")                  # current directory
        tc.store("~/tradechart_data")

    This creates ``<path>/tradechart_FetchData/`` and enables automatic
    disk persistence for every subsequent fetch (``chart()``, ``data()``,
    ``export()``, …).  Data already stored on disk is reused without hitting
    the network, even across Python sessions.

    **Pre-fetching tickers** — once a store path is set, pass any combination
    of individual symbols, named sector groups, or plain lists::

        tc.store("AAPL")                          # single ticker, default duration
        tc.store("AAPL", "MSFT", "NVDA", "3mo")  # three tickers for 3 months
        tc.store("mag7", "6mo")                   # named group → all 7 tickers
        tc.store(tc.SECTOR_GROUPS["tech"], "1y")  # list passed directly

    If the last positional argument is a valid duration string it is used as
    the fetch window; otherwise *duration* (default ``"1mo"``) applies.

    Named groups (``"mag7"``, ``"tech"``, ``"finance"``, …) are resolved via
    :data:`SECTOR_GROUPS` — each member ticker is fetched individually.

    Parameters
    ----------
    *args : str | list | tuple
        A single path string **or** any mix of ticker symbols, named sector
        group keys, and/or lists of tickers, optionally ending with a duration.
    duration : str
        Fallback duration when none is specified in *args*.
        ``"1d"`` ``"5d"`` ``"1mo"`` ``"3mo"`` ``"6mo"`` ``"1y"`` ``"2y"``
        ``"5y"`` ``"10y"`` ``"max"``

    Returns
    -------
    pathlib.Path or None
        The ``tradechart_FetchData`` folder path when setting the store;
        ``None`` when pre-fetching.

    Examples
    --------
    >>> import tradechart as tc
    >>> tc.store("/home/user/market_data")          # configure store
    >>> tc.store("AAPL", "MSFT", "1mo")             # pre-fetch two tickers
    >>> tc.store("mag7", "3mo")                     # pre-fetch Magnificent 7
    >>> tc.chart("AAPL", "1mo")                     # served from disk, no network
    """
    if not args:
        raise ConfigError("store() requires at least one argument.")

    # ── Case 1: set / change the store path ──────────────────────────────────
    if len(args) == 1 and isinstance(args[0], str) and _is_store_path(args[0]):
        path = Path(args[0]).expanduser().resolve()
        get_settings().set_store_path(path)
        store_dir = get_settings().disk_store.root  # type: ignore[union-attr]
        _log = _get_engine()._log  # type: ignore[attr-defined]
        _log.summary(f"✓ Data store set → {store_dir}")
        return store_dir

    # ── Case 2: pre-fetch tickers/groups ─────────────────────────────────────
    if get_settings().disk_store is None:
        raise ConfigError(
            "No store path configured. Call tc.store('/path/to/dir') first."
        )

    # Determine duration: if the last arg is a known duration string, use it.
    ticker_args: tuple
    if args and isinstance(args[-1], str) and args[-1] in VALID_DURATIONS:
        dur = args[-1]
        ticker_args = args[:-1]
    else:
        dur = duration
        ticker_args = args

    # Resolve all tickers (flatten lists, expand named groups).
    all_tickers: list[str] = []
    for arg in ticker_args:
        if isinstance(arg, (list, tuple)):
            all_tickers.extend(str(t) for t in arg)
        elif isinstance(arg, str):
            if arg in SECTOR_GROUPS:
                all_tickers.extend(SECTOR_GROUPS[arg])
            else:
                all_tickers.append(arg)

    if not all_tickers:
        raise ConfigError("store() received no recognisable ticker symbols.")

    engine = _get_engine()
    fetched: list[str] = []
    failed: list[str] = []
    for ticker in all_tickers:
        try:
            engine.fetch_data(ticker, dur)
            fetched.append(ticker)
        except Exception as exc:
            failed.append(f"{ticker}: {exc}")

    if failed:
        import warnings
        warnings.warn(
            f"store(): could not fetch {len(failed)} ticker(s):\n"
            + "\n".join(f"  • {e}" for e in failed),
            stacklevel=2,
        )

    engine._log.summary(  # type: ignore[attr-defined]
        f"✓ Stored {len(fetched)} ticker(s) for {dur} "
        f"→ {get_settings().disk_store.root}"  # type: ignore[union-attr]
    )
    return None
