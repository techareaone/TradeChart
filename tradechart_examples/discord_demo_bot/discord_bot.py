#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeChartBot: Lightweight Discord bot for financial charts.

Permissions model (simple):
  - Guild owner + Discord Administrators: always have full access (mod).
  - Mod roles: can use all commands including /clearcache.
  - User roles: can use /chart and /compare only.
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
# PATHS & CONFIG
# ============================================================

SCRIPT_DIR  = Path(__file__).parent.resolve()
DATA_DIR    = SCRIPT_DIR / "TradeChartBot_Data"
CONFIG_PATH = DATA_DIR / "config.env"
PERMS_FILE  = DATA_DIR / "guild_permissions.json"

DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = """\
DISCORD_TOKEN=
GUILD_ID=
THEME=dark
TERMINAL=none
WATERMARK=True
MAX_CONCURRENT=2
MAX_QUEUE_SIZE=20
"""

def ensure_config() -> None:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(DEFAULT_CONFIG)
        print("Created config.env - fill in DISCORD_TOKEN and restart.")
        sys.exit(0)

def load_config() -> None:
    for line in CONFIG_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        # Strip inline comments
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

GUILD_ID_RAW  = os.getenv("GUILD_ID", "").strip()
GUILD_ID: int | None = int(GUILD_ID_RAW) if GUILD_ID_RAW.isdigit() else None

MAX_CONCURRENT = max(1, int(os.getenv("MAX_CONCURRENT", "2")))
MAX_QUEUE_SIZE = max(1, int(os.getenv("MAX_QUEUE_SIZE", "20")))

tc.theme(os.getenv("THEME", "dark"))
tc.terminal(os.getenv("TERMINAL", "none"))
tc.watermark(os.getenv("WATERMARK", "True").lower() == "true")

# ============================================================
# GUILD PERMISSIONS (JSON, in-memory cache with write-through)
# ============================================================
#
# Schema per guild (keyed by str(guild_id)):
#   {
#     "status":     "live" | "off",
#     "mod_roles":  [role_id, ...],   # full access
#     "user_roles": [role_id, ...]    # chart/compare only
#   }
#
# If both lists are empty -> open access (everyone may use all commands).
# ============================================================

_perms_cache: dict[str, dict] = {}


def _default_guild() -> dict:
    return {"status": "live", "mod_roles": [], "user_roles": []}


def _load_from_disk() -> None:
    global _perms_cache
    if not PERMS_FILE.exists():
        _perms_cache = {}
        return
    try:
        _perms_cache = json.loads(PERMS_FILE.read_text())
    except Exception:
        _perms_cache = {}


def _save_to_disk() -> None:
    PERMS_FILE.write_text(json.dumps(_perms_cache, indent=2))


def _guild(guild_id: int) -> dict:
    """Return (and initialise if absent) the config for one guild."""
    key = str(guild_id)
    if key not in _perms_cache:
        _perms_cache[key] = _default_guild()
        _save_to_disk()
    return _perms_cache[key]


_load_from_disk()

# ============================================================
# PERMISSION HELPERS
# ============================================================

def _is_discord_admin(member: discord.Member, guild: discord.Guild) -> bool:
    """True if the member is the guild owner or has Discord's Administrator bit."""
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
    # Open access when no roles configured at all
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
            # Wipe global commands so they don't appear alongside guild ones.
            self.tree.clear_commands(guild=None)
            await self.tree.sync(guild=None)
            print(f"Commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync(guild=None)
            print("Commands synced globally")

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}")
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
# QUEUE (per-guild fairness via guild-keyed sub-queues)
# ============================================================
# We keep one global asyncio.Queue but tag each item with its guild_id.
# A semaphore limits total concurrency. Per-guild in-flight tracking
# prevents one guild from monopolising all worker slots.
# ============================================================

_queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# guild_id -> number of tasks currently in-flight or queued
_guild_load: dict[int, int] = {}
_PER_GUILD_MAX = max(1, MAX_QUEUE_SIZE // 2)

# Maps interaction.id -> ephemeral "please wait" message (guild-scoped key)
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
            pass  # task() handles its own error reporting via _status_msgs
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
            f"This server already has {current_guild_load} requests queued. "
            "Please wait for them to complete.", ephemeral=True
        )
        return False

    position = _queue.qsize() + 1
    position_text = "you are next" if position == 1 else f"{position} ahead of you"
    msg = await interaction.followup.send(f"Queued ({position_text}) -- please wait...", ephemeral=True)
    _status_msgs[(guild_id, interaction.id)] = msg
    _guild_load[guild_id] = current_guild_load + 1
    await _queue.put((guild_id, interaction, task))
    return True

# ============================================================
# CHART TASK HELPER
# ============================================================

async def _send_chart(interaction: discord.Interaction, generate) -> None:
    """
    Run `generate(path)` in a thread, then deliver the chart.
    The queued "please wait" ephemeral is edited in-place with the
    final image -- it is never deleted, so the user always sees a result.
    Errors are also shown in that same message.
    """
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
            if msg:
                await msg.edit(content=f"Error: {exc}")
            else:
                await interaction.followup.send(content=f"Error: {exc}", ephemeral=True)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    await enqueue(interaction, task)

# ============================================================
# AUTOCOMPLETE
# ============================================================

TICKERS     = ["AAPL","MSFT","GOOGL","AMZN","TSLA","META","NFLX","NVDA","BTC-USD","ETH-USD"]
DURATIONS   = ["1d","5d","1mo","3mo","6mo","1y","2y","5y","max"]
CHART_TYPES = ["candle","line","area","ohlc","heikin_ashi"]
INDICATORS  = ["sma","ema","rsi","macd","bollinger","vwap"]


def _autocomplete(options: list[str]):
    async def inner(interaction: discord.Interaction, current: str):
        low = current.lower()
        return [
            app_commands.Choice(name=o, value=o)
            for o in options if low in o.lower()
        ][:25]
    return inner

# ============================================================
# /chart
# ============================================================

@client.tree.command(name="chart", description="Generate a financial chart")
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
        reason = "The bot is disabled in this server." if cfg["status"] == "off" \
            else "You don't have permission to use this command."
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
# /compare
# ============================================================

@client.tree.command(name="compare", description="Compare two symbols on one chart")
@app_commands.describe(
    symbol1="First ticker",
    symbol2="Second ticker",
    duration="Time range (default: 1mo)",
)
@app_commands.autocomplete(
    symbol1=_autocomplete(TICKERS),
    symbol2=_autocomplete(TICKERS),
    duration=_autocomplete(DURATIONS),
)
async def cmd_compare(
    interaction: discord.Interaction,
    symbol1: str,
    symbol2: str,
    duration: str = "1mo",
) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_charts(interaction.user, interaction.guild):
        cfg = _guild(interaction.guild_id)
        reason = "The bot is disabled in this server." if cfg["status"] == "off" \
            else "You don't have permission to use this command."
        await interaction.response.send_message(reason, ephemeral=True)
        return

    symbol1 = symbol1.upper().strip()
    symbol2 = symbol2.upper().strip()

    if symbol1 == symbol2:
        await interaction.response.send_message(
            "Both symbols are the same -- pick two different tickers.", ephemeral=True
        )
        return

    await interaction.response.defer()

    def generate(tmp_dir: str) -> None:
        tc.compare(
            [symbol1, symbol2], duration,
            output_location=tmp_dir,
        )

    await _send_chart(interaction, generate)

# ============================================================
# /clearcache  (mod-only)
# ============================================================

@client.tree.command(name="clearcache", description="Clear the chart data cache (mods only)")
async def cmd_clearcache(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await interaction.response.send_message("This bot only works in servers.", ephemeral=True)
        return

    if not _can_use_clearcache(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "Only mods can clear the cache.", ephemeral=True
        )
        return

    tc.clear_cache()
    await interaction.response.send_message("Cache cleared.", ephemeral=True)

# ============================================================
# /status  (mod-only, toggles live/off for THIS guild only)
# ============================================================

@client.tree.command(name="status", description="Enable or disable the bot for this server (mods only)")
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
        await interaction.response.send_message(
            "Only mods can change the bot status.", ephemeral=True
        )
        return

    cfg = _guild(interaction.guild_id)
    cfg["status"] = state
    _save_to_disk()

    label = "Bot is now live." if state == "live" else "Bot is now disabled in this server."
    await interaction.response.send_message(label, ephemeral=True)

# ============================================================
# /permissions  (admin-only)
#
# Simple model: Discord roles are labelled as either "mod" or "user".
#   mod roles  -> full access (chart, compare, clearcache, status)
#   user roles -> chart and compare only
#
# If no roles are configured, the bot is open to everyone.
# ============================================================

@client.tree.command(
    name="permissions",
    description="Assign Discord roles as 'mod' or 'user' for this server (admins only)",
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

    # Only Discord administrators / guild owner may touch permissions
    if not _is_discord_admin(interaction.user, interaction.guild):
        await interaction.response.send_message(
            "Only server administrators can manage bot permissions.", ephemeral=True
        )
        return

    cfg = _guild(interaction.guild_id)

    # No args -> show current config
    if action is None or role_type is None or role is None:
        mod_mentions  = " ".join(f"<@&{rid}>" for rid in cfg["mod_roles"])  or "*(none)*"
        user_mentions = " ".join(f"<@&{rid}>" for rid in cfg["user_roles"]) or "*(none)*"

        embed = discord.Embed(title="Bot Permissions", colour=discord.Colour.blue())
        embed.add_field(name="Status",     value=cfg["status"],  inline=True)
        embed.add_field(name="Mod roles",  value=mod_mentions,  inline=False)
        embed.add_field(name="User roles", value=user_mentions, inline=False)
        embed.set_footer(
            text=(
                "Mod roles: chart, compare, clearcache, status.\n"
                "User roles: chart and compare only.\n"
                "If no roles are set, everyone can use the bot.\n"
                "Use /status to enable or disable the bot."
            )
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    key      = "mod_roles" if role_type == "mod" else "user_roles"
    other    = "user_roles" if role_type == "mod" else "mod_roles"
    role_id  = role.id

    if action == "add":
        # Enforce mutual exclusivity: a role can only be in one category
        if role_id in cfg[other]:
            cfg[other].remove(role_id)
        if role_id not in cfg[key]:
            cfg[key].append(role_id)
            _save_to_disk()
            await interaction.response.send_message(
                f"{role.mention} is now a {role_type} role.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{role.mention} is already a {role_type} role.", ephemeral=True
            )
    else:  # remove
        if role_id in cfg[key]:
            cfg[key].remove(role_id)
            _save_to_disk()
            await interaction.response.send_message(
                f"Removed {role.mention} from {role_type} roles.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{role.mention} is not in the {role_type} role list.", ephemeral=True
            )

# ============================================================
# /help
# ============================================================

@client.tree.command(name="help", description="Show available commands")
async def cmd_help(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="TradeChartBot", colour=discord.Colour.green())

    embed.add_field(
        name="/chart <symbol> <duration> [chart_type] [indicators]",
        value="Generate a financial chart.\nExample: `/chart AAPL 1mo candle sma rsi`",
        inline=False,
    )
    embed.add_field(
        name="/compare <symbol1> <symbol2> [duration]",
        value="Overlay two symbols on one chart.\nExample: `/compare AAPL MSFT 6mo`",
        inline=False,
    )
    embed.add_field(
        name="/clearcache",
        value="Clear cached chart data. **Mod only.**",
        inline=False,
    )
    embed.add_field(
        name="/status <live|off>",
        value="Enable or disable the bot in this server. **Mod only.**",
        inline=False,
    )
    embed.add_field(
        name="/permissions [add|remove] [mod|user] [role]",
        value=(
            "Assign roles as **mod** (full access) or **user** (charts only).\n"
            "Run with no arguments to view current settings. **Admin only.**"
        ),
        inline=False,
    )
    embed.set_footer(text="If no roles are configured, the bot is open to everyone.")

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ============================================================
# ENTRYPOINT
# ============================================================
# discord.py's client.run() owns the event loop, so signal handling
# must go through the loop itself rather than plain signal.signal().
# We register asyncio signal handlers inside an async main() so they
# can call client.close() cleanly without fighting asyncio.run().
# ============================================================

async def main() -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _handle_shutdown(sig) -> None:
        print(f"Received {signal.Signals(sig).name}, shutting down...")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_shutdown, sig)

    async with client:
        # Run the bot and the shutdown watcher concurrently.
        # When the signal fires, stop.set() unblocks the watcher,
        # which calls client.close() and awaits it fully before
        # the async-with block exits -- giving Discord time to
        # receive the websocket close frame and mark the bot offline.
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
