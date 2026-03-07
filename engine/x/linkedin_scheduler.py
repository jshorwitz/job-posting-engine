#!/usr/bin/env python3
"""
LinkedIn content scheduler — posts from linkedin_calendar.json with generated images.

Generates branded images via Imagen, then posts to the SynterAI org page.

Usage:
    python -m engine.x.linkedin_scheduler --next              # Post next scheduled item
    python -m engine.x.linkedin_scheduler --next --dry-run     # Preview without posting
    python -m engine.x.linkedin_scheduler --generate-images    # Pre-generate all images
    python -m engine.x.linkedin_scheduler --list               # Show post status
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from engine.x.time_utils import PACIFIC_TZ, weekday_name

logger = logging.getLogger(__name__)

CALENDAR_PATH = Path(__file__).parent / "linkedin_calendar.json"
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
IMAGES_DIR = _DATA_DIR / "linkedin-images"
POSTED_LOG = _DATA_DIR / ".linkedin_calendar_posted_log.json"


def load_calendar() -> dict:
    with open(CALENDAR_PATH) as f:
        return json.load(f)


def load_posted() -> set:
    if POSTED_LOG.exists():
        with open(POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_posted(posted: set):
    with open(POSTED_LOG, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def _get_week_keys(calendar: dict) -> list:
    return sorted(k for k in calendar if k.startswith("week_"))


def get_next_post(calendar: dict, posted: set, now=None) -> tuple:
    """Find the next unposted LinkedIn post."""
    today = weekday_name(now, PACIFIC_TZ)

    # Try today first
    for wk in _get_week_keys(calendar):
        for i, post in enumerate(calendar.get(wk, [])):
            post_id = f"{wk}_{i}"
            if post_id not in posted and post.get("day", "").lower() == today:
                return post_id, post

    # Then next available
    for wk in _get_week_keys(calendar):
        for i, post in enumerate(calendar.get(wk, [])):
            post_id = f"{wk}_{i}"
            if post_id not in posted:
                return post_id, post

    return None, None


def ensure_image(post_id: str, image_prompt: str) -> str | None:
    """Generate image if it doesn't exist yet. Returns path or None."""
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    image_path = IMAGES_DIR / f"{post_id}.png"

    if image_path.exists():
        logger.info("image already exists: %s", image_path)
        return str(image_path)

    try:
        from engine.x.generate_linkedin_image import generate_image
        result = generate_image(image_prompt, str(IMAGES_DIR), f"{post_id}.png")
        if result and Path(result).exists():
            logger.info("generated image: %s", result)
            return result
        else:
            logger.warning("image generation returned no result for %s", post_id)
            return None
    except Exception as e:
        logger.error("image generation failed for %s: %s", post_id, e)
        return None


def post_linkedin(post_id: str, post: dict, dry_run: bool = False) -> dict:
    """Post a LinkedIn calendar item with optional image."""
    text = post.get("text", "")
    image_prompt = post.get("image_prompt", "")
    has_image = post.get("has_image", False)

    image_path = None
    if has_image and image_prompt:
        image_path = ensure_image(post_id, image_prompt)

    if dry_run:
        return {
            "post_id": post_id, "status": "dry_run",
            "day": post.get("day"), "type": post.get("type"),
            "chars": len(text), "has_image": image_path is not None,
        }

    from engine.x.linkedin_crosspost import get_linkedin_auth, post_to_linkedin, _retry_with_refresh

    token, org_urn = get_linkedin_auth()
    result = _retry_with_refresh(post_to_linkedin, token, org_urn, text, image_path=image_path)

    if result.get("success"):
        posted = load_posted()
        posted.add(post_id)
        save_posted(posted)

    return {
        "post_id": post_id,
        "status": "sent" if result.get("success") else "failed",
        "linkedin_post_id": result.get("post_id", ""),
        "error": result.get("error", ""),
        "day": post.get("day"), "type": post.get("type"),
        "has_image": image_path is not None,
    }


def list_posts(calendar: dict, posted: set):
    for wk in _get_week_keys(calendar):
        print(f"\n=== {wk.upper()} ===")
        for i, post in enumerate(calendar.get(wk, [])):
            post_id = f"{wk}_{i}"
            status = "✅" if post_id in posted else "⬜"
            img = "🖼️" if post.get("has_image") else "  "
            image_exists = "📁" if (IMAGES_DIR / f"{post_id}.png").exists() else "  "
            print(f"  {status} {img}{image_exists} [{i}] {post.get('day',''): >9} ({post.get('type',''):>20}) {post.get('text','')[:70]}...")


def generate_all_images(calendar: dict):
    """Pre-generate all images for the calendar."""
    for wk in _get_week_keys(calendar):
        for i, post in enumerate(calendar.get(wk, [])):
            post_id = f"{wk}_{i}"
            if post.get("has_image") and post.get("image_prompt"):
                print(f"Generating {post_id}...")
                result = ensure_image(post_id, post["image_prompt"])
                print(f"  {'✅ ' + result if result else '❌ failed'}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="LinkedIn content scheduler")
    parser.add_argument("--next", action="store_true", help="Post next scheduled item")
    parser.add_argument("--list", action="store_true", help="List post status")
    parser.add_argument("--generate-images", action="store_true", help="Pre-generate all images")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = parser.parse_args()

    calendar = load_calendar()
    posted = load_posted()

    if args.list:
        list_posts(calendar, posted)
        return

    if args.generate_images:
        generate_all_images(calendar)
        return

    if args.next:
        post_id, post = get_next_post(calendar, posted)
        if not post:
            print(json.dumps({"success": False, "error": "All LinkedIn posts sent"}))
            return
        result = post_linkedin(post_id, post, dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
