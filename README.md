# TradeChart — Library Edition v2.2.1

**Python → Financial Charts**  
Generate production-quality candlestick, line, area, OHLC, Heikin-Ashi, and performance heatmap charts from code.  
Automatic multi-provider data fetching · persistent disk store · 7 technical indicators · 3 themes · PNG/SVG/PDF output · 14 built-in sector groups.

---

## Installation

```bash
pip install TradeChart
```

### Optional Extras

| Extra | Installs | Benefit |
|---|---|---|
| `TradeChart[tradingview]` | `tvDatafeed` | TradingView as a fallback data provider |
| `TradeChart[mplfinance]` | `mplfinance` | Higher-quality candlestick rendering |
| `TradeChart[xlsx]` | `openpyxl` | Excel `.xlsx` export support |
| `TradeChart[all]` | All of the above | Everything |

```bash
pip install TradeChart[all]
```

---

## Quick Start

```python
import tradechart as tc

tc.chart("AAPL", "1mo", "candle", indicators=["sma", "bollinger"])
```

---

## Persistent Data Store

`tc.store()` adds a two-level cache on top of the existing in-memory TTL cache: data fetched from any provider is written to a `tradechart_FetchData/` folder and reloaded automatically in future sessions, eliminating redundant network requests.

### Set the store location

Call `tc.store()` once with a filesystem path. The folder `tradechart_FetchData/` is created there automatically.

```python
import tradechart as tc

tc.store("/data/myproject")      # absolute path
tc.store(".")                    # current working directory
tc.store("~/market_data")        # tilde expansion supported
```

### Pre-fetch tickers and groups

After setting the path, call `tc.store()` again on subsequent lines listing any combination of individual ticker symbols, named sector group keys, or plain lists. An optional duration string as the last argument controls the fetch window (defaults to `"1mo"`).

```python
tc.store("AAPL")                           # single ticker, default duration (1mo)
tc.store("AAPL", "MSFT", "NVDA", "3mo")   # three tickers for 3 months
tc.store("mag7", "6mo")                    # named group — fetches all 7 tickers
tc.store("tech", "finance", "1y")          # two named groups for 1 year
tc.store(tc.SECTOR_GROUPS["crypto"], "3mo") # list passed directly
```

Any valid `SECTOR_GROUPS` key (`"mag7"`, `"tech"`, `"finance"`, `"energy"`, …) is expanded to its full ticker list automatically.

### How it works

Once a store path is configured, every call to `chart()`, `data()`, `export()`, `compare()`, or `heatmap()` uses a three-level lookup before touching the network:

1. **In-memory cache** — sub-millisecond, TTL-based (existing behaviour).
2. **Disk store (fresh)** — if the stored file is younger than the bar-resolution threshold, it is served as-is. No network call.
3. **Disk store (stale) + live fetch** — if the stored file is older than the threshold, the library fetches the current window from a live provider to get the missing bars, then **merges** those new rows on top of the stored history. Historical bars are never discarded or re-requested. The merged result is written back to disk and served.

The staleness threshold matches the resolution of the data so charts are never more than one bar behind:

| Duration | Bar resolution | Refreshes after |
|---|---|---|
| `"1d"`, `"5d"` | 5 / 15-min bars | 4 hours |
| `"1mo"`, `"3mo"`, `"6mo"` | Daily bars | 24 hours |
| `"1y"`, `"2y"`, `"5y"` | Weekly bars | 7 days |
| `"10y"`, `"max"` | Monthly bars | 30 days |

```python
tc.store("/data/myproject")
tc.store("AAPL", "MSFT", "mag7", "3mo")   # fetch once, write to disk

# Later — same session or a completely new one:
tc.chart("AAPL", "3mo")                   # served from disk, no network call
tc.data("MSFT", "3mo")                    # same

# After 24 hours (daily bars): only the new day's bar is fetched and merged
# in — the months of stored history are kept and reused as-is
tc.chart("AAPL", "3mo")                   # delta fetch + merge, then cached
```

### Clearing stored data

```python
tc.clear_cache()           # flush in-memory cache only (default)
tc.clear_cache(disk=True)  # also delete all CSV files in tradechart_FetchData/
```

### Store folder layout

```
/data/myproject/
└── tradechart_FetchData/
    ├── AAPL_3mo.csv
    ├── MSFT_3mo.csv
    ├── NVDA_3mo.csv
    └── ...
```

| Parameter | Type | Description |
|---|---|---|
| `*args` | `str \| list \| tuple` | A single path string **or** any mix of ticker symbols, named sector group keys, and/or lists — optionally ending with a duration string. |
| `duration` | `str` (keyword) | Fallback duration when none is provided in `*args`. Default `"1mo"`. |

**Returns:** the `tradechart_FetchData/` `Path` when setting the store; `None` when pre-fetching.

---

## Ticker Groups — Averaged Series

`tc.chart()`, `tc.data()`, and `tc.export()` accept a **list or tuple of ticker symbols** in addition to a single string. When a group is supplied the library:

1. Fetches each ticker independently (using the normal provider fallback chain).
2. Aligns all series to their **overlapping trading dates**.
3. Computes the **column-wise mean** of Open, High, Low, Close, and Volume across all tickers.
4. Renders or returns that single averaged series, labelled `AVG(AAPL,MSFT,AMZN)`.

```python
import tradechart as tc

tech = ["AAPL", "MSFT", "AMZN"]

# Chart the average of the three — produces a single line/candle series
tc.chart(tech, "3mo", "line")

# Fetch the averaged DataFrame for custom analysis
df = tc.data(tech, "6mo")

# Export the averaged data to CSV
tc.export(tech, "1y", fmt="csv", output_location="./exports")
```

### Collision note — variable names vs ticker symbols

There is no ambiguity between a variable named after a real ticker (e.g. `DNUT`) and the ticker string `"DNUT"`. Python's type system handles this automatically:

```python
# This passes the string "DNUT" → Krispy Kreme ticker
tc.chart("DNUT", "1mo")

# This passes the list held by the variable DNUT → averaged group
DNUT = ["AAPL", "MSFT"]
tc.chart(DNUT, "1mo")   # library sees a list, not the name "DNUT"
```

The library inspects `isinstance(ticker, (list, tuple))` — it never looks at variable names. Any list or tuple is a group; any string is a single ticker.

### Behaviour on partial failure

If one or more tickers in the group fail to fetch data, they are **skipped with a warning** and the remaining tickers are averaged. If **all** tickers fail, or if the surviving tickers share **no common trading dates**, a `DataFetchError` is raised with a clear explanation.

---

## API Overview

| Function | Description |
|---|---|
| `tc.terminal(mode)` | Set console logging verbosity |
| `tc.theme(name)` | Set chart colour theme |
| `tc.watermark(enabled)` | Toggle the TRADELY logo watermark |
| `tc.config(**kwargs)` | Batch-set multiple global options at once |
| `tc.store(path)` | Set persistent data-store directory |
| `tc.store(ticker, ...)` | Pre-fetch and persist tickers / groups |
| `tc.chart(...)` | Fetch data and render a chart image |
| `tc.compare(...)` | Overlay multiple tickers on one chart |
| `tc.heatmap(...)` | Render a performance heatmap for a ticker group |
| `tc.data(...)` | Fetch raw OHLCV data as a DataFrame |
| `tc.export(...)` | Export market data to CSV / JSON / XLSX |
| `tc.clear_cache(disk=False)` | Flush in-memory cache; optionally wipe disk store |
| `tc.SECTOR_GROUPS` | Dict of 14 pre-defined ticker lists (sectors, indices, crypto, …) |

---

## `tc.chart()` — Render a Chart

Fetches market data and saves a chart image to disk. Returns the `pathlib.Path` of the saved file.

```python
path = tc.chart(
    "AAPL",
    duration="3mo",
    chart_type="candle",
    indicators=["sma", "ema", "rsi", "macd"],
    show_volume=True,
    fmt="png",
    output_location="./charts",
    output_name="apple_q1.png",
)
print(f"Saved → {path}")
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `ticker` | `str \| list[str] \| tuple[str, ...]` | Yes | — | Instrument symbol such as `"AAPL"`, `"BTC-USD"`, `"EURUSD=X"`, `"^GSPC"` — **or** a list/tuple of symbols to average (see [Ticker Groups](#ticker-groups--averaged-series)). |
| `duration` | `str` | No | `"1mo"` | Time span of the chart. See [Durations](#durations). |
| `chart_type` | `str` | No | `"candle"` | Chart style. One of: `"candle"`, `"line"`, `"ohlc"`, `"area"`, `"heikin_ashi"`. |
| `output_location` | `str \| None` | No | Current working directory | Directory to save the file. Created automatically if it does not exist. |
| `output_name` | `str \| None` | No | `{TICKER}_{duration}_{type}.{fmt}` | Custom filename. Extension is added automatically if omitted. |
| `fmt` | `str` | No | `"png"` | Output format. One of: `"png"`, `"jpg"`, `"svg"`, `"pdf"`, `"webp"`. |
| `indicators` | `list[str] \| None` | No | `None` | Technical indicators to overlay or add as sub-panels. See [Indicators](#indicators). |
| `show_volume` | `bool` | No | `True` | Whether to show a volume sub-panel beneath the price chart. Has no effect on `"line"` and `"area"` chart types. |

### Chart Types

| Value | Description |
|---|---|
| `"candle"` | Candlestick chart with open/high/low/close bodies and wicks |
| `"heikin_ashi"` | Heikin-Ashi smoothed candles (OHLC converted before rendering; source data unchanged) |
| `"ohlc"` | OHLC bar chart — vertical high/low line with left (open) and right (close) ticks |
| `"line"` | Close price line chart |
| `"area"` | Close price line chart with shaded fill beneath the curve |

---

## `tc.compare()` — Multi-Ticker Overlay

Plots multiple tickers on a single chart for performance comparison. Returns the `pathlib.Path` of the saved file.

```python
path = tc.compare(
    ["AAPL", "MSFT", "GOOG", "AMZN"],
    duration="6mo",
    normalise=True,
    fmt="png",
    output_location="./charts",
    output_name="big_tech_6mo.png",
)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `tickers` | `list[str]` | Yes | — | 2–8 ticker symbols to overlay on the same chart. Each is fetched independently using the provider fallback chain. |
| `duration` | `str` | No | `"1mo"` | Shared time span applied to every ticker. See [Durations](#durations). |
| `normalise` | `bool` | No | `True` | `True` — plot percentage change from the first bar of the period (recommended when tickers have different price scales). `False` — plot raw closing prices. |
| `output_location` | `str \| None` | No | Current working directory | Output directory. Created if missing. |
| `output_name` | `str \| None` | No | `compare_{tickers}_{duration}.{fmt}` | Custom filename. |
| `fmt` | `str` | No | `"png"` | Output format: `"png"`, `"jpg"`, `"svg"`, `"pdf"`, `"webp"`. |

---

## `tc.heatmap()` — Performance Heatmap

Renders a **market-cap weighted treemap** — one tile per ticker — where tile **size** is proportional to market capitalisation and tile **colour** encodes percentage change over the requested duration. Red = loss, green = gain. Designed for sector snapshots and portfolio overviews, matching the style of professional tools like Finviz and Bloomberg.

```python
import tradechart as tc

# Magnificent 7 over the last month
tc.heatmap(tc.SECTOR_GROUPS["mag7"], "1mo")

# All S&P 500 sector ETFs over 3 months
tc.heatmap(tc.SECTOR_GROUPS["sp500_etfs"], "3mo")

# Custom list
tc.heatmap(["AAPL", "MSFT", "NVDA", "GOOGL", "META"], "6mo", fmt="png")
```

Each tile shows:
- **Ticker symbol** (bold)
- **± % change** over the duration
- **Last closing price**

Tile sizes use a **squarified treemap** algorithm to minimise wasted space while keeping aspect ratios close to square. Market-cap data is fetched automatically via yfinance. When market-cap data is unavailable (indices, futures, commodities), the renderer falls back to an equal-area grid automatically. The colour scale is symmetrically ranged to the largest move in the group. A colourbar legend is included.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `tickers` | `list[str]` | Yes | — | 2 or more ticker symbols. Use `tc.SECTOR_GROUPS["key"]` or any custom list. |
| `duration` | `str` | No | `"1mo"` | Time span applied to every ticker. See [Durations](#durations). |
| `output_location` | `str \| None` | No | Current working directory | Output directory. Created if missing. |
| `output_name` | `str \| None` | No | `heatmap_{group}_{duration}.{fmt}` | Custom filename. |
| `fmt` | `str` | No | `"png"` | Output format: `"png"`, `"jpg"`, `"svg"`, `"pdf"`, `"webp"`. |

**Returns:** `pathlib.Path` of the saved heatmap image.

---

## `tc.SECTOR_GROUPS` — Pre-defined Ticker Lists

A dictionary of curated ticker groups ready to pass into `tc.heatmap()`, `tc.compare()`, `tc.chart()`, `tc.store()`, or `tc.export()`.

```python
import tradechart as tc

print(list(tc.SECTOR_GROUPS.keys()))
# ['mag7', 'sp500_etfs', 'tech', 'finance', 'energy', 'healthcare',
#  'consumer_disc', 'consumer_stap', 'industrials', 'realestate',
#  'utilities', 'crypto', 'indices', 'commodities']

# Use as a heatmap input
tc.heatmap(tc.SECTOR_GROUPS["crypto"], "1mo")

# Use as a compare input (max 8 tickers)
tc.compare(tc.SECTOR_GROUPS["sp500_etfs"][:8], "3mo")

# Use as an averaged chart input
tc.chart(tc.SECTOR_GROUPS["mag7"], "6mo", "line")
```

| Key | Tickers |
|---|---|
| `"mag7"` | AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA |
| `"sp500_etfs"` | XLK, XLF, XLE, XLV, XLY, XLI, XLB, XLU, XLRE, XLC, XLP |
| `"tech"` | AAPL, MSFT, NVDA, AMD, INTC, ORCL, CRM, ADBE, QCOM, TXN |
| `"finance"` | JPM, BAC, GS, MS, WFC, C, BLK, AXP, V, MA |
| `"energy"` | XOM, CVX, COP, EOG, MPC, VLO, PSX, OXY, HES, SLB |
| `"healthcare"` | JNJ, LLY, UNH, ABBV, MRK, ABT, TMO, PFE, DHR, BMY |
| `"consumer_disc"` | AMZN, TSLA, HD, MCD, NKE, SBUX, LOW, TGT, BKNG, GM |
| `"consumer_stap"` | WMT, PG, KO, PEP, COST, PM, MO, CL, GIS, KHC |
| `"industrials"` | CAT, HON, UPS, BA, GE, MMM, RTX, LMT, DE, EMR |
| `"realestate"` | AMT, PLD, EQIX, SPG, CCI, PSA, DLR, O, WELL, AVB |
| `"utilities"` | NEE, DUK, SO, D, AEP, EXC, SRE, PCG, ED, ETR |
| `"crypto"` | BTC-USD, ETH-USD, BNB-USD, SOL-USD, ADA-USD, XRP-USD, DOGE-USD, AVAX-USD |
| `"indices"` | ^GSPC, ^DJI, ^IXIC, ^RUT, ^FTSE, ^N225, ^HSI, ^GDAXI |
| `"commodities"` | GC=F, SI=F, CL=F, NG=F, HG=F, ZC=F, ZS=F, PL=F |

---

## `tc.data()` — Fetch Raw OHLCV Data

Fetches market data and returns it as a `pandas.DataFrame` without rendering any chart. Useful for further analysis or custom plotting.

```python
df = tc.data("TSLA", "3mo")
print(df.head())
#            Open    High     Low   Close      Volume
# Date
# 2024-01-02  248.5  251.3  245.0  249.8  120000000
# ...
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `ticker` | `str \| list[str] \| tuple[str, ...]` | Yes | — | Instrument symbol or a group to average (see [Ticker Groups](#ticker-groups--averaged-series)). |
| `duration` | `str` | No | `"1mo"` | Time span. See [Durations](#durations). |

**Returns:** `pandas.DataFrame` with a `DatetimeIndex` and columns `Open`, `High`, `Low`, `Close`, `Volume`.  
Data is cleaned (NaN rows dropped, Volume NaN → 0) and downsampled to a maximum of 2,000 rows.

---

## `tc.export()` — Export Data to File

Fetches market data and writes it to a file. Returns the `pathlib.Path` of the saved file.

```python
# CSV
path = tc.export("AAPL", "1y", fmt="csv", output_location="./exports")

# JSON
path = tc.export("MSFT", "6mo", fmt="json", output_name="msft_6mo.json")

# Excel
path = tc.export("BTC-USD", "3mo", fmt="xlsx")  # requires TradeChart[xlsx]
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `ticker` | `str \| list[str] \| tuple[str, ...]` | Yes | — | Instrument symbol or a group to average (see [Ticker Groups](#ticker-groups--averaged-series)). |
| `duration` | `str` | No | `"1mo"` | Time span. See [Durations](#durations). |
| `fmt` | `str` | No | `"csv"` | Export format: `"csv"`, `"json"`, or `"xlsx"`. Excel export requires `pip install TradeChart[xlsx]`. |
| `output_location` | `str \| None` | No | Current working directory | Output directory. Created if missing. |
| `output_name` | `str \| None` | No | `{TICKER}_{duration}.{fmt}` | Custom filename. |

---

## `tc.config()` — Batch Settings

Set multiple global options in a single call. Returns a `dict` snapshot of all current settings.

```python
tc.config(
    terminal="full",
    theme="light",
    dpi=200,
    overwrite=True,
    fig_size=(16, 9),
    cache_ttl=600,
    watermark=False,
)
```

| Key | Type | Default | Valid values / range | Description |
|---|---|---|---|---|
| `terminal` | `str` | `"on_done"` | `"full"`, `"on_done"`, `"none"` | Console logging verbosity. See [Terminal Modes](#terminal-modes). |
| `theme` | `str` | `"dark"` | `"dark"`, `"light"`, `"classic"` | Chart colour theme. See [Themes](#themes). |
| `watermark` | `bool` | `True` | `True`, `False` | Show or hide the TRADELY logo in the bottom-left corner of charts. |
| `overwrite` | `bool` | `False` | `True`, `False` | `False` — append `_1`, `_2`, … to the filename if it already exists. `True` — overwrite the existing file silently. |
| `dpi` | `int` | `150` | `50`–`600` | Output resolution in dots per inch. Higher values produce larger, sharper files. |
| `fig_size` | `tuple[int, int]` | `(14, 7)` | Any valid `(width, height)` in inches | Matplotlib figure size. Increase for wide monitors or presentations. |
| `cache_ttl` | `int` | `300` | Any positive integer (seconds) | How long fetched data is kept in memory. `0` effectively disables caching. |

---

## `tc.terminal()` — Logging Verbosity

```python
tc.terminal("full")     # Show every step
tc.terminal("on_done")  # Show summary after completion (default)
tc.terminal("none")     # Complete silence — no output at all
```

## Terminal Modes

| Mode | What prints | Best for |
|---|---|---|
| `"full"` | Every internal step, provider attempts, row counts, file paths | Debugging and development |
| `"on_done"` | One-line summary after each operation completes | Normal interactive use |
| `"none"` | Nothing — completely silent | Production scripts, CI pipelines, bots |

---

## `tc.theme()` — Chart Colour Theme

```python
tc.theme("dark")     # Default
tc.theme("light")
tc.theme("classic")
```

## Themes

| Name | Background | Candle colours | Spine |
|---|---|---|---|
| `"dark"` | `#1e1e2f` (dark navy) | Green `#26a69a` / Red `#ef5350` | Hidden |
| `"light"` | `#ffffff` (white) | Green `#26a69a` / Red `#ef5350` | Hidden |
| `"classic"` | `#f5f5dc` (parchment) | Dark green `#2e7d32` / Dark red `#c62828` | Visible |

---

## `tc.watermark()` — Logo Watermark

```python
tc.watermark(True)   # Enable (default)
tc.watermark(False)  # Disable
```

The TRADELY logo is stamped in the bottom-left corner of every chart by default. The logo is downloaded once from the CDN and cached locally at `~/.tradechart/cache/tradely_logo.png` for all subsequent renders.

---

## `tc.clear_cache()` — Flush Data Cache

```python
tc.clear_cache()            # flush in-memory cache only
tc.clear_cache(disk=True)   # also wipe all CSVs in tradechart_FetchData/
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `disk` | `bool` | `False` | When `True`, deletes all CSV files in the disk store (the folder is kept). Has no effect if no store path has been set. |

Clears in-memory cached market data, forcing the next fetch to check the disk store (or go to the network if no store is configured). Useful during live market hours when TTL has not yet expired but you need a fresh quote.

---

## Durations

| Value | Period | Bar Resolution |
|---|---|---|
| `"1d"` | 1 day | 5-minute bars |
| `"5d"` | 5 days | 15-minute bars |
| `"1mo"` | 1 month | Daily bars |
| `"3mo"` | 3 months | Daily bars |
| `"6mo"` | 6 months | Daily bars |
| `"1y"` | 1 year | Weekly bars |
| `"2y"` | 2 years | Weekly bars |
| `"5y"` | 5 years | Weekly bars |
| `"10y"` | 10 years | Monthly bars |
| `"max"` | All available history | Monthly bars |

---

## Indicators

Pass any combination as a list to `tc.chart(indicators=[...])`.

| Name | Panel | Default Parameters | Description |
|---|---|---|---|
| `"sma"` | Price overlay | Period 20 | Simple Moving Average of the close price |
| `"ema"` | Price overlay | Period 20 | Exponential Moving Average of the close price |
| `"bollinger"` | Price overlay | Period 20, 2σ | Bollinger Bands — upper, middle (SMA), and lower band plotted as dashed lines with a shaded band |
| `"vwap"` | Price overlay | — | Volume-Weighted Average Price — cumulative from the first bar of the dataset |
| `"rsi"` | Sub-panel (0–100) | Period 14 | Relative Strength Index with overbought (70) and oversold (30) reference lines |
| `"macd"` | Sub-panel | Fast 12, Slow 26, Signal 9 | MACD line, signal line, and histogram |
| `"volume"` | Sub-panel | — | Volume bars coloured by bar direction. Equivalent to `show_volume=True` when used as an indicator. |

**Example — multiple indicators:**

```python
tc.chart(
    "NVDA",
    duration="6mo",
    chart_type="candle",
    indicators=["ema", "bollinger", "rsi", "macd"],
    show_volume=True,
)
```

---

## Data Providers

TradeChart tries providers in priority order and falls back automatically on failure or empty data.

| Priority | Provider | Requires | Notes |
|---|---|---|---|
| 0 | **Disk store** | `tc.store(path)` called once | Served from local CSV when fresh. When stale, only the missing bars are fetched from a live provider and merged on top — historical rows are never re-requested. |
| 1 | **yfinance** | Included by default | Primary live source. Covers stocks, ETFs, indices, crypto, forex. |
| 2 | **TradingView** | `pip install TradeChart[tradingview]` | Tried if yfinance returns empty or fails. Attempts multiple exchanges automatically (`NASDAQ`, `NYSE`, `AMEX`, `CRYPTO`, `FX`). |
| 3 | **Stooq** | Nothing — free CSV endpoint | Final fallback. No API key required. Duration mapped to a rolling date range. |

If all live providers fail and no disk data exists, a `DataFetchError` is raised with a list of each provider's error message.

---

## Notes

**Persistent disk store**  
When `tc.store()` is configured, every successful live fetch is written to `tradechart_FetchData/` as a CSV file. On subsequent requests the library checks whether the stored data is fresh enough (based on bar resolution — 24 hours for daily bars, 4 hours for intraday, etc.). If fresh, it is served directly with no network call. If stale, only the most recent bars are fetched from a live provider and merged on top of the stored history — historical rows are never discarded or re-fetched. Use `tc.clear_cache(disk=True)` to wipe stored files and force a full re-fetch.

**In-memory caching**  
Fetched data is also cached in-memory for `cache_ttl` seconds (default 300 s / 5 minutes). All subsequent calls with the same ticker and duration within that window are served from the memory cache. Call `tc.clear_cache()` to force re-evaluation (disk store is still checked before going to the network). Set `tc.config(cache_ttl=0)` to disable the memory cache entirely.

**File collision handling**  
By default (`overwrite=False`), TradeChart appends a counter to avoid overwriting existing files: `chart.png` → `chart_1.png` → `chart_2.png`. Set `tc.config(overwrite=True)` to overwrite silently.

**Watermark**  
The logo PNG is downloaded once from the TRADELY CDN and stored at `~/.tradechart/cache/tradely_logo.png`. Subsequent renders use the local file. Disable with `tc.watermark(False)` or `tc.config(watermark=False)`.

**Thread safety**  
The global settings singleton and engine initialisation are protected by locks. `tc.chart()` can be called concurrently from multiple threads (e.g. a Discord bot handling simultaneous requests).

**Heikin-Ashi**  
The `"heikin_ashi"` chart type converts standard OHLC data to Heikin-Ashi candles during rendering only. The cached source data and any DataFrame returned by `tc.data()` are never modified.

**mplfinance**  
When `mplfinance` is installed (`pip install TradeChart[mplfinance]`), candlestick and Heikin-Ashi charts use it for higher-quality rendering. Otherwise a pure-matplotlib fallback is used automatically — no configuration required.

**Output resolution**  
Default DPI is 150, producing a ~2100 × 1050 px image at the default figure size. Increase with `tc.config(dpi=300)` for print-quality output.

---

## Error Handling

All TradeChart exceptions inherit from `TradeChartError`.

| Exception | Raised when |
|---|---|
| `DataFetchError` | All configured providers fail to return data for the requested ticker/duration |
| `InvalidTickerError` | The ticker string fails validation (too long, invalid characters) |
| `RenderError` | Chart rendering fails (e.g. empty dataset after cleaning) |
| `OutputError` | The chart cannot be saved (e.g. permission denied) |
| `ConfigError` | An unknown key is passed to `tc.config()`, or `tc.store()` is called with tickers before a path is set |

```python
import tradechart as tc
from tradechart import DataFetchError, RenderError

try:
    tc.chart("INVALID!!!", "1mo")
except DataFetchError as e:
    print(f"Data error: {e}")
except RenderError as e:
    print(f"Render error: {e}")
```

---

## Example Charts
<img width="2081" height="1039" alt="image" src="https://github.com/user-attachments/assets/b93f79e6-a135-4de8-993d-ee13071fe791" />
<img width="2081" height="1039" alt="image" src="https://github.com/user-attachments/assets/b0755b35-b21c-4b27-8faa-c57e13892dad" />

---

## Further Details

- Documentation: [doc.tradely.dev](https://doc.tradely.dev)
- PyPI: [pypi.org/project/TradeChart](https://pypi.org/project/TradeChart/)
- Source: [github.com/techareaone/TradeChart](https://github.com/techareaone/TradeChart)
