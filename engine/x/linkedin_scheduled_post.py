#!/usr/bin/env python3
"""
Post from the LinkedIn content calendar or run as a cron job to auto-post.

Usage:
    python -m engine.x.linkedin_scheduled_post --next                    # Post next unposted item for today
    python -m engine.x.linkedin_scheduled_post --list                    # Show all posts with status
    python -m engine.x.linkedin_scheduled_post --index 0                 # Post specific index from week_1
    python -m engine.x.linkedin_scheduled_post --week week_2 --index 1   # Post index 1 from week_2
    python -m engine.x.linkedin_scheduled_post --dry-run --next          # Preview without posting
    python -m engine.x.linkedin_scheduled_post --generate-images         # Pre-generate all images
    python -m engine.x.linkedin_scheduled_post --reset                   # Clear posted log

Auth: Uses LinkedIn OAuth via direct credentials (env vars).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.x.linkedin_generate_image import generate_image
from engine.x.linkedin_org_post import post_to_linkedin_native
from engine.x.time_utils import PACIFIC_TZ, weekday_name


CALENDAR_PATH = Path(__file__).parent / "linkedin_calendar.json"

# Use Railway persistent volume if available, otherwise local
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
POSTED_LOG = _DATA_DIR / ".linkedin_native_posted_log.json"

LINKEDIN_DAYS = ["tuesday", "wednesday", "thursday"]


def load_calendar() -> dict:
    with open(CALENDAR_PATH) as f:
        return json.load(f)


def load_posted_log() -> dict:
    """Load posted log. Returns dict mapping post_id -> post metadata."""
    if POSTED_LOG.exists():
        with open(POSTED_LOG) as f:
            data = json.load(f)
            # Support both legacy set format (list of strings) and dict format
            if isinstance(data, list):
                return {pid: {"posted_at": None} for pid in data}
            return data
    return {}


def save_posted_log(posted: dict):
    with open(POSTED_LOG, "w") as f:
        json.dump(posted, f, indent=2)


def _get_week_keys(calendar: dict) -> list:
    """Discover all week_N keys in the calendar, sorted."""
    return sorted(k for k in calendar if k.startswith("week_"))


def get_next_post(calendar: dict, posted: dict, now=None) -> tuple:
    """Find the next unposted item matching today's day (Tue/Wed/Thu)."""
    today = weekday_name(now, PACIFIC_TZ)
    week_keys = _get_week_keys(calendar)

    # Try today first
    if today in LINKEDIN_DAYS:
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


def list_posts(calendar: dict, posted: dict):
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
            has_image = "🖼️" if post.get("image_prompt") else "  "
            text = post.get("text", "")[:80]
            print(f"  {status} {has_image} [{i:2d}] {day:>9} {time} ({ptype:>20}) {text}...")


def generate_image_for_post(post: dict) -> str | None:
    """Generate an image for a post if it has an image_prompt. Returns image path or None."""
    image_prompt = post.get("image_prompt")
    if not image_prompt:
        return None

    try:
        result = generate_image(prompt=image_prompt)
        if isinstance(result, dict) and result.get("success"):
            return result.get("image_path")
        elif isinstance(result, str):
            return result
        else:
            print(f"  ⚠️  Image generation returned: {result}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"  ⚠️  Image generation failed: {e}", file=sys.stderr)
        return None


def generate_all_images(calendar: dict):
    """Pre-generate all images from the calendar without posting."""
    results = []
    for week_key in _get_week_keys(calendar):
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            image_prompt = post.get("image_prompt")
            if not image_prompt:
                continue

            print(f"  Generating image for {post_id}: {image_prompt[:60]}...")
            image_path = generate_image_for_post(post)
            status = "generated" if image_path else "failed"
            results.append({
                "post_id": post_id,
                "status": status,
                "image_path": image_path,
                "prompt": image_prompt[:80],
            })

    print(json.dumps({"success": True, "images": results}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Post from LinkedIn content calendar")
    parser.add_argument("--next", action="store_true", help="Post next scheduled item for today")
    parser.add_argument("--index", type=int, help="Post specific index from a week")
    parser.add_argument("--week", default="week_1", help="Week to use (default: week_1)")
    parser.add_argument("--list", action="store_true", help="List all posts with status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--reset", action="store_true", help="Reset posted log")
    parser.add_argument("--generate-images", action="store_true", help="Pre-generate all images")
    args = parser.parse_args()

    calendar = load_calendar()
    posted = load_posted_log()

    if args.reset:
        save_posted_log({})
        print(json.dumps({"success": True, "message": "Posted log reset"}))
        return

    if args.list:
        list_posts(calendar, posted)
        return

    if args.generate_images:
        generate_all_images(calendar)
        return

    posts_to_send = []

    if args.next:
        post_id, post = get_next_post(calendar, posted)
        if not post:
            print(json.dumps({"success": False, "error": "All posts have been sent"}))
            return
        posts_to_send.append((post_id, post))

    elif args.index is not None:
        week_posts = calendar.get(args.week, [])
        if args.index < len(week_posts):
            post_id = f"{args.week}_{args.index}"
            posts_to_send.append((post_id, week_posts[args.index]))
        else:
            print(json.dumps({"success": False, "error": f"Index {args.index} out of range for {args.week} ({len(week_posts)} posts)"}))
            return

    if not posts_to_send:
        print(json.dumps({"success": False, "error": "No posts to send. Use --next, --index, or --list"}))
        return

    if args.dry_run:
        for post_id, post in posts_to_send:
            has_image = "🖼️ " if post.get("image_prompt") else ""
            print(f"[DRY RUN] {post_id}: {post.get('day')} {post.get('time')} ({post.get('type')})")
            print(f"  {has_image}{post.get('text', '')[:200]}")
            if post.get("image_prompt"):
                print(f"  Image prompt: {post['image_prompt'][:100]}")
            print(f"  chars: {len(post.get('text', ''))}")
            print()
        return

    results = []

    for post_id, post in posts_to_send:
        text = post.get("text", "")

        try:
            # Step 1: Generate image if needed
            image_path = generate_image_for_post(post)

            # Step 2: Post to LinkedIn
            result = post_to_linkedin_native(text, image_path)

            if result.get("success"):
                posted[post_id] = {
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "post_urn": result.get("post_urn"),
                    "image_path": image_path,
                }
                save_posted_log(posted)
                results.append({
                    "post_id": post_id,
                    "status": "sent",
                    "post_urn": result.get("post_urn"),
                    "day": post.get("day"),
                    "type": post.get("type"),
                    "had_image": image_path is not None,
                })
            else:
                results.append({
                    "post_id": post_id,
                    "status": "failed",
                    "error": result.get("error", "Unknown error"),
                })
        except Exception as e:
            results.append({"post_id": post_id, "status": "failed", "error": str(e)})

    print(json.dumps({"success": True, "results": results}, indent=2))


if __name__ == "__main__":
    main()
