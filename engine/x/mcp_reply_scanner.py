#!/usr/bin/env python3
"""
Scan X for tweets about Claude + Facebook Ads + MCP and auto-reply.

Searches for tweets mentioning Claude/MCP + Facebook Ads automation, generates
a short founder-voice reply, and posts it. Runs on a schedule via x_scheduler.py.

Usage:
    python -m engine.x.mcp_reply_scanner                    # Scan and auto-reply
    python -m engine.x.mcp_reply_scanner --scan-only        # Scan without replying
    python -m engine.x.mcp_reply_scanner --dry-run          # Preview matches + replies
    python -m engine.x.mcp_reply_scanner --review           # Show already-replied tweets
    python -m engine.x.mcp_reply_scanner --max 3            # Reply to up to 3 tweets

Auth: X_API_BEARER_TOKEN for search, JOEL_X_* for posting
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path("/data") if Path("/data").exists() else Path(__file__).parent
REPLIED_LOG = _DATA_DIR / ".x_mcp_replied_log.json"

# Search queries targeting Claude + Facebook Ads + MCP tweets
SEARCH_QUERIES = [
    # Original MCP-specific queries
    '"Claude" "Facebook Ads" MCP',
    '"Claude" "Facebook Ads" "MCP server"',
    '"Claude" "Meta Ads" MCP',
    'MCP "Facebook Ads" reporting',
    'MCP "Facebook Ads" automation',
    'MCP "ad reporting" Claude',
    '"Facebook Ads" MCP integration',
    'Claude MCP "ads manager"',
    # Broader Claude Code + ads queries (catches vibe-coders building ad tools)
    '"Claude Code" "Meta Ads"',
    '"Claude Code" "Facebook Ads"',
    '"Claude Code" "ads manager"',
    '"Claude Code" "ad campaign"',
    '"vibe code" "Meta Ads"',
    '"vibe code" "Facebook Ads"',
    '"vibe coded" "Meta Ads"',
    '"vibe coded" "Facebook Ads"',
    '"Claude" "Meta Ads" bulk',
    '"Claude" "Meta Ads" automation',
    '"Claude" "ads manager" API',
    # AI ads dashboards / analytics (competitors like Graphed, Supermetrics, etc.)
    'AI "paid ads" dashboard',
    'AI "ads KPI" dashboard',
    'AI analyst "Facebook Ads"',
    'AI analyst "Google Ads"',
    '"data warehouse" "Facebook Ads" AI',
    'MCP "paid ads"',
    'MCP "Google Ads"',
    'MCP "LinkedIn Ads"',
]

REPLY_SYSTEM_PROMPT = """\
you write X (twitter) replies as the @SynterAI account. synter is an AI ad execution \
platform, not just reporting. MCP servers that let claude create, pause, and optimize \
campaigns across 9 platforms (Meta, Google, TikTok, LinkedIn, X, Snapchat, Pinterest, \
Amazon, Microsoft).

VOICE:
- lowercase casual, no periods at end of lines, short punchy lines
- line breaks between thoughts (not commas or semicolons)
- build-in-public energy, founder voice
- end with syntermedia.ai on its own line

ABSOLUTE RULES:
- NO emojis. none.
- NO em dashes. use commas or line breaks instead.
- NO exclamation marks.
- NO hashtags.
- NO words: leverage, unlock, game-changer, cutting-edge, streamline, elevate, \
supercharge, revolutionize, next-level, synergy, robust, seamless, holistic, innovative, \
AI-powered, excited
- NO "we'd love to", "feel free to", "don't hesitate"
- must be under 260 characters total (leave room for twitter overhead)
- 3-5 short lines max

POSITIONING:
- the tweet you're replying to usually shows someone doing facebook ads reporting via MCP
- your angle: reporting is cool but synter goes further, full execution not just read-only
- don't be dismissive of what they built. acknowledge it, then position synter as the next step
- be specific: mention the number of platforms (9), mention execution (create campaigns, \
swap creatives, adjust budgets), not just dashboards

EXAMPLES OF GOOD REPLIES:
---
reporting is the first step

we went further, AI agents that actually create, optimize and pause campaigns across 9 platforms

syntermedia.ai
---
nice, this handles the read side well

what about execution? synter lets claude create campaigns, swap creatives and adjust budgets across 9 platforms

syntermedia.ai
---
"""

FALLBACK_REPLIES = [
    "reporting is step 1\n\nwe went further, AI agents that actually create, optimize and pause campaigns across 9 platforms\n\nsyntermedia.ai",
    "nice, this handles the read side well\n\nwhat about execution? synter lets claude create campaigns, swap creatives and adjust budgets across 9 platforms\n\nsyntermedia.ai",
    "cool to see MCP for ad reporting\n\nwe built the execution layer on top, create campaigns, pause underperformers, reallocate budgets across 9 platforms from a chat message\n\nsyntermedia.ai",
]

# Lower engagement thresholds than the general scanner — these are niche, targeted
MIN_LIKES = 3
MIN_FOLLOWERS = 100
# Never reply to our own account
SKIP_USERNAMES = {"jshorwitz", "synterai", "syntermedia"}


def get_bearer_token() -> str:
    token = os.environ.get("X_API_BEARER_TOKEN") or os.environ.get("JOEL_X_BEARER_TOKEN")
    if not token:
        raise RuntimeError("X_API_BEARER_TOKEN not set")
    return token


def search_tweets(bearer_token: str, query: str, limit: int = 20) -> list:
    """Search recent tweets matching query."""
    import httpx

    url = "https://api.x.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "query": f"{query} -is:retweet lang:en",
        "max_results": min(max(limit, 10), 100),
        "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified,description",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        if response.status_code == 429:
            logger.warning("rate limited on query: %s", query)
            return []
        response.raise_for_status()
        data = response.json()

    tweets = data.get("data", [])
    users_by_id = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

    results = []
    for tweet in tweets:
        metrics = tweet.get("public_metrics", {})
        likes = metrics.get("like_count", 0)
        author = users_by_id.get(tweet.get("author_id", ""), {})
        username = author.get("username", "")
        author_followers = author.get("public_metrics", {}).get("followers_count", 0)

        if likes < MIN_LIKES:
            continue
        if author_followers < MIN_FOLLOWERS:
            continue
        if username.lower() in SKIP_USERNAMES:
            continue

        tweet_id = tweet.get("id", "")
        results.append({
            "tweet_id": tweet_id,
            "text": tweet.get("text", ""),
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "created_at": tweet.get("created_at", ""),
            "conversation_id": tweet.get("conversation_id", ""),
            "likes": likes,
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
            "bookmarks": metrics.get("bookmark_count", 0),
            "author_username": username,
            "author_name": author.get("name", ""),
            "author_followers": author_followers,
            "author_verified": author.get("verified", False),
            "matched_query": query,
        })

    return results


def load_replied() -> dict:
    """Load replied log. Maps tweet_id -> reply metadata."""
    if REPLIED_LOG.exists():
        with open(REPLIED_LOG) as f:
            return json.load(f)
    return {}


def save_replied(replied: dict):
    with open(REPLIED_LOG, "w") as f:
        json.dump(replied, f, indent=2)


def generate_reply(tweet_text: str, author_username: str) -> str:
    """Generate a contextual reply using OpenAI, matching brand voice."""
    try:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, using fallback reply")
            return random.choice(FALLBACK_REPLIES)

        client = OpenAI(api_key=api_key)

        prompt = (
            f"tweet from @{author_username}:\n"
            f'"""\n{tweet_text}\n"""\n\n'
            "write a reply to this tweet. just the reply text, nothing else."
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=150,
        )

        reply = (response.choices[0].message.content or "").strip()

        # Strip any quotes the model might wrap the reply in
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1].strip()

        # Validate: must be under 280 chars, no emojis, no em dashes
        if len(reply) > 280:
            reply = reply[:277] + "..."
        reply = reply.replace("—", ",").replace("–", ",")

        if not reply or len(reply) < 20:
            logger.warning("AI reply too short or empty, using fallback")
            return random.choice(FALLBACK_REPLIES)

        logger.info("AI generated reply (%d chars): %s", len(reply), reply[:80])
        return reply

    except Exception as e:
        logger.error("AI reply generation failed: %s, using fallback", e)
        return random.choice(FALLBACK_REPLIES)


def get_synterai_oauth():
    """Get OAuth 1.0a session for @SynterAI account."""
    from requests_oauthlib import OAuth1Session

    consumer_key = os.environ.get("X_ADS_CONSUMER_KEY")
    consumer_secret = os.environ.get("X_ADS_CONSUMER_SECRET")
    access_token = os.environ.get("X_ADS_ACCESS_TOKEN")
    access_secret = os.environ.get("X_ADS_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        raise RuntimeError("Missing X_ADS_* OAuth credentials for @SynterAI")

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def post_reply(tweet_id: str, text: str) -> dict:
    """Reply to a tweet from @SynterAI."""
    oauth = get_synterai_oauth()
    body = {"text": text, "reply": {"in_reply_to_tweet_id": tweet_id}}
    resp = oauth.post("https://api.x.com/2/tweets", json=body)

    if resp.status_code in (200, 201):
        reply_data = resp.json().get("data", {})
        return {"success": True, "reply_id": reply_data.get("id", ""), "method": "reply"}

    # If reply is restricted, try quote tweet, then standalone mention
    try:
        error_body = resp.json()
    except Exception:
        error_body = {"detail": resp.text}

    detail = error_body.get("detail", "")

    # Try quote tweet
    quote_body = {"text": text, "quote_tweet_id": tweet_id}
    quote_resp = oauth.post("https://api.x.com/2/tweets", json=quote_body)
    if quote_resp.status_code in (200, 201):
        quote_data = quote_resp.json().get("data", {})
        return {"success": True, "reply_id": quote_data.get("id", ""), "method": "quote"}

    # Try standalone mention with tweet URL
    tweet_url = f"https://x.com/i/status/{tweet_id}"
    standalone_text = f"{text}\n\n{tweet_url}"
    if len(standalone_text) > 280:
        standalone_text = text
    standalone_resp = oauth.post("https://api.x.com/2/tweets", json={"text": standalone_text})
    if standalone_resp.status_code in (200, 201):
        standalone_data = standalone_resp.json().get("data", {})
        return {"success": True, "reply_id": standalone_data.get("id", ""), "method": "standalone_mention"}

    return {"success": False, "error": detail or str(resp.status_code)}


def run_scan() -> list:
    """Search all queries and return deduplicated candidates."""
    bearer_token = get_bearer_token()
    replied = load_replied()
    all_results = []

    for query in SEARCH_QUERIES:
        try:
            results = search_tweets(bearer_token, query)
            all_results.extend(results)
            time.sleep(1)  # be gentle with rate limits
        except Exception as e:
            logger.debug("query failed (%s): %s", query, e)

    # Deduplicate by tweet_id, exclude already-replied and conversation dupes
    seen_ids = set()
    seen_convos = set()
    unique = []
    for r in all_results:
        tid = r["tweet_id"]
        cid = r.get("conversation_id", tid)
        if tid in seen_ids or tid in replied or cid in seen_convos:
            continue
        seen_ids.add(tid)
        seen_convos.add(cid)
        unique.append(r)

    # Sort by likes descending
    unique.sort(key=lambda x: x["likes"], reverse=True)
    return unique


def run_scan_and_reply(max_replies: int = 5, dry_run: bool = False) -> dict:
    """Scan for tweets and reply to them."""
    candidates = run_scan()
    replied = load_replied()
    results = []

    for candidate in candidates[:max_replies]:
        reply_text = generate_reply(candidate["text"], candidate["author_username"])

        if dry_run:
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "likes": candidate["likes"],
                "tweet_text": candidate["text"][:120],
                "reply_text": reply_text,
                "status": "dry_run",
            })
            continue

        result = post_reply(candidate["tweet_id"], reply_text)

        if result.get("success"):
            replied[candidate["tweet_id"]] = {
                "replied_at": datetime.now(timezone.utc).isoformat(),
                "reply_id": result.get("reply_id", ""),
                "reply_text": reply_text,
                "target_url": candidate["url"],
                "target_author": candidate["author_username"],
            }
            save_replied(replied)
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "reply_id": result.get("reply_id", ""),
                "reply_url": f"https://x.com/SynterAI/status/{result.get('reply_id', '')}",
                "status": "sent",
            })
            logger.info("replied to @%s: %s", candidate["author_username"], candidate["url"])
            time.sleep(2)  # spacing between replies
        else:
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "status": "failed",
                "error": result.get("error", ""),
            })
            logger.warning("reply failed for %s: %s", candidate["url"], result.get("error"))

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "queries": SEARCH_QUERIES,
        "candidates_found": len(candidates),
        "replies": results,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Scan X for Claude+Facebook Ads+MCP tweets and reply")
    parser.add_argument("--scan-only", action="store_true", help="Scan without replying")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches + replies")
    parser.add_argument("--review", action="store_true", help="Show already-replied tweets")
    parser.add_argument("--max", type=int, default=5, help="Max replies per run (default 5)")
    args = parser.parse_args()

    if args.review:
        replied = load_replied()
        print(json.dumps({"total": len(replied), "replies": replied}, indent=2))
        return

    if args.scan_only:
        candidates = run_scan()
        print(json.dumps({
            "success": True,
            "candidate_count": len(candidates),
            "candidates": [{
                "url": c["url"],
                "author": f"@{c['author_username']}",
                "likes": c["likes"],
                "text": c["text"][:140],
            } for c in candidates[:20]],
        }, indent=2))
        return

    result = run_scan_and_reply(max_replies=args.max, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
