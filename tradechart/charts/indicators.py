"""Technical indicator computations added to a DataFrame in-place."""

from __future__ import annotations

import pandas as pd


def add_sma(df: pd.DataFrame, period: int = 20) -> None:
    """Simple Moving Average on Close."""
    df[f"SMA_{period}"] = df["Close"].rolling(window=period).mean()


def add_ema(df: pd.DataFrame, period: int = 20) -> None:
    """Exponential Moving Average on Close."""
    df[f"EMA_{period}"] = df["Close"].ewm(span=period, adjust=False).mean()


def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> None:
    """Bollinger Bands (upper, middle, lower)."""
    sma = df["Close"].rolling(window=period).mean()
    std = df["Close"].rolling(window=period).std()
    df["BB_Upper"] = sma + std_dev * std
    df["BB_Middle"] = sma
    df["BB_Lower"] = sma - std_dev * std


def add_vwap(df: pd.DataFrame) -> None:
    """Volume-Weighted Average Price (resets each day for intraday data)."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (typical * df["Volume"]).cumsum()
    cum_vol = df["Volume"].cumsum()
    df["VWAP"] = cum_tp_vol / cum_vol.replace(0, float("nan"))


def add_rsi(df: pd.DataFrame, period: int = 14) -> None:
    """Relative Strength Index (0–100)."""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["RSI"] = 100 - (100 / (1 + rs))


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> None:
    """MACD line, signal line, and histogram."""
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    df["MACD"] = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]


# Dispatcher
_INDICATOR_FNS: dict[str, callable] = {
    "sma": add_sma,
    "ema": add_ema,
    "bollinger": add_bollinger,
    "vwap": add_vwap,
    "rsi": add_rsi,
    "macd": add_macd,
}


def apply_indicators(df: pd.DataFrame, indicators: list[str]) -> None:
    """Apply each named indicator to *df* in-place."""
    for name in indicators:
        fn = _INDICATOR_FNS.get(name)
        if fn is not None:
            fn(df)
