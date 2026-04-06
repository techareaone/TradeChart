
# Privacy Policy  
**TradeChart Demo Discord Bot**  
*Effective: April 6, 2026*  
[Library Source](https://github.com/techareaone/TradeChart) · [Demo Bot Code](https://github.com/techareaone/TradeChart/blob/main/tradechart_examples/discord_demo_bot/discord_bot.py)

## 1. Information We Collect

### A. User‑provided (explicit input)
- Ticker symbols (e.g., `AAPL`, `BTC-USD`)
- Chart parameters (duration, type, indicators)
- Comparison symbols (two tickers)

### B. Discord metadata (automatically received)
- User ID, Guild (server) ID, Role IDs
- Interaction ID, permission flags (admin/mod)

### C. Persistent stored data (only file)
`guild_permissions.json` stores:
- `guild_id`, `status` (`live`/`off`)
- `mod_roles`, `user_roles` (role IDs)

**No usernames, message logs, chat history, IPs, emails, or personal identifiers are ever stored.**

### D. Temporary / ephemeral data
- Chart images (`.png`) → deleted immediately after sending
- In‑memory queue state → cleared on restart
- Ephemeral Discord messages

### E. External data sources
Ticker symbols + parameters are sent to financial data providers (e.g., Yahoo Finance) via the `tradechart` library. **No user identity is attached.**

## 2. How We Use Information

**Only for:**
- Generating requested charts
- Enforcing role‑based permissions
- Managing queue / rate limits
- Storing server‑specific config

**No:** marketing, selling, profiling, analytics.

## 3. Data Sharing

| Recipient | Data shared | Purpose |
|-----------|-------------|---------|
| Discord Inc. | User ID, Guild ID, Role IDs, Interaction ID, command params | Deliver responses, verify permissions |
| Financial data providers | Ticker symbols, chart parameters | Fetch market data |

No other third parties. No Discord metadata is shared with data providers.

## 4. Data Retention

| Data type | Retention |
|-----------|------------|
| `guild_permissions.json` | Indefinite until manual deletion |
| Temporary chart images | Deleted after sending |
| In‑memory caches | Cleared on restart |
| Ephemeral Discord messages | Auto‑deleted by Discord |

## 5. Data Security

- Data stored locally on host machine (no cloud database)
- No encryption for JSON files
- Discord token stored in `config.env` (must be kept secret by host)
- Access control relies entirely on Discord roles

**Host responsibility:** securing the host machine and token.

## 6. Your Rights & Choices

- **Server admins** can modify/delete config using `/permissions`, `/status`, or by contacting the host.
- **Users** – no stored personal data; simply stop using the bot.
- **Opt‑out:** use `/status off` (mod only) to disable the bot for a server.

## 7. Children’s Privacy

The bot does not knowingly collect information from children under 13 (or 16). Contact host if you believe otherwise – no personal data is retained.

## 8. Changes to This Policy

The “Effective Date” at the top will change. For the official demo bot, updates are announced via GitHub.

## 9. Contact

Open an issue on the [TradeChart GitHub repo](https://github.com/techareaone/TradeChart).


# Terms & Conditions  
**TradeChart Demo Discord Bot**  
*Last Updated: April 6, 2026*  
By using this bot, you agree to these Terms.

## 1. Description of Service

A **demonstration** of the `tradechart` Python library. Provides Discord commands:
- `/chart`, `/compare`, `/clearcache` (mod only)
- `/status`, `/permissions`, `/help`

## 2. Acceptable Use

You agree **not** to:
- Spam the bot or circumvent rate limits
- Use the bot for illegal activity or harassment
- Reverse‑engineer, inject malicious code, or disrupt operation
- Rely solely on charts for financial decisions (see §5)

Violation may lead to blocking at the host’s discretion.

## 3. Permissions & Access Control

Access governed by Discord roles:
- **Server admins** – full access
- **Mod roles** – `/status`, `/clearcache`, `/permissions`
- **User roles** – `/chart`, `/compare`, `/help`
- **No roles set** – all members have user commands

## 4. Availability & Service Level

- **No uptime guarantee** – bot may go offline
- Queued requests may cause delays
- Bot may be discontinued at any time
- Self‑hosted availability is your own responsibility

## 5. Financial Disclaimer – No Investment Advice

**Charts are for informational and educational purposes only.**
- Not financial advice, trading recommendations, or an offer to buy/sell.
- Past performance does not guarantee future results.
- Data comes from third‑party providers (e.g., Yahoo Finance) – no warranty of accuracy or timeliness.
- **Consult a qualified financial advisor before making investment decisions.**

You assume all risk. Authors and hosts are not liable for any losses.

## 6. Limitation of Liability

To the maximum extent permitted by law:
- The bot is provided “AS IS” and “AS AVAILABLE” without any warranties.
- In no event shall developers, contributors, or hosts be liable for any direct, indirect, incidental, special, consequential, or punitive damages arising from your use of the bot.

## 7. Third‑Party Services

The bot uses Discord’s API (subject to Discord’s ToS) and financial data APIs (subject to their own terms). We have no control over their availability or data quality.

## 8. Changes to the Bot or These Terms

We may modify or discontinue the bot (or these Terms) at any time. Continued use constitutes acceptance.

## 9. Termination

We may suspend or terminate access at any time, without notice, for violation of these Terms. Server admins can disable the bot for their server using `/status off`.

## 10. Governing Law

Governing law is that of the bot host’s jurisdiction (for the official demo, the repository owner’s location). Self‑hosted instances are the host’s responsibility.

## 11. Contact & Disputes

Open an issue on the [TradeChart GitHub repo](https://github.com/techareaone/TradeChart). You agree to attempt informal resolution before any legal claim.

---

*This document is a template. If you self‑host, adapt to your own legal requirements.*

