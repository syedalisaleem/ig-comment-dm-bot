# Instagram Comment -> DM Bot

Fully free, local Python tool: watches a post/reel and automatically DMs each new commenter from your own account.

**Want it to run 24/7 without your PC?** See [CLOUD.md](CLOUD.md) — a free GitHub Actions setup runs it every 5 minutes from the cloud.

**Warning:** this automates actions Instagram's Terms of Service discourage. There is a real risk of rate-limits, challenges, or account action on your account. The default limits in `config.json` are deliberately conservative. Use on a spare account first, and stop if you see a challenge.

## Setup

1. Install Python 3.10+.
2. Install dependencies:

   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

3. Edit `config.json`:
   - `username` - your Instagram username
   - `password` - your password, or `"ENV"` and set the `IG_PASSWORD` environment variable instead (safer)
   - `sessionid` - optional but recommended: a session cookie from a browser logged into the account (see below). Used first; bypasses Instagram's device-login checks.
   - `media_urls` - list of post/reel links to watch (as many as you want). Each is checked on every run.
   - `reply_enabled` / `reply_text` - optionally reply publicly to each new comment before DMing it (default on, supports `{username}` and `{comment}`)
   - `message_template` - the DM text; supports `{username}` and `{comment}` placeholders
   - `keywords` - leave `[]` to DM every commenter, or list words (e.g. `["price", "info"]`) to only DM matching comments
   - `ignore_users` - usernames to never DM
   - Delay/limit settings - the safety knobs (lower = safer)

## sessionid (recommended)

If password login gets rejected ("version out of date", wrong-password errors, etc.), paste a `sessionid` into `config.json` and the bot uses it instead:

1. Log into instagram.com in Chrome (any device).
2. Press F12 → **Application** tab → **Cookies** → `https://www.instagram.com` → find the **`sessionid`** cookie → copy its value.
3. Paste it into `sessionid` in `config.json`.

The sessionid is powerful (full account access) - treat it like a password. A fresh one may be needed periodically.

## Run

```
.venv\Scripts\python bot.py            # continuous mode
.venv\Scripts\python bot.py --once     # single check, exits (for Task Scheduler)
.venv\Scripts\python bot.py --dry-run  # logs what it WOULD do, sends nothing
```

First run asks for login (and 2FA code if enabled) and saves the session to `session.json`; later runs reuse it.

## State files

- `state.json` - replied comments and DM'd users per video, DM timestamps. Never delete it; it prevents double replies and double DMs.
- `bot.log` - full activity log.

## Long-term use (Windows Task Scheduler)

Use `--once` every few minutes instead of running continuous mode:

1. `schtasks /create /tn "IGBot" /tr "\"F:\11\.venv\Scripts\python.exe\" F:\11\bot.py --once" /sc minute /mo 5`
2. Keep the PC awake, or rely on the poll loop's own sleep instead.

## If you get rate-limited or a challenge

The bot pauses 15 minutes on rate limits and exits with instructions on challenges. Resolve challenges in the Instagram app before rerunning. If it keeps happening, lower `max_dms_per_hour`/`max_dms_per_day` and raise `min_delay_seconds`/`max_delay_seconds`.
