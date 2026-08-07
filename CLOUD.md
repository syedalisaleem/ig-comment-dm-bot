# Run the bot 24/7 in the cloud (GitHub Actions)

Free cloud hosting: GitHub runs `bot.py --once` every 5 minutes on their servers.
Your PC can be off. **No hardware, no cost.**

## What happens

1. Every 5 minutes GitHub starts a Linux VM, logs into Instagram with your sessionid,
   checks the post for new comments, DMs new commenters, then commits the updated
   `state.json` back to the repo so nobody is ever DM'd twice.

## Setup (10 minutes)

1. Create a free account at github.com.
2. Click **+** → **New repository**:
   - Name: `ig-comment-dm-bot`
   - **Public** (required: private repos only get 2000 free minutes/month, which
     won't cover every-5-minute runs; public is unlimited)
   - Do NOT initialize with README (you'll push local files).
3. Copy these files from `F:\11` into the new repo:
   - `bot.py`, `requirements.txt`, `config.json`, `state.json`, `.gitignore`
   - the `.github` folder (contains the workflow)
4. Commit and push them (GitHub Desktop or `git push`).
5. Add your sessionid as a secret (it stays encrypted, never committed):
   - Repo → **Settings** → **Secrets and variables** → **Actions**
   - **New repository secret** → Name: `IG_SESSIONID`
   - Value: your sessionid cookie (same one as before)
6. Test it now: repo → **Actions** tab → **IG Comment DM Bot** →
   **Run workflow** button → watch the logs. You should see
   `Logged in with sessionid` and `Run finished, sent 0`.
7. The schedule (`*/5 * * * *`) takes over automatically from then on.

## Troubleshooting

- **"sessionid login failed"** in the logs: Instagram rejected the cloud IP for
  that session. Get a fresh sessionid from your browser and update the secret.
- **Runs missing for a while**: GitHub sometimes delays scheduled runs (up to ~30 min),
  that's normal.
- **Workflow paused**: GitHub auto-pauses schedules if a repo is inactive for
  60 days — just go to Actions and re-enable.
- **Login not possible / blocked**: fall back to running the app on an always-on
  device (spare phone with Termux, or an old laptop) — the same `bot.py` works there.

## Local files you no longer need for the cloud version

- `session.json`, `bot.log` are never used in the cloud (the sessionid env var is
  used instead, and logs go to the Actions output).
