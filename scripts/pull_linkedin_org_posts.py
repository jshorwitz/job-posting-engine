#!/usr/bin/env python3
"""
Pull historical posts from the SynterAI LinkedIn organization page.

Saves posts to data/linkedin-historical-posts.json for brand voice analysis.

Usage:
    # Load tokens from Doppler first:
    export LINKEDIN_ACCESS_TOKEN=$(doppler secrets get LINKEDIN_ACCESS_TOKEN --project synter-media --config prd --plain)
    export LINKEDIN_REFRESH_TOKEN=$(doppler secrets get LINKEDIN_REFRESH_TOKEN --project synter-media --config prd --plain)
    export LINKEDIN_CLIENT_ID=86jcu6xeaod28m
    export LINKEDIN_CLIENT_SECRET=$(doppler secrets get LINKEDIN_CLIENT_SECRET --project synter-media --config prd --plain)

    python scripts/pull_linkedin_org_posts.py
    python scripts/pull_linkedin_org_posts.py --limit 200
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_ORG_URN = "urn:li:organization:4803356"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "linkedin-historical-posts.json"


def get_token() -> str:
    """Get a valid LinkedIn access token (refresh if needed)."""
    from engine.x.linkedin_crosspost import get_linkedin_auth
    token, _ = get_linkedin_auth()
    return token


def pull_posts(token: str, org_urn: str, limit: int = 100) -> list[dict]:
    """Pull posts from the LinkedIn organization page using the Posts API."""
    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "LinkedIn-Version": "202510",
        "X-Restli-Protocol-Version": "2.0.0",
    }

    # Use the Posts API with author filter
    posts = []
    start = 0
    page_size = min(limit, 50)

    # URL-encode the org URN for the query parameter
    import urllib.parse
    encoded_urn = urllib.parse.quote(org_urn, safe="")

    with httpx.Client(timeout=30.0) as client:
        while len(posts) < limit:
            url = (
                f"https://api.linkedin.com/rest/posts"
                f"?q=author"
                f"&author={encoded_urn}"
                f"&count={page_size}"
                f"&start={start}"
                f"&sortBy=CREATED"
            )
            resp = client.get(url, headers=headers)

            if resp.status_code == 401:
                print("Token expired. Refreshing...")
                from engine.x.linkedin_crosspost import _refresh_token, _save_token_cache
                refresh = os.environ.get("LINKEDIN_REFRESH_TOKEN", "")
                if not refresh:
                    from engine.x.linkedin_crosspost import _load_token_cache
                    cache = _load_token_cache()
                    if cache:
                        refresh = cache.get("refresh_token", "")
                if refresh:
                    tokens = _refresh_token(refresh)
                    token = tokens["access_token"]
                    _save_token_cache(token, tokens.get("refresh_token", refresh))
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                else:
                    print("No refresh token available.")
                    break

            if resp.status_code != 200:
                print(f"Error {resp.status_code}: {resp.text[:500]}")
                break

            data = resp.json()
            elements = data.get("elements", [])
            if not elements:
                break

            for post in elements:
                posts.append({
                    "id": post.get("id", ""),
                    "text": post.get("commentary", ""),
                    "created_at": post.get("createdAt", 0),
                    "lifecycle_state": post.get("lifecycleState", ""),
                    "visibility": post.get("visibility", ""),
                    "has_content": "content" in post,
                    "content_type": post.get("content", {}).get("media", {}).get("mediaCategory", "")
                        if "content" in post else "",
                    "distribution": post.get("distribution", {}).get("feedDistribution", ""),
                })

            start += page_size
            if len(elements) < page_size:
                break

    return posts


def main():
    parser = argparse.ArgumentParser(description="Pull historical LinkedIn org posts")
    parser.add_argument("--limit", type=int, default=200, help="Max posts to pull")
    parser.add_argument("--org-urn", default=DEFAULT_ORG_URN, help="Organization URN")
    args = parser.parse_args()

    print(f"Pulling up to {args.limit} posts from {args.org_urn}...")
    token = get_token()
    posts = pull_posts(token, args.org_urn, limit=args.limit)

    if not posts:
        print("No posts pulled. Check authentication.")
        sys.exit(1)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({
            "org_urn": args.org_urn,
            "pulled_at": datetime.now(timezone.utc).isoformat(),
            "count": len(posts),
            "posts": posts,
        }, f, indent=2)

    print(f"Saved {len(posts)} posts to {OUTPUT_PATH}")

    # Quick stats
    with_text = [p for p in posts if p.get("text")]
    with_media = [p for p in posts if p.get("has_content")]
    avg_len = sum(len(p.get("text", "")) for p in with_text) / max(len(with_text), 1)
    print(f"  With text: {len(with_text)}")
    print(f"  With media: {len(with_media)}")
    print(f"  Avg text length: {avg_len:.0f} chars")


if __name__ == "__main__":
    main()
