"""Fallback provider — TradingView via *tvDatafeed*."""

from __future__ import annotations

import pandas as pd

from tradechart.data.models import MarketData
from tradechart.data.provider_base import BaseProvider
from tradechart.config.logger import get_logger

_DURATION_MAP: dict[str, tuple[int, str]] = {
    "1d":   (78,   "in_5_minute"),
    "5d":   (130,  "in_15_minute"),
    "1mo":  (22,   "in_daily"),
    "3mo":  (66,   "in_daily"),
    "6mo":  (130,  "in_daily"),
    "1y":   (52,   "in_weekly"),
    "2y":   (104,  "in_weekly"),
    "5y":   (260,  "in_weekly"),
    "10y":  (120,  "in_monthly"),
    "max":  (240,  "in_monthly"),
}


class TradingViewProvider(BaseProvider):

    @property
    def name(self) -> str:
        return "TradingView"

    def fetch(self, ticker: str, duration: str) -> MarketData:
        log = get_logger()
        from tradechart.utils.install import ensure_package
        ensure_package("tvDatafeed")
        from tvDatafeed import TvDatafeed, Interval

        n_bars, interval_name = _DURATION_MAP.get(duration, (22, "in_daily"))
        interval = getattr(Interval, interval_name, Interval.in_daily)
        log.detail("TradingView: fetching %s  bars=%d  interval=%s", ticker, n_bars, interval_name)

        tv = TvDatafeed()
        exchanges_to_try = ["", "NASDAQ", "NYSE", "AMEX", "CRYPTO", "FX"]
        df: pd.DataFrame | None = None

        for exchange in exchanges_to_try:
            try:
                kwargs: dict = {"symbol": ticker, "interval": interval, "n_bars": n_bars}
                if exchange:
                    kwargs["exchange"] = exchange
                df = tv.get_hist(**kwargs)
                if df is not None and not df.empty:
                    log.detail("TradingView: found data on exchange=%s", exchange or "auto")
                    break
            except Exception:
                continue

        if df is None or df.empty:
            raise ValueError(f"TradingView returned no data for '{ticker}'")

        rename = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
        df = df.rename(columns=rename)
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        df = df[keep]

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return MarketData(ticker=ticker, duration=duration, provider=self.name, df=df)
