"""Pre-defined ticker groups for common market segments.

Usage
-----
>>> import tradechart as tc
>>> tc.heatmap(tc.SECTOR_GROUPS["mag7"], "1mo")
>>> tc.heatmap(tc.SECTOR_GROUPS["tech"], "3mo")
>>> tc.compare(tc.SECTOR_GROUPS["sp500_etfs"], "6mo")
"""

from __future__ import annotations

SECTOR_GROUPS: dict[str, list[str]] = {
    # ── Mega-cap tech (Magnificent 7) ─────────────────────────────────────────
    "mag7": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],

    # ── S&P 500 sector ETFs ───────────────────────────────────────────────────
    "sp500_etfs": [
        "XLK",   # Technology
        "XLF",   # Financials
        "XLE",   # Energy
        "XLV",   # Health Care
        "XLY",   # Consumer Discretionary
        "XLI",   # Industrials
        "XLB",   # Materials
        "XLU",   # Utilities
        "XLRE",  # Real Estate
        "XLC",   # Communication Services
        "XLP",   # Consumer Staples
    ],

    # ── Technology ────────────────────────────────────────────────────────────
    "tech": [
        "AAPL", "MSFT", "NVDA", "AMD", "INTC",
        "ORCL", "CRM", "ADBE", "QCOM", "TXN",
    ],

    # ── Financials ───────────────────────────────────────────────────────────
    "finance": ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "AXP", "V", "MA"],

    # ── Energy ───────────────────────────────────────────────────────────────
    "energy": [
        "XOM", "CVX", "COP", "EOG", "MPC",
        "VLO", "PSX", "OXY", "HES", "SLB",
    ],

    # ── Health Care ──────────────────────────────────────────────────────────
    "healthcare": [
        "JNJ", "LLY", "UNH", "ABBV", "MRK",
        "ABT", "TMO", "PFE", "DHR", "BMY",
    ],

    # ── Consumer Discretionary ───────────────────────────────────────────────
    "consumer_disc": [
        "AMZN", "TSLA", "HD", "MCD", "NKE",
        "SBUX", "LOW", "TGT", "BKNG", "GM",
    ],

    # ── Consumer Staples ─────────────────────────────────────────────────────
    "consumer_stap": [
        "WMT", "PG", "KO", "PEP", "COST",
        "PM", "MO", "CL", "GIS", "KHC",
    ],

    # ── Industrials ──────────────────────────────────────────────────────────
    "industrials": [
        "CAT", "HON", "UPS", "BA", "GE",
        "MMM", "RTX", "LMT", "DE", "EMR",
    ],

    # ── Real Estate ──────────────────────────────────────────────────────────
    "realestate": [
        "AMT", "PLD", "EQIX", "SPG", "CCI",
        "PSA", "DLR", "O", "WELL", "AVB",
    ],

    # ── Utilities ────────────────────────────────────────────────────────────
    "utilities": [
        "NEE", "DUK", "SO", "D", "AEP",
        "EXC", "SRE", "PCG", "ED", "ETR",
    ],

    # ── Crypto ───────────────────────────────────────────────────────────────
    "crypto": [
        "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD",
        "ADA-USD", "XRP-USD", "DOGE-USD", "AVAX-USD",
    ],

    # ── Major indices ─────────────────────────────────────────────────────────
    "indices": [
        "^GSPC",   # S&P 500
        "^DJI",    # Dow Jones
        "^IXIC",   # NASDAQ Composite
        "^RUT",    # Russell 2000
        "^FTSE",   # FTSE 100
        "^N225",   # Nikkei 225
        "^HSI",    # Hang Seng
        "^GDAXI",  # DAX
    ],

    # ── Commodities (futures) ─────────────────────────────────────────────────
    "commodities": [
        "GC=F",  # Gold
        "SI=F",  # Silver
        "CL=F",  # Crude Oil (WTI)
        "NG=F",  # Natural Gas
        "HG=F",  # Copper
        "ZC=F",  # Corn
        "ZS=F",  # Soybeans
        "PL=F",  # Platinum
    ],
}
