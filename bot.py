import argparse
import json
import logging
import os
import random
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    DirectMessageRequestsDisabled,
    LoginRequired,
    PleaseWaitFewMinutes,
    TwoFactorRequired,
)

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
SESSION_PATH = BASE_DIR / "session.json"
LOG_PATH = BASE_DIR / "bot.log"
STATE_TRIM = 2000

CONFIG_TEMPLATE = {
    "username": "YOUR_USERNAME",
    "password": "ENV",
    "sessionid": "",
    "media_urls": ["https://www.instagram.com/p/PASTE_POST_SHORTCODE_HERE/"],
    "reply_enabled": True,
    "reply_text": "@{username} thanks for your comment - I've sent you a DM!",
    "message_template": "Hi {username}! Thanks for your comment on my reel.",
    "keywords": [],
    "ignore_users": ["instagram"],
    "poll_interval_seconds": 45,
    "min_delay_seconds": 45,
    "max_delay_seconds": 120,
    "max_dms_per_hour": 5,
    "max_dms_per_day": 20,
    "request_delay_range": [2, 6],
    "pause_window": {"start": "02:00", "end": "06:00"},
    "pause_check_minutes": 5,
    "cloud_interval_minutes": 5,
}

logger = logging.getLogger("ig_bot")


class LoginFailed(Exception):
    pass


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
        ],
    )


def load_config(path):
    if not path.exists():
        path.write_text(json.dumps(CONFIG_TEMPLATE, indent=2), encoding="utf-8")
        logger.error("No config.json found - created a template at %s", path)
        logger.error("Open it, fill in your username and sessionid, then run again")
        sys.exit(1)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("sessionid", "")
    stored = cfg.get("password", "")
    if not stored or stored == "ENV":
        stored = os.environ.get("IG_PASSWORD", "")
    cfg["_password_from_env"] = stored
    return cfg


def load_state():
    if STATE_PATH.exists():
        try:
            return normalize_state(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            logger.warning("state.json corrupt, starting fresh")
    return {"replied_comments": {}, "dm_users": {}, "dm_timestamps": [], "last_run": None}


def normalize_state(state):
    state.setdefault("dm_timestamps", [])
    state.setdefault("last_run", None)
    if isinstance(state.get("seen_comments"), list):
        legacy = state
        logger.info(
            "Migrating legacy state (seen_comments=%d, dm_users=%d)",
            len(legacy.get("seen_comments", [])),
            len(legacy.get("dm_users", [])),
        )
        state = {
            "replied_comments": {},
            "dm_users": {},
            "dm_timestamps": legacy.get("dm_timestamps", []),
            "last_run": legacy.get("last_run"),
            "_legacy_seen": legacy.get("seen_comments", []),
            "_legacy_dm_users": legacy.get("dm_users", []),
        }
    state.setdefault("replied_comments", {})
    state.setdefault("dm_users", {})
    return state


def save_state(state):
    for key in ("replied_comments", "dm_users"):
        for media_id in state.get(key, {}):
            state[key][media_id] = state[key][media_id][-STATE_TRIM:]
    state["dm_timestamps"] = state["dm_timestamps"][-STATE_TRIM:]
    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def in_pause_window(cfg):
    start, end = cfg["pause_window"]["start"], cfg["pause_window"]["end"]
    now = datetime.now().strftime("%H:%M")
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def count_since(state, seconds):
    cutoff = time.time() - seconds
    return sum(1 for t in state["dm_timestamps"] if t > cutoff)


def render_template(template, username, comment_text):
    return template.replace("{username}", username).replace("{comment}", comment_text)


def login(cfg, twofa_callback=None):
    client = Client()
    client.delay_range = cfg.get("request_delay_range", [2, 6])
    sessionid = os.environ.get("IG_SESSIONID") or cfg.get("sessionid", "")
    if sessionid:
        try:
            client.login_by_sessionid(sessionid)
            client.dump_settings(SESSION_PATH)
            logger.info("Logged in with sessionid")
            return client
        except Exception as exc:
            raise LoginFailed(f"sessionid login failed: {exc}. "
                              "Paste a fresh sessionid from a logged-in browser into config.json")
    if SESSION_PATH.exists():
        try:
            client.load_settings(SESSION_PATH)
            client.login(cfg["username"], cfg["password"])
            client.dump_settings(SESSION_PATH)
            logger.info("Logged in with saved session")
            return client
        except (LoginRequired, ChallengeRequired) as exc:
            logger.warning("Saved session rejected (%s); doing fresh login", exc)
            SESSION_PATH.unlink(missing_ok=True)
    if not cfg["password"]:
        raise LoginFailed("No password set. Set the IG_PASSWORD env var, or put a sessionid in config.json")
    try:
        client.login(cfg["username"], cfg["password"])
    except TwoFactorRequired:
        ask = twofa_callback or input
        code = str(ask("Enter 2FA code: ")).strip()
        client.login(cfg["username"], cfg["password"], verification_code=code)
    except (ChallengeRequired, LoginRequired) as exc:
        raise LoginFailed(f"Login blocked: {exc}. Resolve any challenge in the Instagram app, then retry")
    except Exception as exc:
        raise LoginFailed(f"Login failed: {exc}. If Instagram rejects the login, add a sessionid to config.json")
    client.dump_settings(SESSION_PATH)
    logger.info("Logged in, session saved")
    return client


def media_list(cfg):
    urls = [u.strip() for u in cfg.get("media_urls", []) if u.strip()]
    if not urls and cfg.get("media_url"):
        urls = [cfg["media_url"]]
    return urls


def resolve_media_urls(cfg, config_path):
    urls = media_list(cfg)
    if not urls or any("PASTE_POST_SHORTCODE" in u for u in urls):
        urls = []
        print("Paste Instagram post/reel URLs, one per line (empty line = done):")
        while True:
            url = input().strip()
            if not url:
                break
            urls.append(url)
        cfg["media_urls"] = urls
        cfg.pop("media_url", None)
        cfg["password"] = "ENV"
        cfg.pop("_password_from_env", None)
        config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        cfg["password"] = cfg.pop("_password_from_env", "")
        logger.info("Saved media_urls to %s", config_path)
    else:
        cfg["password"] = cfg.pop("_password_from_env", "")
    return urls


def process_media(client, cfg, state, dry_run):
    sent_this_run = 0
    reply_enabled = cfg.get("reply_enabled", True) and cfg.get("reply_text", "").strip()
    for url in media_list(cfg):
        media_id = str(client.media_pk_from_url(url))
        if state.get("_legacy_seen") is not None:
            state["replied_comments"][media_id] = state.pop("_legacy_seen")
            state["dm_users"][media_id] = state.pop("_legacy_dm_users")
            save_state(state)
            logger.info("Attached legacy state to media %s", media_id)
        replied = state["replied_comments"].setdefault(media_id, [])
        dm_users = state["dm_users"].setdefault(media_id, [])
        comments = client.media_comments(media_id, amount=0)
        comments.sort(key=lambda c: c.created_at_utc)
        logger.info("[%s] Fetched %d comments", media_id, len(comments))
        for comment in comments:
            pk = str(comment.pk)
            if str(comment.user.pk) == str(client.user_id):
                if pk not in replied:
                    replied.append(pk)
                    save_state(state)
                continue
            username = comment.user.username
            if username in cfg.get("ignore_users", []):
                continue
            keywords = cfg.get("keywords", [])
            if keywords and not any(k.lower() in comment.text.lower() for k in keywords):
                continue
            if pk in replied and username in dm_users:
                continue
            if count_since(state, 3600) >= cfg["max_dms_per_hour"]:
                logger.info("Hourly limit (%d/h) reached", cfg["max_dms_per_hour"])
                return sent_this_run
            if count_since(state, 86400) >= cfg["max_dms_per_day"]:
                logger.info("Daily limit (%d/day) reached", cfg["max_dms_per_day"])
                return sent_this_run
            if state["dm_timestamps"]:
                delay = random.randint(cfg["min_delay_seconds"], cfg["max_delay_seconds"])
                logger.info("Waiting %ds before next action", delay)
                time.sleep(delay)
            if reply_enabled and pk not in replied:
                reply_text = render_template(cfg["reply_text"], username, comment.text)
                try:
                    client.media_comment(media_id, reply_text, replied_to_comment_id=int(pk))
                    logger.info("Replied to @%s (%s)", username, pk)
                except Exception as exc:
                    logger.warning("Reply to @%s failed: %s", username, exc)
                replied.append(pk)
                save_state(state)
            if username not in dm_users:
                text = render_template(cfg["message_template"], username, comment.text)
                if dry_run:
                    logger.info("[DRY-RUN] would DM @%s: %s", username, text)
                else:
                    try:
                        client.direct_send(text, user_ids=[comment.user.pk])
                    except DirectMessageRequestsDisabled:
                        logger.warning("@%s has DMs disabled, skipped", username)
                    else:
                        state["dm_timestamps"].append(time.time())
                        logger.info("DM sent to @%s (%s)", username, pk)
                dm_users.append(username)
                save_state(state)
                sent_this_run += 1
    return sent_this_run


def run_forever(client, cfg, state, stop_event, log=logger.info, once=False, dry_run=False):
    while not stop_event.is_set():
        try:
            if in_pause_window(cfg):
                log("Inside pause window (%s-%s), sleeping", *cfg["pause_window"].values())
                if once or stop_event.wait(60 * cfg.get("pause_check_minutes", 5)):
                    return
                continue
            sent = process_media(client, cfg, state, dry_run)
            log("Run finished, sent %d", sent)
            if once or stop_event.wait(cfg["poll_interval_seconds"]):
                return
        except PleaseWaitFewMinutes as exc:
            log("Rate limited by Instagram: %s. Pausing 15 min", exc)
            if stop_event.wait(900):
                return
        except (LoginRequired, ChallengeRequired) as exc:
            log("Account needs attention: %s", exc)
            log("Resolve any challenge in the Instagram app, then restart")
            return
        except Exception as exc:
            log("Unexpected error: %s", exc)
            if once:
                return
            if stop_event.wait(60):
                return


def main():
    parser = argparse.ArgumentParser(description="Instagram comment -> DM bot")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="path to config.json")
    parser.add_argument("--once", action="store_true", help="check once and exit")
    parser.add_argument("--dry-run", action="store_true", help="log what would be sent, send nothing")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config(Path(args.config))
    resolve_media_urls(cfg, Path(args.config))
    state = load_state()
    try:
        client = login(cfg)
    except LoginFailed as exc:
        logger.error("%s", exc)
        sys.exit(1)
    stop_event = threading.Event()
    try:
        run_forever(client, cfg, state, stop_event, once=args.once, dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
