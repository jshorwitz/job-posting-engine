#!/usr/bin/env python3
"""
Cross-post X content to LinkedIn personal profile.

Adapts X-style posts for LinkedIn's format:
- X posts are ≤280 chars, lowercase, punchy
- LinkedIn allows 3000 chars — we expand with context, hashtags, and CTA

Usage:
    python -m engine.x.linkedin_crosspost --next              # Cross-post next unposted item
    python -m engine.x.linkedin_crosspost --index 0           # Cross-post specific item
    python -m engine.x.linkedin_crosspost --text "custom"     # Post custom text
    python -m engine.x.linkedin_crosspost --dry-run --next    # Preview without posting

Auth: Uses LINKEDIN_PERSONAL_ACCESS_TOKEN (OAuth 2.0 w_member_social scope)
      and LINKEDIN_PERSON_URN (urn:li:person:xxx)

Output: JSON with post details
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Persistence
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
LINKEDIN_POSTED_LOG = _DATA_DIR / ".linkedin_posted_log.json"

# Post types that are good for LinkedIn cross-posting
# (skip casual weekend posts and short questions)
CROSSPOST_TYPES = {"hot_take", "breakdown", "build_in_public", "article"}

# Hashtags to append (LinkedIn loves these)
DEFAULT_HASHTAGS = [
    "AIAgents", "AdTech", "DigitalMarketing", "PaidMedia",
    "MarketingAutomation", "StartupLife",
]


def get_linkedin_auth() -> tuple[str, str]:
    """Get LinkedIn access token and person URN."""
    token = os.environ.get("LINKEDIN_PERSONAL_ACCESS_TOKEN")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN")

    if not token:
        print(json.dumps({"success": False, "error": "LINKEDIN_PERSONAL_ACCESS_TOKEN not set"}))
        sys.exit(1)
    if not person_urn:
        print(json.dumps({"success": False, "error": "LINKEDIN_PERSON_URN not set (e.g. urn:li:person:abc123)"}))
        sys.exit(1)

    return token, person_urn


def load_linkedin_posted() -> set:
    if LINKEDIN_POSTED_LOG.exists():
        with open(LINKEDIN_POSTED_LOG) as f:
            return set(json.load(f))
    return set()


def save_linkedin_posted(posted: set):
    with open(LINKEDIN_POSTED_LOG, "w") as f:
        json.dump(sorted(posted), f, indent=2)


def adapt_for_linkedin(post: dict) -> str:
    """Adapt an X-style post for LinkedIn.

    LinkedIn allows 3000 chars, so we:
    - Keep the original text (it's already good)
    - Replace > arrows with bullet unicode for readability
    - Add hashtags at the end
    """
    text = post.get("text", "")

    # Replace > arrows with bullet points for LinkedIn readability
    lines = text.split("\n")
    adapted_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> "):
            adapted_lines.append("→ " + stripped[2:])
        else:
            adapted_lines.append(line)

    adapted = "\n".join(adapted_lines)

    # Add hashtags
    hashtags = " ".join(f"#{h}" for h in DEFAULT_HASHTAGS[:4])
    adapted = f"{adapted}\n\n{hashtags}"

    return adapted


def post_to_linkedin(token: str, person_urn: str, text: str) -> dict:
    """Post text content to LinkedIn personal profile via UGC Posts API."""
    import httpx

    url = "https://api.linkedin.com/v2/ugcPosts"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    body = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=body)

        if response.status_code == 401:
            return {"success": False, "error": "LinkedIn token expired or invalid — regenerate with w_member_social scope"}

        if response.status_code == 403:
            return {"success": False, "error": "LinkedIn token missing w_member_social scope"}

        response.raise_for_status()

        # LinkedIn returns the post URN in the id field
        post_id = response.headers.get("X-RestLi-Id", response.headers.get("x-restli-id", ""))
        if not post_id:
            data = response.json()
            post_id = data.get("id", "")

        return {"success": True, "post_id": post_id}


def get_next_crosspost(calendar: dict, posted: set, linkedin_posted: set) -> tuple:
    """Find the next item that's been posted to X but not yet to LinkedIn."""
    from engine.x.scheduled_post import _get_week_keys

    for week_key in _get_week_keys(calendar):
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            post_type = post.get("type", "")

            # Only cross-post types that work on LinkedIn
            if post_type not in CROSSPOST_TYPES:
                continue

            # Must be posted to X already, but not yet to LinkedIn
            if post_id in posted and post_id not in linkedin_posted:
                return post_id, post

    return None, None


def main():
    parser = argparse.ArgumentParser(description="Cross-post X content to LinkedIn")
    parser.add_argument("--next", action="store_true", help="Cross-post next eligible item")
    parser.add_argument("--index", type=int, help="Cross-post specific index")
    parser.add_argument("--week", default="week_1", help="Week to use with --index")
    parser.add_argument("--text", help="Post custom text to LinkedIn")
    parser.add_argument("--all-pending", action="store_true", help="Cross-post all pending items")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = parser.parse_args()

    if args.text:
        if len(args.text) > 3000:
            print(json.dumps({"success": False, "error": f"Text exceeds 3000 chars ({len(args.text)})"}))
            sys.exit(1)
        if args.dry_run:
            print(json.dumps({"success": True, "dry_run": True, "text": args.text, "chars": len(args.text)}))
            return
        token, person_urn = get_linkedin_auth()
        result = post_to_linkedin(token, person_urn, args.text)
        print(json.dumps(result, indent=2))
        return

    from engine.x.scheduled_post import load_calendar, load_posted_log

    calendar = load_calendar()
    x_posted = load_posted_log()
    li_posted = load_linkedin_posted()

    posts_to_send = []

    if args.next:
        post_id, post = get_next_crosspost(calendar, x_posted, li_posted)
        if not post:
            print(json.dumps({"success": False, "error": "No pending cross-posts (all eligible items already posted to LinkedIn)"}))
            return
        posts_to_send.append((post_id, post))

    elif args.all_pending:
        from engine.x.scheduled_post import _get_week_keys
        for week_key in _get_week_keys(calendar):
            posts = calendar.get(week_key, [])
            for i, post in enumerate(posts):
                post_id = f"{week_key}_{i}"
                if post.get("type", "") in CROSSPOST_TYPES and post_id in x_posted and post_id not in li_posted:
                    posts_to_send.append((post_id, post))

    elif args.index is not None:
        week_posts = calendar.get(args.week, [])
        if args.index < len(week_posts):
            post_id = f"{args.week}_{args.index}"
            posts_to_send.append((post_id, week_posts[args.index]))

    if not posts_to_send:
        print(json.dumps({"success": False, "error": "No posts to cross-post"}))
        return

    if args.dry_run:
        for post_id, post in posts_to_send:
            adapted = adapt_for_linkedin(post)
            print(f"[DRY RUN] {post_id}: {post.get('day')} ({post.get('type')})")
            print(f"  LinkedIn text ({len(adapted)} chars):")
            print(f"  {adapted}")
            print()
        return

    token, person_urn = get_linkedin_auth()
    results = []

    for post_id, post in posts_to_send:
        adapted = adapt_for_linkedin(post)

        try:
            result = post_to_linkedin(token, person_urn, adapted)
            if result.get("success"):
                li_posted.add(post_id)
                save_linkedin_posted(li_posted)
                results.append({
                    "post_id": post_id, "status": "sent",
                    "linkedin_post_id": result.get("post_id", ""),
                    "day": post.get("day"), "type": post.get("type"),
                    "chars": len(adapted),
                })
            else:
                results.append({"post_id": post_id, "status": "failed", "error": result.get("error", "")})
        except Exception as e:
            results.append({"post_id": post_id, "status": "failed", "error": str(e)})

    print(json.dumps({"success": True, "results": results}, indent=2))


if __name__ == "__main__":
    main()
