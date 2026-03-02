#!/usr/bin/env python3
"""
Post from the content calendar or run as a cron job to auto-post.

Usage:
    python x_scheduled_post.py --next                    # Post the next scheduled item
    python x_scheduled_post.py --day monday              # Post all Monday content
    python x_scheduled_post.py --index 0                 # Post specific item from week_1
    python x_scheduled_post.py --text "custom post"      # Post custom text
    python x_scheduled_post.py --list                    # Show upcoming posts
    python x_scheduled_post.py --dry-run --next          # Preview without posting

Auth: Uses JOEL_X_CONSUMER_KEY/SECRET + stored access tokens,
      falls back to X_ADS_* credentials (@synterai)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


CALENDAR_PATH = Path(__file__).parent / "content_calendar.json"

# Use Railway persistent volume if available, otherwise local
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
POSTED_LOG = _DATA_DIR / ".x_posted_log.json"

DAYS_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_calendar() -> dict:
    with open(CALENDAR_PATH) as f:
        return json.load(f)


def load_posted_log() -> set:
    if POSTED_LOG.exists():
        with open(POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_posted_log(posted: set):
    with open(POSTED_LOG, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def get_oauth_session():
    """Get OAuth 1.0a session. Prefer Joel Personal Assistant app, fall back to Synter app."""
    from requests_oauthlib import OAuth1Session

    # Try Joel Personal Assistant credentials first
    consumer_key = os.environ.get("JOEL_X_CONSUMER_KEY") or os.environ.get("X_ADS_CONSUMER_KEY")
    consumer_secret = os.environ.get("JOEL_X_CONSUMER_SECRET") or os.environ.get("X_ADS_CONSUMER_SECRET")
    access_token = os.environ.get("JOEL_X_ACCESS_TOKEN") or os.environ.get("X_ADS_ACCESS_TOKEN")
    access_secret = os.environ.get("JOEL_X_ACCESS_TOKEN_SECRET") or os.environ.get("X_ADS_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        print(json.dumps({"success": False, "error": "Missing OAuth credentials"}))
        sys.exit(1)

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def post_tweet(oauth, text: str) -> dict:
    resp = oauth.post("https://api.x.com/2/tweets", json={"text": text})
    resp.raise_for_status()
    return resp.json()


def _get_week_keys(calendar: dict) -> list:
    """Discover all week_N keys in the calendar, sorted."""
    return sorted(k for k in calendar if k.startswith("week_"))


def get_next_post(calendar: dict, posted: set) -> tuple:
    """Find the next unposted item based on current day."""
    today = datetime.now(timezone.utc).strftime("%A").lower()
    week_keys = _get_week_keys(calendar)

    # Try today first, then future days, then wrap around
    for week_key in week_keys:
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            if post_id in posted:
                continue
            post_day = post.get("day", "").lower()
            if post_day == today:
                return post_id, post

    # If nothing for today, get next available
    for week_key in week_keys:
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            if post_id not in posted:
                return post_id, post

    return None, None


def list_posts(calendar: dict, posted: set):
    """List all posts with status."""
    for week_key in _get_week_keys(calendar):
        print(f"\n=== {week_key.upper()} ===")
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            status = "✅" if post_id in posted else "⬜"
            day = post.get("day", "?")
            time = post.get("time", "?")
            ptype = post.get("type", "?")
            text = post.get("text", "")[:80]
            print(f"  {status} [{i:2d}] {day:>9} {time} ({ptype:>15}) {text}...")


def main():
    parser = argparse.ArgumentParser(description="Post from content calendar")
    parser.add_argument("--next", action="store_true", help="Post next scheduled item")
    parser.add_argument("--day", help="Post all items for a specific day")
    parser.add_argument("--index", type=int, help="Post specific index from week_1")
    parser.add_argument("--week", default="week_1", help="Week to use (default: week_1)")
    parser.add_argument("--text", help="Post custom text")
    parser.add_argument("--list", action="store_true", help="List upcoming posts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--reset", action="store_true", help="Reset posted log")
    args = parser.parse_args()

    calendar = load_calendar()
    posted = load_posted_log()

    if args.reset:
        save_posted_log(set())
        print("Posted log reset")
        return

    if args.list:
        list_posts(calendar, posted)
        return

    if args.text:
        if len(args.text) > 280:
            print(json.dumps({"success": False, "error": f"Text exceeds 280 chars ({len(args.text)})"}))
            sys.exit(1)
        if args.dry_run:
            print(json.dumps({"success": True, "dry_run": True, "text": args.text, "chars": len(args.text)}))
            return
        oauth = get_oauth_session()
        result = post_tweet(oauth, args.text)
        tid = result.get("data", {}).get("id", "")
        print(json.dumps({"success": True, "tweet_id": tid, "url": f"https://x.com/JSHorwitz/status/{tid}"}))
        return

    posts_to_send = []

    if args.next:
        post_id, post = get_next_post(calendar, posted)
        if not post:
            print(json.dumps({"success": False, "error": "All posts have been sent"}))
            return
        posts_to_send.append((post_id, post))

    elif args.day:
        week_posts = calendar.get(args.week, [])
        for i, post in enumerate(week_posts):
            post_id = f"{args.week}_{i}"
            if post.get("day", "").lower() == args.day.lower() and post_id not in posted:
                posts_to_send.append((post_id, post))

    elif args.index is not None:
        week_posts = calendar.get(args.week, [])
        if args.index < len(week_posts):
            post_id = f"{args.week}_{args.index}"
            posts_to_send.append((post_id, week_posts[args.index]))

    if not posts_to_send:
        print(json.dumps({"success": False, "error": "No posts to send"}))
        return

    if args.dry_run:
        for post_id, post in posts_to_send:
            print(f"[DRY RUN] {post_id}: {post.get('day')} {post.get('time')} ({post.get('type')})")
            print(f"  {post.get('text')}")
            print(f"  chars: {len(post.get('text', ''))}")
            print()
        return

    oauth = get_oauth_session()
    results = []

    for post_id, post in posts_to_send:
        text = post.get("text", "")
        if len(text) > 280:
            results.append({"post_id": post_id, "status": "skipped", "error": f"Exceeds 280 chars ({len(text)})"})
            continue

        try:
            result = post_tweet(oauth, text)
            tid = result.get("data", {}).get("id", "")
            posted.add(post_id)
            save_posted_log(posted)
            results.append({
                "post_id": post_id,
                "status": "sent",
                "tweet_id": tid,
                "url": f"https://x.com/JSHorwitz/status/{tid}",
                "day": post.get("day"),
                "type": post.get("type"),
            })
        except Exception as e:
            results.append({"post_id": post_id, "status": "failed", "error": str(e)})

    print(json.dumps({"success": True, "results": results}, indent=2))


if __name__ == "__main__":
    main()
