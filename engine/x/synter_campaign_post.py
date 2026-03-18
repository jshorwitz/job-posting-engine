#!/usr/bin/env python3
"""
Post Synter marketing campaign content to LinkedIn (org page) and X (@synterai).

Each campaign post is published to both platforms with pre-made ad images.
Posts are scheduled every Tuesday at 9:00 AM PT via the scheduler.

Usage:
    python -m engine.x.synter_campaign_post --next                # Post next unposted item
    python -m engine.x.synter_campaign_post --next --dry-run      # Preview without posting
    python -m engine.x.synter_campaign_post --list                # Show all posts with status
    python -m engine.x.synter_campaign_post --id campaign_w1      # Post specific campaign post
    python -m engine.x.synter_campaign_post --reset               # Clear posted log

Auth:
    LinkedIn: Uses LinkedIn OAuth via direct credentials (env vars).
    X (@synterai): Uses X_ADS_CONSUMER_KEY/SECRET + X_ADS_ACCESS_TOKEN/SECRET (OAuth 1.0a).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CALENDAR_PATH = Path(__file__).parent / "synter_campaign_calendar.json"
IMAGES_DIR = Path(__file__).parent / "synter-campaign-images"

# Use Railway persistent volume if available, otherwise local
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
POSTED_LOG = _DATA_DIR / ".synter_campaign_posted_log.json"


def load_calendar() -> dict:
    with open(CALENDAR_PATH) as f:
        return json.load(f)


def load_posted() -> dict:
    """Load posted log. Returns dict mapping post_id -> metadata."""
    if POSTED_LOG.exists():
        with open(POSTED_LOG) as f:
            return json.load(f)
    return {}


def save_posted(posted: dict):
    with open(POSTED_LOG, "w") as f:
        json.dump(posted, f, indent=2)


def get_next_post(calendar: dict, posted: dict) -> dict | None:
    """Find the next unposted campaign post (by date order)."""
    for post in calendar["posts"]:
        post_id = post["id"]
        if post_id not in posted:
            return post
    return None


def get_post_by_id(calendar: dict, post_id: str) -> dict | None:
    for post in calendar["posts"]:
        if post["id"] == post_id:
            return post
    return None


def _get_image_path(post: dict) -> str | None:
    """Resolve the image path for a campaign post."""
    image_file = post.get("image")
    if not image_file:
        return None
    image_path = IMAGES_DIR / image_file
    if image_path.is_file():
        return str(image_path)
    logger.warning("image not found: %s", image_path)
    return None


def _post_to_linkedin(text: str, image_path: str | None) -> dict:
    """Post to Synter LinkedIn org page."""
    try:
        from engine.x.linkedin_org_post import post_to_linkedin_native
        return post_to_linkedin_native(text, image_path)
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_synterai_oauth():
    """Get OAuth 1.0a session for @synterai (X_ADS credentials)."""
    from requests_oauthlib import OAuth1Session

    consumer_key = os.environ.get("X_ADS_CONSUMER_KEY")
    consumer_secret = os.environ.get("X_ADS_CONSUMER_SECRET")
    access_token = os.environ.get("X_ADS_ACCESS_TOKEN")
    access_secret = os.environ.get("X_ADS_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        raise ValueError("Missing X_ADS_* OAuth credentials for @synterai")

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def _upload_media_x(oauth, image_path: str) -> str:
    """Upload image to X via v1.1 media/upload endpoint. Returns media_id_string."""
    import mimetypes

    media_type = mimetypes.guess_type(image_path)[0] or "image/png"

    # INIT
    file_size = os.path.getsize(image_path)
    init_resp = oauth.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        data={
            "command": "INIT",
            "total_bytes": file_size,
            "media_type": media_type,
        },
    )
    init_resp.raise_for_status()
    media_id = init_resp.json()["media_id_string"]

    # APPEND
    with open(image_path, "rb") as f:
        append_resp = oauth.post(
            "https://upload.twitter.com/1.1/media/upload.json",
            data={"command": "APPEND", "media_id": media_id, "segment_index": 0},
            files={"media": f},
        )
        append_resp.raise_for_status()

    # FINALIZE
    finalize_resp = oauth.post(
        "https://upload.twitter.com/1.1/media/upload.json",
        data={"command": "FINALIZE", "media_id": media_id},
    )
    finalize_resp.raise_for_status()

    return media_id


def _post_to_x(text: str, image_path: str | None) -> dict:
    """Post to X as @synterai with optional image."""
    try:
        oauth = _get_synterai_oauth()

        body = {"text": text}

        # Upload image if provided
        if image_path:
            try:
                media_id = _upload_media_x(oauth, image_path)
                body["media"] = {"media_ids": [media_id]}
            except Exception as e:
                logger.warning("X image upload failed, posting text-only: %s", e)

        resp = oauth.post("https://api.x.com/2/tweets", json=body)
        resp.raise_for_status()
        data = resp.json()
        tweet_id = data.get("data", {}).get("id", "")
        return {
            "success": True,
            "tweet_id": tweet_id,
            "url": f"https://x.com/synterai/status/{tweet_id}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def post_campaign(post: dict, dry_run: bool = False) -> dict:
    """Post a campaign item to both LinkedIn and X.

    Returns dict with results for each platform.
    """
    post_id = post["id"]
    image_path = _get_image_path(post)

    if dry_run:
        return {
            "post_id": post_id,
            "status": "dry_run",
            "date": post.get("date"),
            "pattern": post.get("pattern"),
            "image": post.get("image"),
            "image_found": image_path is not None,
            "linkedin_chars": len(post.get("linkedin_text", "")),
            "x_chars": len(post.get("x_text", "")),
        }

    results = {"post_id": post_id, "date": post.get("date"), "pattern": post.get("pattern")}

    # Post to LinkedIn
    li_result = _post_to_linkedin(post["linkedin_text"], image_path)
    results["linkedin"] = {
        "success": li_result.get("success", False),
        "post_urn": li_result.get("post_urn", ""),
        "url": li_result.get("url", ""),
        "error": li_result.get("error", ""),
    }

    # Post to X (@synterai)
    x_result = _post_to_x(post["x_text"], image_path)
    results["x"] = {
        "success": x_result.get("success", False),
        "tweet_id": x_result.get("tweet_id", ""),
        "url": x_result.get("url", ""),
        "error": x_result.get("error", ""),
    }

    # Mark as posted if at least one platform succeeded
    if li_result.get("success") or x_result.get("success"):
        posted = load_posted()
        posted[post_id] = {
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "linkedin_success": li_result.get("success", False),
            "linkedin_post_urn": li_result.get("post_urn", ""),
            "x_success": x_result.get("success", False),
            "x_tweet_id": x_result.get("tweet_id", ""),
        }
        save_posted(posted)

    results["status"] = "sent"
    return results


def list_posts(calendar: dict, posted: dict):
    """List all campaign posts with status."""
    print("\n=== SYNTER CAMPAIGN CALENDAR ===")
    print(f"Platforms: LinkedIn (Synter org) + X (@synterai)\n")
    for post in calendar["posts"]:
        post_id = post["id"]
        posted_info = posted.get(post_id)
        if posted_info:
            li_ok = "LI:✅" if posted_info.get("linkedin_success") else "LI:❌"
            x_ok = "X:✅" if posted_info.get("x_success") else "X:❌"
            status = f"✅ {li_ok} {x_ok}"
        else:
            status = "⬜"
        image_exists = "🖼️" if (IMAGES_DIR / post.get("image", "")).is_file() else "  "
        print(f"  {status} {image_exists} {post['date']} ({post['pattern'][:35]:>35})")
        print(f"         X: {post['x_text'][:70]}...")
        print()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Synter campaign poster (LinkedIn + X)")
    parser.add_argument("--next", action="store_true", help="Post next unposted campaign item")
    parser.add_argument("--id", help="Post a specific campaign post by ID")
    parser.add_argument("--list", action="store_true", help="List all posts with status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--reset", action="store_true", help="Reset posted log")
    args = parser.parse_args()

    calendar = load_calendar()
    posted = load_posted()

    if args.reset:
        save_posted({})
        print(json.dumps({"success": True, "message": "Campaign posted log reset"}))
        return

    if args.list:
        list_posts(calendar, posted)
        return

    post = None
    if args.next:
        post = get_next_post(calendar, posted)
        if not post:
            print(json.dumps({"success": False, "error": "All campaign posts have been sent"}))
            return
    elif args.id:
        post = get_post_by_id(calendar, args.id)
        if not post:
            print(json.dumps({"success": False, "error": f"Post ID '{args.id}' not found"}))
            return

    if not post:
        parser.print_help()
        return

    result = post_campaign(post, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
