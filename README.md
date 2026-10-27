# Waaid Radar

A Telegram bot that watches the [Waaid scholarship path](https://sites.moe.gov.sa/scholarship-program/paths/path-waaid/) and posts every new program to a channel.

- Posts each new program with its full details and hashtags
- Keeps each post's status current: not open yet → open → closed
- Reminds on the opening day and the day before closing
- Sends programs that match your interests to your private chat, plus a weekly digest

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and make it an admin of your channel.
2. In **Settings → Secrets and variables → Actions**, add:

   | Name | Type | Value |
   |---|---|---|
   | `TELEGRAM_BOT_TOKEN` | Secret | Bot token |
   | `TELEGRAM_CHANNEL_ID` | Variable | `@your_channel` |
   | `TELEGRAM_ADMIN_CHAT_ID` | Variable | Your chat ID |

3. Open **Actions → waaid-radar → Run workflow** and run `check`, then `preview`, then `run`.

It then runs every 3 hours and sends a digest every Sunday.

Optional variables: `PERSONAL_TAGS` (default `حاسب,لخريجي_الحاسب`), `QUIET_HOURS` (default `23-7`, Riyadh time).

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env    # then fill it in
python -m waaid_radar preview
```

Tests: `pip install -r requirements-dev.txt && python -m pytest -q`
