#!/usr/bin/env python3
"""
Cross-post X content to LinkedIn as SynterAI organization page.

Adapts X-style posts for LinkedIn's format:
- X posts are ≤280 chars, lowercase, punchy
- LinkedIn allows 3000 chars — we expand with context, hashtags, and CTA

Auth: Direct LinkedIn OAuth 2.0 via Synter app credentials.
      Posts as urn:li:organization:4803356 (SynterAI) via w_organization_social scope.
      Auto-refreshes token when expired using refresh_token.

Env vars:
    LINKEDIN_ACCESS_TOKEN   - OAuth 2.0 access token
    LINKEDIN_REFRESH_TOKEN  - OAuth 2.0 refresh token (for auto-renewal)
    LINKEDIN_CLIENT_ID      - Synter app client ID
    LINKEDIN_CLIENT_SECRET  - Synter app client secret
    LINKEDIN_ORG_URN        - Org URN (default: urn:li:organization:4803356)

Usage:
    python -m engine.x.linkedin_crosspost --next
    python -m engine.x.linkedin_crosspost --text "custom post"
    python -m engine.x.linkedin_crosspost --dry-run --next
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Persistence
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
LINKEDIN_POSTED_LOG = _DATA_DIR / ".linkedin_posted_log.json"
LINKEDIN_TOKEN_CACHE = _DATA_DIR / ".linkedin_token_cache.json"

# SynterAI org page
DEFAULT_ORG_URN = "urn:li:organization:4803356"

# Post types that are good for LinkedIn cross-posting
CROSSPOST_TYPES = {"hot_take", "breakdown", "build_in_public", "article"}

# Hashtags to append
DEFAULT_HASHTAGS = [
    "AIAgents", "AdTech", "DigitalMarketing", "PaidMedia",
    "MarketingAutomation", "StartupLife",
]


def _refresh_token(refresh_token: str) -> dict:
    """Exchange refresh token for a new access token."""
    import httpx

    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise RuntimeError("LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET required for token refresh")

    resp = httpx.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def _save_token_cache(access_token: str, refresh_token: str):
    """Cache refreshed tokens to disk so we don't re-read stale env vars."""
    try:
        with open(LINKEDIN_TOKEN_CACHE, "w") as f:
            json.dump({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            }, f)
    except Exception as e:
        logger.warning("failed to save token cache: %s", e)


def _load_token_cache() -> dict | None:
    """Load cached tokens (from a previous refresh)."""
    try:
        if LINKEDIN_TOKEN_CACHE.exists():
            with open(LINKEDIN_TOKEN_CACHE) as f:
                return json.load(f)
    except Exception:
        pass
    return None


def get_linkedin_auth() -> tuple[str, str]:
    """Get LinkedIn access token and org URN.

    Priority:
    1. Cached token from disk (from a previous refresh)
    2. LINKEDIN_ACCESS_TOKEN env var
    3. Refresh using LINKEDIN_REFRESH_TOKEN if access token fails
    """
    # Check disk cache first (may have a fresher token from a previous refresh)
    cache = _load_token_cache()
    token = cache["access_token"] if cache else ""

    if not token:
        token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")

    if not token:
        # Try to get one via refresh
        refresh = os.environ.get("LINKEDIN_REFRESH_TOKEN", "")
        if refresh:
            logger.info("no access token, attempting refresh...")
            tokens = _refresh_token(refresh)
            token = tokens["access_token"]
            new_refresh = tokens.get("refresh_token", refresh)
            _save_token_cache(token, new_refresh)
        else:
            raise RuntimeError(
                "Set LINKEDIN_ACCESS_TOKEN or LINKEDIN_REFRESH_TOKEN. "
                "Run: python scripts/linkedin_auth.py"
            )

    org_urn = os.environ.get("LINKEDIN_ORG_URN", DEFAULT_ORG_URN)
    return token, org_urn


def _retry_with_refresh(func, *args, **kwargs) -> dict:
    """Call func; if 401, refresh token and retry once."""
    result = func(*args, **kwargs)

    if not result.get("success") and "401" in str(result.get("error", "")):
        refresh = os.environ.get("LINKEDIN_REFRESH_TOKEN", "")
        cache = _load_token_cache()
        if cache and cache.get("refresh_token"):
            refresh = cache["refresh_token"]

        if refresh:
            logger.info("got 401, refreshing LinkedIn token...")
            try:
                tokens = _refresh_token(refresh)
                new_token = tokens["access_token"]
                new_refresh = tokens.get("refresh_token", refresh)
                _save_token_cache(new_token, new_refresh)

                # Retry with new token
                # Replace token in args (it's the first positional arg)
                new_args = (new_token,) + args[1:]
                result = func(*new_args, **kwargs)
            except Exception as e:
                logger.error("token refresh failed: %s", e)
                result = {"success": False, "error": f"Token refresh failed: {e}. Re-run: python scripts/linkedin_auth.py"}

    return result


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

    lines = text.split("\n")
    adapted_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("> "):
            adapted_lines.append("→ " + stripped[2:])
        else:
            adapted_lines.append(line)

    adapted = "\n".join(adapted_lines)

    hashtags = " ".join(f"#{h}" for h in DEFAULT_HASHTAGS[:4])
    adapted = f"{adapted}\n\n{hashtags}"

    return adapted


def post_to_linkedin(token: str, org_urn: str, text: str) -> dict:
    """Post text content to LinkedIn organization page via REST Posts API."""
    import httpx

    url = "https://api.linkedin.com/rest/posts"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202510",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    body = {
        "author": org_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, headers=headers, json=body)

        if response.status_code == 401:
            return {"success": False, "error": "401: LinkedIn token expired"}

        if response.status_code == 403:
            return {"success": False, "error": f"403: not admin of {org_urn} or missing w_organization_social scope"}

        if response.status_code >= 400:
            error_body = response.text[:500]
            return {"success": False, "error": f"LinkedIn {response.status_code}: {error_body}"}

        post_id = response.headers.get("x-restli-id", response.headers.get("X-RestLi-Id", ""))
        return {"success": True, "post_id": post_id, "org": org_urn}


def get_next_crosspost(calendar: dict, posted: set, linkedin_posted: set) -> tuple:
    """Find the next item that's been posted to X but not yet to LinkedIn."""
    from engine.x.scheduled_post import _get_week_keys

    for week_key in _get_week_keys(calendar):
        posts = calendar.get(week_key, [])
        for i, post in enumerate(posts):
            post_id = f"{week_key}_{i}"
            post_type = post.get("type", "")

            if post_type not in CROSSPOST_TYPES:
                continue

            if post_id in posted and post_id not in linkedin_posted:
                return post_id, post

    return None, None


def main():
    parser = argparse.ArgumentParser(description="Cross-post X content to LinkedIn org page")
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
        token, org_urn = get_linkedin_auth()
        result = _retry_with_refresh(post_to_linkedin, token, org_urn, args.text)
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
            print(json.dumps({"success": False, "error": "No pending cross-posts"}))
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

    token, org_urn = get_linkedin_auth()
    results = []

    for post_id, post in posts_to_send:
        adapted = adapt_for_linkedin(post)

        try:
            result = _retry_with_refresh(post_to_linkedin, token, org_urn, adapted)
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
