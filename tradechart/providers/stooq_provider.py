"""Tertiary fallback — Stooq free CSV endpoint (no API key required)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd

from tradechart.data.models import MarketData
from tradechart.data.provider_base import BaseProvider
from tradechart.config.logger import get_logger

_DAYS_MAP: dict[str, int] = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 7300,
}

_STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={d1}&d2={d2}&i=d"


class StooqProvider(BaseProvider):

    @property
    def name(self) -> str:
        return "Stooq"

    def fetch(self, ticker: str, duration: str) -> MarketData:
        log = get_logger()
        import urllib.request

        days = _DAYS_MAP.get(duration, 30)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        symbol = ticker.lower().replace("/", "")
        url = _STOOQ_URL.format(
            symbol=symbol,
            d1=start.strftime("%Y%m%d"),
            d2=end.strftime("%Y%m%d"),
        )
        log.detail("Stooq: GET %s", url)

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TradeChart/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8")
        except Exception as exc:
            raise ConnectionError(f"Stooq request failed: {exc}") from exc

        if not raw.strip() or "No data" in raw:
            raise ValueError(f"Stooq returned no data for '{ticker}'")

        df = pd.read_csv(StringIO(raw), parse_dates=["Date"], index_col="Date")
        if "Volume" not in df.columns:
            df["Volume"] = 0
        keep = ["Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in keep if c in df.columns]]

        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return MarketData(ticker=ticker, duration=duration, provider=self.name, df=df)
