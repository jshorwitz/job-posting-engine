#!/usr/bin/env python3
"""
Scan X for high-engagement tweets relevant to Synter and save candidates for review.

Runs on a schedule (every 4-6 hours). Finds tweets about AI ads, MCP, cross-platform
automation, etc. and saves the best candidates to a JSON file for manual or
agent-assisted engagement (quote retweet, reply, etc).

Usage:
    python x_engagement_scanner.py                        # Run full scan, save candidates
    python x_engagement_scanner.py --review               # Show current candidates
    python x_engagement_scanner.py --engage 0             # Quote-retweet candidate #0
    python x_engagement_scanner.py --engage 0 --comment "this is why we built synter"
    python x_engagement_scanner.py --auto-engage --max 2  # Auto-engage top 2 (careful!)
    python x_engagement_scanner.py --dry-run              # Scan without saving

Auth: Uses X_API_BEARER_TOKEN for search, JOEL_X_* for posting

Output: JSON with scan results or engagement actions
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Use Railway persistent volume if available
_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
CANDIDATES_PATH = _DATA_DIR / ".x_scan_candidates.json"
ENGAGED_LOG = _DATA_DIR / ".x_engaged_log.json"

SEARCH_QUERIES = [
    "AI ad campaign management",
    "MCP advertising",
    "cross-platform ad automation",
    "AI media buying",
    "claude ads",
    "AI agent marketing",
    "AI agents for ads",
    "programmatic AI agents",
    "ad tech MCP server",
    "cursor for marketing",
]

# Templates for auto-generated engagement comments (founder voice)
COMMENT_TEMPLATES = [
    "this is exactly why we built synter\n\nAI agents that actually execute across {platform_count} ad platforms, not just suggest things",
    "been building exactly this\n\ncross-platform ad execution via AI agents\n\nthe hard part isn't the AI, it's the oauth tokens",
    "we shipped this\n\n100+ scripts, 7 platforms, full campaign lifecycle from a chat message\n\nsyntermedia.ai",
]


def get_bearer_token() -> str:
    token = os.environ.get("X_API_BEARER_TOKEN") or os.environ.get("JOEL_X_BEARER_TOKEN")
    if not token:
        print(json.dumps({"success": False, "error": "X_API_BEARER_TOKEN not set"}))
        sys.exit(1)
    return token


def search_tweets(bearer_token: str, query: str, limit: int, min_likes: int, min_followers: int) -> list:
    """Search recent tweets matching query with engagement filters."""
    import httpx

    url = "https://api.x.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "query": f"{query} -is:retweet -is:reply lang:en",
        "max_results": min(limit, 100),
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified,description",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        if response.status_code == 429:
            return []  # silently skip on rate limit during scan
        response.raise_for_status()
        data = response.json()

    tweets = data.get("data", [])
    users_by_id = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

    results = []
    for tweet in tweets:
        metrics = tweet.get("public_metrics", {})
        likes = metrics.get("like_count", 0)
        if likes < min_likes:
            continue

        author = users_by_id.get(tweet.get("author_id", ""), {})
        author_followers = author.get("public_metrics", {}).get("followers_count", 0)
        if author_followers < min_followers:
            continue

        username = author.get("username", "")
        tweet_id = tweet.get("id", "")

        results.append({
            "tweet_id": tweet_id,
            "text": tweet.get("text", ""),
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "created_at": tweet.get("created_at", ""),
            "likes": likes,
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
            "quotes": metrics.get("quote_count", 0),
            "bookmarks": metrics.get("bookmark_count", 0),
            "author_username": username,
            "author_name": author.get("name", ""),
            "author_followers": author_followers,
            "author_verified": author.get("verified", False),
            "author_bio": author.get("description", ""),
            "matched_query": query,
        })

    return results


def load_candidates() -> dict:
    if CANDIDATES_PATH.exists():
        with open(CANDIDATES_PATH) as f:
            return json.load(f)
    return {"scanned_at": None, "candidates": []}


def save_candidates(data: dict):
    with open(CANDIDATES_PATH, "w") as f:
        json.dump(data, f, indent=2)


def load_engaged() -> set:
    if ENGAGED_LOG.exists():
        with open(ENGAGED_LOG) as f:
            return set(json.load(f))
    return set()


def save_engaged(engaged: set):
    with open(ENGAGED_LOG, "w") as f:
        json.dump(sorted(engaged), f, indent=2)


def run_scan(min_likes: int = 20, min_followers: int = 500) -> list:
    """Run all search queries and return deduplicated, ranked candidates."""
    bearer_token = get_bearer_token()
    engaged = load_engaged()
    all_results = []

    for query in SEARCH_QUERIES:
        try:
            results = search_tweets(bearer_token, query, 20, min_likes, min_followers)
            all_results.extend(results)
        except Exception:
            pass  # skip failed queries, log nothing (rate limits are common)

    # Deduplicate by tweet ID, exclude already-engaged
    seen = set()
    unique = []
    for r in all_results:
        tid = r["tweet_id"]
        if tid not in seen and tid not in engaged:
            seen.add(tid)
            unique.append(r)

    # Score: likes * 2 + retweets * 3 + bookmarks * 5 (bookmarks = high intent)
    for r in unique:
        r["score"] = r["likes"] * 2 + r["retweets"] * 3 + r.get("bookmarks", 0) * 5

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique[:30]  # keep top 30


def engage_candidate(candidate: dict, comment: str = None) -> dict:
    """Quote retweet or reply to a candidate tweet."""
    from engine.x.quote_retweet import post_quote_tweet, get_oauth_session

    if not comment:
        template = COMMENT_TEMPLATES[0]
        comment = template.format(platform_count=7)

    if len(comment) > 280:
        return {"success": False, "error": f"comment too long ({len(comment)} chars)"}

    oauth = get_oauth_session()
    result = post_quote_tweet(oauth, comment, candidate["tweet_id"])
    tid = result.get("data", {}).get("id", "")
    method = result.get("method", "quote")

    # Log engagement
    engaged = load_engaged()
    engaged.add(candidate["tweet_id"])
    save_engaged(engaged)

    return {
        "success": True,
        "tweet_id": tid,
        "url": f"https://x.com/JSHorwitz/status/{tid}",
        "method": method,
        "target": candidate["url"],
        "comment": comment,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan X for engagement opportunities")
    parser.add_argument("--review", action="store_true", help="Show current candidates")
    parser.add_argument("--engage", type=int, help="Engage with candidate at index N")
    parser.add_argument("--comment", help="Custom comment for engagement")
    parser.add_argument("--auto-engage", action="store_true", help="Auto-engage top candidates")
    parser.add_argument("--max", type=int, default=1, help="Max auto-engagements (default 1)")
    parser.add_argument("--min-likes", type=int, default=20, help="Min likes filter (default 20)")
    parser.add_argument("--min-followers", type=int, default=500, help="Min author followers (default 500)")
    parser.add_argument("--dry-run", action="store_true", help="Scan without saving")
    args = parser.parse_args()

    if args.review:
        data = load_candidates()
        print(json.dumps(data, indent=2))
        return

    if args.engage is not None:
        data = load_candidates()
        candidates = data.get("candidates", [])
        if args.engage >= len(candidates):
            print(json.dumps({"success": False, "error": f"index {args.engage} out of range (have {len(candidates)})"}))
            sys.exit(1)
        result = engage_candidate(candidates[args.engage], args.comment)
        print(json.dumps(result, indent=2))
        return

    # Run scan
    candidates = run_scan(args.min_likes, args.min_followers)

    if args.auto_engage and not args.dry_run:
        results = []
        for candidate in candidates[:args.max]:
            result = engage_candidate(candidate, args.comment)
            results.append(result)
        print(json.dumps({"success": True, "engaged": results}, indent=2))
        return

    scan_data = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "queries": SEARCH_QUERIES,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    if not args.dry_run:
        save_candidates(scan_data)

    print(json.dumps({
        "success": True,
        "dry_run": args.dry_run,
        "scanned_at": scan_data["scanned_at"],
        "candidate_count": len(candidates),
        "top_5": [
            {
                "url": c["url"],
                "likes": c["likes"],
                "author": f"@{c['author_username']}",
                "score": c["score"],
                "text": c["text"][:100],
            }
            for c in candidates[:5]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
