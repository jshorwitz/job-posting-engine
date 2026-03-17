#!/usr/bin/env python3
"""
Find relevant tweets and quote retweet them with Synter commentary.

Usage:
    python x_quote_retweet.py --search "AI advertising" --comment "we built this"
    python x_quote_retweet.py --tweet-id 2028560985985036743 --comment "this is why we built synter"
    python x_quote_retweet.py --search "MCP AI agents" --min-likes 50 --dry-run
    python x_quote_retweet.py --list-targets                    # Show saved targets
    python x_quote_retweet.py --add-target @aakashgupta         # Monitor this account

Arguments:
    --search: Search query to find relevant tweets
    --tweet-id: Specific tweet ID to quote retweet
    --tweet-url: Tweet URL (extracts ID automatically)
    --comment: Your quote retweet text (max 280 chars)
    --min-likes: Minimum like count to filter results (default 20)
    --min-followers: Minimum author follower count (default 500)
    --limit: Max search results to scan (default 20)
    --dry-run: Preview matches without posting
    --list-targets: Show monitored accounts
    --add-target: Add an account to monitor

Auth: Uses JOEL_X_* credentials (posts from @JSHorwitz)

Output: JSON with matched tweets or posted quote retweet
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


TARGETS_PATH = Path(__file__).parent / ".x_quote_targets.json"
BEARER_TOKEN_KEY = "X_BEARER_TOKEN"

# Searches that surface Synter-relevant content
DEFAULT_SEARCHES = [
    "AI ad campaign management",
    "MCP advertising",
    "cross-platform ad automation",
    "AI media buying",
    "claude ads",
    "AI agent marketing",
]


def get_bearer_token() -> str:
    token = os.environ.get(BEARER_TOKEN_KEY) or os.environ.get("X_API_BEARER_TOKEN") or os.environ.get("JOEL_X_BEARER_TOKEN")
    if not token:
        print(json.dumps({"success": False, "error": f"{BEARER_TOKEN_KEY} not set"}))
        sys.exit(1)
    return token


def get_oauth_session():
    """Get OAuth 1.0a session for posting (Joel's account)."""
    from requests_oauthlib import OAuth1Session

    consumer_key = os.environ.get("JOEL_X_CONSUMER_KEY") or os.environ.get("X_ADS_CONSUMER_KEY")
    consumer_secret = os.environ.get("JOEL_X_CONSUMER_SECRET") or os.environ.get("X_ADS_CONSUMER_SECRET")
    access_token = os.environ.get("JOEL_X_ACCESS_TOKEN") or os.environ.get("X_ADS_ACCESS_TOKEN")
    access_secret = os.environ.get("JOEL_X_ACCESS_TOKEN_SECRET") or os.environ.get("X_ADS_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        print(json.dumps({"success": False, "error": "Missing OAuth credentials for posting"}))
        sys.exit(1)

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def search_tweets(bearer_token: str, query: str, limit: int, min_likes: int, min_followers: int) -> list:
    """Search recent tweets matching query with engagement filters."""
    import httpx

    url = "https://api.x.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "query": f"{query} -is:retweet -is:reply lang:en",
        "max_results": min(limit, 100),
        "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified,description",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)

        if response.status_code == 429:
            print(json.dumps({"success": False, "error": "rate limited on search endpoint"}))
            sys.exit(1)

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
        })

    results.sort(key=lambda x: x["likes"], reverse=True)
    return results


def post_quote_tweet(oauth, text: str, quote_tweet_id: str) -> dict:
    """Post a quote retweet. Falls back to reply if quoting is restricted."""
    # Try quote first
    body = {"text": text, "quote_tweet_id": quote_tweet_id}
    resp = oauth.post("https://api.x.com/2/tweets", json=body)

    if resp.status_code in (200, 201):
        return {"data": resp.json().get("data", {}), "method": "quote"}

    # If quoting is restricted, fall back to reply
    error_body = {}
    try:
        error_body = resp.json()
    except Exception:
        pass

    detail = error_body.get("detail", "")
    if "Quoting this post is not allowed" in detail:
        # Fall back to reply
        reply_body = {"text": text, "reply": {"in_reply_to_tweet_id": quote_tweet_id}}
        reply_resp = oauth.post("https://api.x.com/2/tweets", json=reply_body)

        if reply_resp.status_code in (200, 201):
            return {"data": reply_resp.json().get("data", {}), "method": "reply"}

        # Reply also restricted, post as standalone mention with tweet URL
        # Extract username from tweet for @mention
        tweet_url = f"https://x.com/i/status/{quote_tweet_id}"
        standalone_text = f"{text}\n\n{tweet_url}"
        if len(standalone_text) > 280:
            standalone_text = text  # skip URL if too long

        standalone_body = {"text": standalone_text}
        standalone_resp = oauth.post("https://api.x.com/2/tweets", json=standalone_body)

        if standalone_resp.status_code in (200, 201):
            return {"data": standalone_resp.json().get("data", {}), "method": "standalone_mention"}

        try:
            standalone_error = standalone_resp.json()
        except Exception:
            standalone_error = standalone_resp.text

        print(json.dumps({
            "success": False,
            "status": standalone_resp.status_code,
            "error": standalone_error,
            "note": "quote, reply, and standalone all failed",
        }))
        sys.exit(1)

    print(json.dumps({"success": False, "status": resp.status_code, "error": error_body}))
    sys.exit(1)


def extract_tweet_id(url_or_id: str) -> str:
    """Extract tweet ID from a URL or return as-is if already an ID."""
    match = re.search(r"/status/(\d+)", url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


def load_targets() -> list:
    if TARGETS_PATH.exists():
        with open(TARGETS_PATH) as f:
            return json.load(f)
    return []


def save_targets(targets: list):
    with open(TARGETS_PATH, "w") as f:
        json.dump(targets, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Find and quote retweet relevant tweets")
    parser.add_argument("--search", help="Search query to find tweets")
    parser.add_argument("--tweet-id", help="Specific tweet ID to quote")
    parser.add_argument("--tweet-url", help="Tweet URL to quote (extracts ID)")
    parser.add_argument("--comment", help="Quote retweet text (max 280 chars)")
    parser.add_argument("--min-likes", type=int, default=20, help="Min like count (default 20)")
    parser.add_argument("--min-followers", type=int, default=500, help="Min author followers (default 500)")
    parser.add_argument("--limit", type=int, default=20, help="Max results to scan (default 20)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--list-targets", action="store_true", help="Show monitored accounts")
    parser.add_argument("--add-target", help="Add account to monitor (with or without @)")
    args = parser.parse_args()

    if args.list_targets:
        targets = load_targets()
        print(json.dumps({"success": True, "targets": targets}, indent=2))
        return

    if args.add_target:
        targets = load_targets()
        username = args.add_target.lstrip("@").lower()
        if username not in targets:
            targets.append(username)
            save_targets(targets)
        print(json.dumps({"success": True, "targets": targets}))
        return

    # Direct quote retweet of a specific tweet
    if args.tweet_id or args.tweet_url:
        tweet_id = extract_tweet_id(args.tweet_url or args.tweet_id)
        comment = args.comment or ""

        if not comment:
            print(json.dumps({"success": False, "error": "provide --comment for quote retweet text"}))
            sys.exit(1)

        if len(comment) > 280:
            print(json.dumps({"success": False, "error": f"comment exceeds 280 chars ({len(comment)})"}))
            sys.exit(1)

        if args.dry_run:
            print(json.dumps({
                "success": True,
                "dry_run": True,
                "quote_tweet_id": tweet_id,
                "comment": comment,
                "chars": len(comment),
            }, indent=2))
            return

        oauth = get_oauth_session()
        result = post_quote_tweet(oauth, comment, tweet_id)
        tid = result.get("data", {}).get("id", "")
        method = result.get("method", "quote")
        print(json.dumps({
            "success": True,
            "tweet_id": tid,
            "url": f"https://x.com/JSHorwitz/status/{tid}",
            "method": method,
            "target_tweet_id": tweet_id,
            "comment": comment,
        }, indent=2))
        return

    # Search mode
    if args.search:
        bearer_token = get_bearer_token()
        results = search_tweets(
            bearer_token, args.search, args.limit, args.min_likes, args.min_followers
        )
        print(json.dumps({
            "success": True,
            "query": args.search,
            "matched_count": len(results),
            "tweets": results,
        }, indent=2))
        return

    # Default: scan default searches and show top results
    bearer_token = get_bearer_token()
    all_results = []
    for query in DEFAULT_SEARCHES:
        try:
            results = search_tweets(bearer_token, query, 10, args.min_likes, args.min_followers)
            all_results.extend(results)
        except Exception as e:
            pass

    # Deduplicate by tweet ID
    seen = set()
    unique = []
    for r in all_results:
        if r["tweet_id"] not in seen:
            seen.add(r["tweet_id"])
            unique.append(r)

    unique.sort(key=lambda x: x["likes"], reverse=True)
    print(json.dumps({
        "success": True,
        "queries_run": DEFAULT_SEARCHES,
        "matched_count": len(unique),
        "tweets": unique[:20],
    }, indent=2))


if __name__ == "__main__":
    main()
