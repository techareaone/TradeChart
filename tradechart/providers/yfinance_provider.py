"""Primary data provider — wraps the *yfinance* library."""

from __future__ import annotations

from tradechart.data.models import MarketData, DURATION_RESOLUTION_MAP
from tradechart.data.provider_base import BaseProvider
from tradechart.config.logger import get_logger


class YFinanceProvider(BaseProvider):

    @property
    def name(self) -> str:
        return "yfinance"

    def fetch(self, ticker: str, duration: str) -> MarketData:
        log = get_logger()
        from tradechart.utils.install import ensure_package
        ensure_package("yfinance")
        import yfinance as yf

        period, interval = DURATION_RESOLUTION_MAP.get(duration, ("1mo", "1d"))
        log.detail("yfinance: downloading %s  period=%s  interval=%s", ticker, period, interval)

        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval=interval)

        if df.empty:
            raise ValueError(f"yfinance returned no data for '{ticker}'")

        col_map = {"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"}
        df = df.rename(columns=col_map)[list(col_map.values())]

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return MarketData(ticker=ticker, duration=duration, provider=self.name, df=df)
