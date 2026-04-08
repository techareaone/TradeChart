#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeChartBot: Lightweight Discord bot for financial charts.

Permissions model (simple):
  - Guild owner + Discord Administrators: always have full access (mod).
  - Mod roles: can use all commands including /clearcache.
  - User roles: can use /chart, /compare, and /heatmap only.
  - If NO roles are configured, everyone can use everything.
  - Status (live/off) is toggled via /status (mod-only) or by editing JSON directly.

Per-guild configs are fully isolated; no cross-guild state leaks.
"""

import os
import shutil
import sys
import asyncio
import json
import re
import signal
import tempfile
from pathlib import Path

import discord
from discord import app_commands

import tradechart as tc

# ============================================================
# CUSTOM EMOJI STRINGS (Discord server-specific IDs)
# Used only inside message strings sent to Discord, never as
# Python source literals, so encoding is irrelevant.
# ============================================================

EMOJI_GREEN  = "<:green:1491137227277729933>"
EMOJI_RED    = "<:red:1491137225302347776>"
EMOJI_YELLOW = "<:yellow:1491137224299774085>"

# ============================================================
# PATHS & CONFIG
# ============================================================

SCRIPT_DIR  = Path(__file__).parent.resolve()
DATA_DIR    = SCRIPT_DIR / "TradeChartBot_Data"
CONFIG_PATH = DATA_DIR / "config.env"
PERMS_FILE  = DATA_DIR / "guild_permissions.json"

DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = (
    "DISCORD_TOKEN=\n"
    "GUILD_ID=\n"
    "THEME=dark\n"
    "TERMINAL=none\n"
    "WATERMARK=True\n"
    "MAX_CONCURRENT=2\n"
    "MAX_QUEUE_SIZE=20\n"
)


def ensure_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG, encoding="ascii")
        print("Created config.env - fill in DISCORD_TOKEN and restart.")
        sys.exit(0)


def load_config() -> None:
    # errors='replace' prevents a mis-encoded config file from crashing the
    # bot with a UnicodeDecodeError before any useful output is produced.
    raw = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if "#" in v:
            v = v[:v.index("#")].strip()
        if v:
            os.environ[k] = v


ensure_config()
load_config()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    print("Missing DISCORD_TOKEN in config.env")
    sys.exit(1)

GUILD_ID_RAW = os.getenv("GUILD_ID", "").strip()
GUILD_ID: int | None = int(GUILD_ID_RAW) if GUILD_ID_RAW.isdigit() else None

MAX_CONCURRENT = max(1, int(os.getenv("MAX_CONCURRENT", "2")))
MAX_QUEUE_SIZE = max(1, int(os.getenv("MAX_QUEUE_SIZE", "20")))

tc.theme(os.getenv("THEME", "dark"))
tc.terminal(os.getenv("TERMINAL", "none"))
tc.watermark(os.getenv("WATERMARK", "True").lower() == "true")
tc.store(DATA_DIR)  # persist fetched data to TradeChartBot_Data/tradechart_FetchData/

# ============================================================
# BUILT-IN SECTOR GROUPS (mirroring tc.SECTOR_GROUPS)
# ============================================================

BUILTIN_SECTOR_GROUPS: dict[str, list[str]] = {
    "mag7":          ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"],
    "sp500_etfs":    ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLB", "XLU", "XLRE", "XLC", "XLP"],
    "tech":          ["AAPL", "MSFT", "NVDA", "AMD", "INTC", "ORCL", "CRM", "ADBE", "QCOM", "TXN"],
    "finance":       ["JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "AXP", "V", "MA"],
    "energy":        ["XOM", "CVX", "COP", "EOG", "MPC", "VLO", "PSX", "OXY", "HES", "SLB"],
    "healthcare":    ["JNJ", "LLY", "UNH", "ABBV", "MRK", "ABT", "TMO", "PFE", "DHR", "BMY"],
    "consumer_disc": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TGT", "BKNG", "GM"],
    "consumer_stap": ["WMT", "PG", "KO", "PEP", "COST", "PM", "MO", "CL", "GIS", "KHC"],
    "industrials":   ["CAT", "HON", "UPS", "BA", "GE", "MMM", "RTX", "LMT", "DE", "EMR"],
    "realestate":    ["AMT", "PLD", "EQIX", "SPG", "CCI", "PSA", "DLR", "O", "WELL", "AVB"],
    "utilities":     ["NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "PCG", "ED", "ETR"],
    "crypto":        ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "ADA-USD", "XRP-USD", "DOGE-USD", "AVAX-USD"],
    "indices":       ["^GSPC", "^DJI", "^IXIC", "^RUT", "^FTSE", "^N225", "^HSI", "^GDAXI"],
    "commodities":   ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F", "ZC=F", "ZS=F", "PL=F"],
}

# ============================================================
# GUILD PERMISSIONS (JSON, in-memory cache with write-through)
# ============================================================

_perms_cache: dict[str, dict] = {}


def _default_guild() -> dict:
    return {
        "status": "live",
        "mod_roles": [],
        "user_roles": [],
        "sector_groups": dict(BUILTIN_SECTOR_GROUPS),
    }


def _load_from_disk() -> None:
    global _perms_cache
    if not PERMS_FILE.exists():
        _perms_cache = {}
        return
    try:
        _perms_cache = json.loads(PERMS_FILE.read_text(encoding="utf-8"))
    except Exception:
        _perms_cache = {}


def _save_to_disk() -> None:
    PERMS_FILE.write_text(json.dumps(_perms_cache, indent=2), encoding="utf-8")


def _guild(guild_id: int) -> dict:
    key = str(guild_id)
    if key not in _perms_cache:
        _perms_cache[key] = _default_guild()
        _save_to_disk()
    if "sector_groups" not in _perms_cache[key]:
        _perms_cache[key]["sector_groups"] = dict(BUILTIN_SECTOR_GROUPS)
        _save_to_disk()
    return _perms_cache[key]


def _get_sector_groups(guild_id: int) -> dict[str, list[str]]:
    return _guild(guild_id).get("sector_groups", dict(BUILTIN_SECTOR_GROUPS))


_load_from_disk()

# ============================================================
# PERMISSION HELPERS
# ============================================================

def _is_discord_admin(member: discord.Member, guild: discord.Guild) -> bool:
    return member == guild.owner or member.guild_permissions.administrator


def _member_role_ids(member: discord.Member) -> set[int]:
    return {role.id for role in member.roles}


def _is_mod(member: discord.Member, guild: discord.Guild) -> bool:
    cfg = _guild(guild.id)
    if _is_discord_admin(member, guild):
        return True
    mod_roles = set(cfg["mod_roles"])
    return bool(mod_roles & _member_role_ids(member))


def _can_use_charts(member: discord.Member, guild: discord.Guild) -> bool:
    cfg = _guild(guild.id)
    if cfg["status"] == "off":
        return False
    if _is_mod(member, guild):
        return True
    if not cfg["mod_roles"] and not cfg["user_roles"]:
        return True
    user_roles = set(cfg["user_roles"])
    return bool(user_roles & _member_role_ids(member))


def _can_use_clearcache(member: discord.Member, guild: discord.Guild) -> bool:
    cfg = _guild(guild.id)
    if cfg["status"] == "off":
        return False
    return _is_mod(member, guild)


# ============================================================
# DISCORD CLIENT
# ============================================================

class Bot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self._workers: list[asyncio.Task] = []

    async def setup_hook(self) -> None:
        if GUILD_ID:
            obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=obj)
            await self.tree.sync(guild=obj)
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            print("Commands synced to guild " + str(GUILD_ID))
        else:
            await self.tree.sync(guild=None)
            print("Commands synced globally")

    async def on_ready(self) -> None:
        print("Logged in as " + str(self.user))
        for _ in range(MAX_CONCURRENT):
            t = asyncio.create_task(worker())
            self._workers.append(t)

    async def close(self) -> None:
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        await super().close()


client = Bot()

# ============================================================
# QUEUE
# ============================================================

_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)
_guild_load: dict[int, int] = {}
_PER_GUILD_MAX = max(1, MAX_QUEUE_SIZE // 2)
_status_msgs: dict[tuple[int, int], discord.WebhookMessage] = {}


async def _run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


async def worker() -> None:
    while True:
        guild_id, interaction, task = await _queue.get()
        try:
            async with _semaphore:
                await task()
        except Exception:
            pass
        finally:
            _guild_load[guild_id] = max(0, _guild_load.get(guild_id, 1) - 1)
            _status_msgs.pop((guild_id, interaction.id), None)
            _queue.task_done()


async def enqueue(interaction: discord.Interaction, task) -> bool:
    guild_id = interaction.guild_id
    current_guild_load = _guild_load.get(guild_id, 0)

    if _queue.full():
        await interaction.followup.send(
            "The global queue is full. Please try again in a moment.", ephemeral=True
        )
        return False

    if current_guild_load >= _PER_GUILD_MAX:
        await interaction.followup.send(
            "This server already has " + str(current_guild_load) + " requests queued. "
            "Please wait for them to complete.",
            ephemeral=True,
        )
        return False

    position = _queue.qsize() + 1
    position_text = "you are next" if position == 1 else str(position) + " ahead of you"
    msg = await interaction.followup.send(
        "Queued (" + position_text + ") -- please wait...", ephemeral=True
    )
    _status_msgs[(guild_id, interaction.id)] = msg
    _guild_load[guild_id] = current_guild_load + 1
    await _queue.put((guild_id, interaction, task))
    return True


# ============================================================
# CHART DELIVERY HELPER
# ============================================================

async def _send_chart(interaction: discord.Interaction, generate) -> None:
    guild_id = interaction.guild_id

    async def task():
        key = (guild_id, interaction.id)
        tmp_dir = tempfile.mkdtemp()
        try:
            await _run_blocking(generate, tmp_dir)
            files = [
                os.path.join(tmp_dir, f)
                for f in os.listdir(tmp_dir)
                if f.lower().endswith(".png")
            ]
            if not files:
                raise RuntimeError("Chart generation produced no output.")
            path = max(files, key=os.path.getmtime)
            msg = _status_msgs.get(key)
            if msg:
                await msg.edit(content="", attachments=[discord.File(path)])
            else:
                await interaction.followup.send(file=discord.File(path), ephemeral=True)
        except Exception as exc:
            msg = _status_msgs.get(key)
            err = EMOJI_RED + " Error: " + str(exc)
            if msg:
                await msg.edit(content=err)
            else:
                await interaction.followup.send(content=err, ephemeral=True)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    await enqueue(interaction, task)


# ============================================================
# TICKER PARSING
# ============================================================

def _parse_tickers(raw: str, guild_id: int) -> list[str]:
    groups = _get_sector_groups(guild_id)
    tokens = re.split(r"[\s,]+", raw.strip())
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token:
            continue
        key = token.lower()
        if key in groups:
            for t in groups[key]:
                if t not in seen:
                    seen.add(t)
                    result.append(t)
        else:
            upper = token.upper()
            if upper not in seen:
                seen.add(upper)
                result.append(upper)
    return result


# ============================================================
# AUTOCOMPLETE HELPERS
# ============================================================

TICKERS     = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NFLX", "NVDA", "BTC-USD", "ETH-USD"]
DURATIONS   = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]
CHART_TYPES = ["candle", "line", "area", "ohlc", "heikin_ashi"]
INDICATORS  = ["sma", "ema", "rsi", "macd", "bollinger", "vwap"]


def _autocomplete(options: list[str]):
    async def inner(interaction: discord.Interaction, current: str):
        low = current.lower()
        return [
            app_commands.Choice(name=o, value=o)
            for o in options if low in o.lower()
        ][:25]
    return inner


async def _sector_group_autocomplete(interaction: discord.Interaction, current: str):
    if interaction.guild_id is None:
        return []
    groups = _get_sector_groups(interaction.guild_id)
    low = current.lower()
    return [
        app_commands.Choice(name=name, value=name)
        for name in groups if low in name.lower()
    ][:25]


# ============================================================
# /chart
# ============================================================

@client.tree.command(name="chart", description="Generate a financial chart for a single ticker")
@app_commands.describe(
    symbol="Ticker symbol, e.g. AAPL or BTC-USD",
    duration="Time range, e.g. 1mo or 1y",
    chart_type="Chart style (default: candle)",
    indicators="Space-separated indicators, e.g. sma rsi",
)
@app_commands.autocomplete(
    symbol=_autocomplete(TICKERS),
    duration=_autocomplete(DURATIONS),
    chart_type=_autocomplete(CHART_TYPES),
    indicators=_autocomplete(INDICATORS),
)
async def cmd_chart(
    interaction: discord.Interaction,
    symbol: str,
    duration: str,
    chart_type: str = "candle",
    indicators: str = "",
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_charts(interaction.user, interaction.guild):
        cfg = _guild(interaction.guild_id)
        reason = (
            "The bot is disabled in this server."
            if cfg["status"] == "off"
            else "You don't have permission to use this command."
        )
        await interaction.response.send_message(reason, ephemeral=True)
        return

    symbol = symbol.upper().strip()
    inds   = indicators.split() if indicators.strip() else []

    await interaction.response.defer()

    def generate(tmp_dir: str) -> None:
        tc.chart(
            symbol, duration, chart_type,
            indicators=inds or None,
            output_location=tmp_dir,
        )

    await _send_chart(interaction, generate)


# ============================================================
# /compare  (2-8 tickers, space/comma-separated or group name)
# ============================================================

@client.tree.command(
    name="compare",
    description="Overlay up to 8 tickers on one chart. Use space/comma-separated symbols or a sector group name.",
)
@app_commands.describe(
    symbols="Tickers or a sector group name, e.g. 'AAPL MSFT NVDA' or 'mag7'",
    duration="Time range (default: 1mo)",
    normalise="Plot % change from first bar instead of raw price (default: True)",
)
@app_commands.autocomplete(duration=_autocomplete(DURATIONS))
async def cmd_compare(
    interaction: discord.Interaction,
    symbols: str,
    duration: str = "1mo",
    normalise: bool = True,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_charts(interaction.user, interaction.guild):
        cfg = _guild(interaction.guild_id)
        reason = (
            "The bot is disabled in this server."
            if cfg["status"] == "off"
            else "You don't have permission to use this command."
        )
        await interaction.response.send_message(reason, ephemeral=True)
        return

    tickers = _parse_tickers(symbols, interaction.guild_id)

    if len(tickers) < 2:
        await interaction.response.send_message(
            "Please provide at least 2 ticker symbols (or a sector group with 2+ tickers).",
            ephemeral=True,
        )
        return

    if len(tickers) > 8:
        await interaction.response.send_message(
            "Too many tickers (" + str(len(tickers)) + "). Maximum is 8 -- please narrow your selection.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    def generate(tmp_dir: str) -> None:
        tc.compare(tickers, duration, normalise=normalise, output_location=tmp_dir)

    await _send_chart(interaction, generate)


# ============================================================
# /heatmap
# ============================================================

@client.tree.command(
    name="heatmap",
    description="Render a performance heatmap for a sector group or custom ticker list",
)
@app_commands.describe(
    group="Sector group name (e.g. mag7, crypto) or space/comma-separated tickers",
    duration="Time range (default: 1mo)",
)
@app_commands.autocomplete(group=_sector_group_autocomplete, duration=_autocomplete(DURATIONS))
async def cmd_heatmap(
    interaction: discord.Interaction,
    group: str,
    duration: str = "1mo",
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_charts(interaction.user, interaction.guild):
        cfg = _guild(interaction.guild_id)
        reason = (
            "The bot is disabled in this server."
            if cfg["status"] == "off"
            else "You don't have permission to use this command."
        )
        await interaction.response.send_message(reason, ephemeral=True)
        return

    tickers = _parse_tickers(group, interaction.guild_id)

    if len(tickers) < 2:
        await interaction.response.send_message(
            "Please provide at least 2 ticker symbols or a valid sector group name.",
            ephemeral=True,
        )
        return

    await interaction.response.defer()

    def generate(tmp_dir: str) -> None:
        tc.heatmap(tickers, duration, output_location=tmp_dir)

    await _send_chart(interaction, generate)


# ============================================================
# /clearcache  (mod-only)
# ============================================================

@client.tree.command(name="clearcache", description="MOD ONLY: Clear the chart data cache")
@app_commands.describe(disk="Also wipe the persistent disk store and force a full re-fetch (default: False)")
async def cmd_clearcache(interaction: discord.Interaction, disk: bool = False) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_clearcache(interaction.user, interaction.guild):
        await interaction.response.send_message("Only mods can clear the cache.", ephemeral=True)
        return

    tc.clear_cache(disk=disk)
    label = EMOJI_GREEN + " Cache cleared (memory + disk store)." if disk else EMOJI_GREEN + " Memory cache cleared."
    await interaction.response.send_message(label, ephemeral=True)


# ============================================================
# /status  (mod-only)
# ============================================================

@client.tree.command(name="status", description="MOD ONLY: Enable or disable the bot for this server")
@app_commands.describe(state="live = enabled, off = disabled")
@app_commands.choices(state=[
    app_commands.Choice(name="live", value="live"),
    app_commands.Choice(name="off",  value="off"),
])
async def cmd_status(interaction: discord.Interaction, state: str) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _is_mod(interaction.user, interaction.guild):
        await interaction.response.send_message("Only mods can change the bot status.", ephemeral=True)
        return

    cfg = _guild(interaction.guild_id)
    cfg["status"] = state
    _save_to_disk()

    if state == "live":
        label = EMOJI_GREEN + " Bot is now live."
    else:
        label = EMOJI_RED + " Bot is now disabled in this server."
    await interaction.response.send_message(label, ephemeral=True)


# ============================================================
# /sectors  (mod-only)
# ============================================================

@client.tree.command(
    name="sectors",
    description="MOD ONLY: Manage per-server sector groups used in /heatmap and /compare",
)
@app_commands.describe(
    action="What to do: list, view, create, add, remove, delete, reset",
    name="Sector group name (not needed for list)",
    tickers="Space/comma-separated ticker symbols (needed for create, add, remove)",
)
@app_commands.choices(action=[
    app_commands.Choice(name="list",   value="list"),
    app_commands.Choice(name="view",   value="view"),
    app_commands.Choice(name="create", value="create"),
    app_commands.Choice(name="add",    value="add"),
    app_commands.Choice(name="remove", value="remove"),
    app_commands.Choice(name="delete", value="delete"),
    app_commands.Choice(name="reset",  value="reset"),
])
@app_commands.autocomplete(name=_sector_group_autocomplete)
async def cmd_sectors(
    interaction: discord.Interaction,
    action: str,
    name: str | None = None,
    tickers: str | None = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _is_mod(interaction.user, interaction.guild):
        await interaction.response.send_message("Only mods can manage sector groups.", ephemeral=True)
        return

    cfg    = _guild(interaction.guild_id)
    groups: dict[str, list[str]] = cfg["sector_groups"]

    if action == "list":
        if not groups:
            await interaction.response.send_message("No sector groups configured.", ephemeral=True)
            return
        embed = discord.Embed(title="Sector Groups", colour=discord.Colour.blurple())
        for gname, gtickers in sorted(groups.items()):
            is_builtin = gname in BUILTIN_SECTOR_GROUPS
            tag   = "[built-in]" if is_builtin else "[custom]"
            label = tag + " " + gname + " (" + str(len(gtickers)) + " tickers)"
            preview = ", ".join(gtickers[:6]) + ("..." if len(gtickers) > 6 else "")
            embed.add_field(name=label, value=preview, inline=False)
        embed.set_footer(text="Use /sectors view <name> to see all tickers in a group")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if not name:
        await interaction.response.send_message(
            "Please provide a group name for action `" + action + "`.", ephemeral=True
        )
        return

    name = name.lower().strip()

    if action == "view":
        if name not in groups:
            await interaction.response.send_message("Group `" + name + "` does not exist.", ephemeral=True)
            return
        ticker_list = groups[name]
        is_builtin  = name in BUILTIN_SECTOR_GROUPS
        kind        = "Built-in" if is_builtin else "Custom"
        embed = discord.Embed(
            title=kind + " group: " + name,
            description=", ".join(ticker_list),
            colour=discord.Colour.blurple(),
        )
        embed.set_footer(text=str(len(ticker_list)) + " tickers")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if action == "delete":
        if name not in groups:
            await interaction.response.send_message("Group `" + name + "` does not exist.", ephemeral=True)
            return
        del groups[name]
        _save_to_disk()
        await interaction.response.send_message(
            EMOJI_RED + " Deleted group `" + name + "`.", ephemeral=True
        )
        return

    if action == "reset":
        if name not in BUILTIN_SECTOR_GROUPS:
            await interaction.response.send_message(
                "`" + name + "` is not a built-in group and cannot be reset. "
                "Use `/sectors delete` to remove a custom group entirely.",
                ephemeral=True,
            )
            return
        groups[name] = list(BUILTIN_SECTOR_GROUPS[name])
        _save_to_disk()
        await interaction.response.send_message(
            EMOJI_GREEN + " Reset `" + name + "` to its default ("
            + str(len(groups[name])) + " tickers).",
            ephemeral=True,
        )
        return

    if not tickers:
        await interaction.response.send_message(
            "Please provide ticker symbols for action `" + action + "`.", ephemeral=True
        )
        return

    new_tickers = [t.upper() for t in re.split(r"[\s,]+", tickers.strip()) if t]

    if action == "create":
        if len(new_tickers) < 2:
            await interaction.response.send_message(
                "A group must contain at least 2 tickers.", ephemeral=True
            )
            return
        verb = "Updated" if name in groups else "Created"
        groups[name] = new_tickers
        _save_to_disk()
        await interaction.response.send_message(
            EMOJI_GREEN + " " + verb + " group `" + name + "` with "
            + str(len(new_tickers)) + " tickers: " + ", ".join(new_tickers),
            ephemeral=True,
        )
        return

    if action == "add":
        if name not in groups:
            await interaction.response.send_message(
                "Group `" + name + "` does not exist. Use `/sectors create` to make it first.",
                ephemeral=True,
            )
            return
        existing = set(groups[name])
        added    = [t for t in new_tickers if t not in existing]
        skipped  = [t for t in new_tickers if t in existing]
        groups[name].extend(added)
        _save_to_disk()
        parts = []
        if added:
            parts.append("Added: " + ", ".join(added))
        if skipped:
            parts.append("Already present (skipped): " + ", ".join(skipped))
        await interaction.response.send_message(
            EMOJI_GREEN + " Group `" + name + "` now has "
            + str(len(groups[name])) + " tickers.\n" + "\n".join(parts),
            ephemeral=True,
        )
        return

    if action == "remove":
        if name not in groups:
            await interaction.response.send_message("Group `" + name + "` does not exist.", ephemeral=True)
            return
        to_remove = set(new_tickers)
        before    = groups[name]
        after     = [t for t in before if t not in to_remove]
        removed   = [t for t in before if t in to_remove]
        not_found = [t for t in new_tickers if t not in set(before)]

        if len(after) < 2 and after != before:
            await interaction.response.send_message(
                "Removing those tickers would leave fewer than 2 in the group. "
                "Use `/sectors delete` to remove the group entirely.",
                ephemeral=True,
            )
            return

        groups[name] = after
        _save_to_disk()
        parts = []
        if removed:
            parts.append("Removed: " + ", ".join(removed))
        if not_found:
            parts.append("Not found (skipped): " + ", ".join(not_found))
        await interaction.response.send_message(
            EMOJI_YELLOW + " Group `" + name + "` now has "
            + str(len(after)) + " tickers.\n" + "\n".join(parts),
            ephemeral=True,
        )
        return

    await interaction.response.send_message("Unknown action: `" + action + "`.", ephemeral=True)


# ============================================================
# /permissions  (admin-only)
# ============================================================

@client.tree.command(
    name="permissions",
    description="MOD ONLY: Assign Discord roles as mod or user for this server (admins only)",
)
@app_commands.describe(
    action="add or remove",
    role_type="mod (full access) or user (charts only)",
    role="The server role to configure",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="add",    value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ],
    role_type=[
        app_commands.Choice(name="mod",  value="mod"),
        app_commands.Choice(name="user", value="user"),
    ],
)
async def cmd_permissions(
    interaction: discord.Interaction,
    action: str | None = None,
    role_type: str | None = None,
    role: discord.Role | None = None,
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _is_discord_admin(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "Only server administrators can manage bot permissions.", ephemeral=True
        )
        return

    cfg = _guild(interaction.guild_id)

    if action is None or role_type is None or role is None:
        mod_mentions  = " ".join("<@&" + str(rid) + ">" for rid in cfg["mod_roles"])  or "*(none)*"
        user_mentions = " ".join("<@&" + str(rid) + ">" for rid in cfg["user_roles"]) or "*(none)*"

        embed = discord.Embed(title="Bot Permissions", colour=discord.Colour.blue())
        embed.add_field(name="Status",     value=cfg["status"], inline=True)
        embed.add_field(name="Mod roles",  value=mod_mentions,  inline=False)
        embed.add_field(name="User roles", value=user_mentions, inline=False)
        embed.set_footer(
            text=(
                "Mod roles: chart, compare, heatmap, clearcache, status, sectors.\n"
                "User roles: chart, compare, and heatmap only.\n"
                "If no roles are set, everyone can use the bot.\n"
                "Use /status to enable or disable the bot."
            )
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    key     = "mod_roles"  if role_type == "mod"  else "user_roles"
    other   = "user_roles" if role_type == "mod"  else "mod_roles"
    role_id = role.id

    if action == "add":
        if role_id in cfg[other]:
            cfg[other].remove(role_id)
        if role_id not in cfg[key]:
            cfg[key].append(role_id)
            _save_to_disk()
            await interaction.response.send_message(
                EMOJI_GREEN + " " + role.mention + " is now a " + role_type + " role.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                role.mention + " is already a " + role_type + " role.", ephemeral=True
            )
    else:
        if role_id in cfg[key]:
            cfg[key].remove(role_id)
            _save_to_disk()
            await interaction.response.send_message(
                EMOJI_YELLOW + " Removed " + role.mention + " from " + role_type + " roles.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                role.mention + " is not in the " + role_type + " role list.", ephemeral=True
            )


# ============================================================
# /help
# ============================================================

@client.tree.command(name="help", description="Show available commands")
async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="TradeChartBot", colour=discord.Colour.green())

    embed.add_field(
        name="/chart <symbol> <duration> [chart_type] [indicators]",
        value=(
            "Generate a financial chart for a single ticker.\n"
            "Example: `/chart AAPL 1mo candle sma rsi`\n"
            "Chart types: candle, line, area, ohlc, heikin_ashi\n"
            "Indicators: sma, ema, rsi, macd, bollinger, vwap"
        ),
        inline=False,
    )
    embed.add_field(
        name="/compare <symbols> [duration] [normalise]",
        value=(
            "Overlay 2-8 tickers on one chart. Separate with spaces or commas.\n"
            "You can also pass a sector group name (e.g. mag7) to compare the whole group.\n"
            "Example: `/compare AAPL MSFT NVDA 6mo` or `/compare crypto 3mo`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/heatmap <group> [duration]",
        value=(
            "Render a performance heatmap for a sector group or custom ticker list.\n"
            "Built-in groups: mag7, crypto, tech, finance, energy, healthcare, "
            "sp500_etfs, consumer_disc, consumer_stap, industrials, realestate, "
            "utilities, indices, commodities.\n"
            "Example: `/heatmap mag7 1mo` or `/heatmap AAPL MSFT NVDA GOOGL 3mo`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/clearcache [disk]  (mod only)",
        value=(
            "Clear cached chart data. Without `disk:True` only the in-memory cache is cleared "
            "and stored data on disk is still reused. Use `disk:True` to wipe the disk store "
            "and force a full re-fetch from the network."
        ),
        inline=False,
    )
    embed.add_field(
        name="/status <live|off>  (mod only)",
        value="Enable or disable the bot in this server.",
        inline=False,
    )
    embed.add_field(
        name="/sectors <action> [name] [tickers]  (mod only)",
        value=(
            "Manage per-server sector groups.\n"
            "Actions: list, view, create, add, remove, delete, reset\n"
            "Example: `/sectors create faang AAPL AMZN NFLX GOOGL META`\n"
            "Example: `/sectors add faang MSFT` | `/sectors reset mag7`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/permissions [add|remove] [mod|user] [role]  (admin only)",
        value=(
            "Assign roles as mod (full access) or user (charts only).\n"
            "Run with no arguments to view current settings."
        ),
        inline=False,
    )
    embed.set_footer(text="If no roles are configured, the bot is open to everyone.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# ENTRYPOINT
# ============================================================

async def main() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _handle_shutdown(sig) -> None:
        print("Received " + signal.Signals(sig).name + ", shutting down...")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    async with client:
        async def watcher():
            await stop.wait()
            await client.close()

        await asyncio.gather(
            client.start(TOKEN),
            watcher(),
            return_exceptions=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
