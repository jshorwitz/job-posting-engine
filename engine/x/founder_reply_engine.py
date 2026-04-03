#!/usr/bin/env python3
"""
Founder Reply Engine — find high-engagement tweets from target accounts
and generate thoughtful replies from @JSHorwitz to build audience.

Strategy: Reply to bigger accounts in the ad tech / growth / AI marketing
space with genuinely insightful comments. People check your profile after
a good reply — this is the #1 organic growth lever on X.

Usage:
    python -m engine.x.founder_reply_engine                     # Scan + reply (up to 5)
    python -m engine.x.founder_reply_engine --scan-only         # Scan without replying
    python -m engine.x.founder_reply_engine --dry-run           # Preview matches + replies
    python -m engine.x.founder_reply_engine --max 3             # Reply to up to 3 tweets
    python -m engine.x.founder_reply_engine --review            # Show reply history

Auth: X_API_BEARER_TOKEN for search, JOEL_X_* for posting (OAuth 1.0a)
"""

from __future__ import annotations

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

_DATA_DIR = Path("/data") if Path("/data").exists() else Path("data")
_DATA_DIR.mkdir(exist_ok=True)
REPLIED_LOG = _DATA_DIR / ".x_founder_replied_log.json"

# ------------------------------------------------------------------
# Target accounts — bigger accounts in ad tech / growth / AI / marketing
# that our ICPs follow. We reply to THEIR tweets to get discovered.
# ------------------------------------------------------------------
TARGET_ACCOUNTS = [
    # Ad tech / growth marketing thought leaders
    "gregisenberg",       # Greg Isenberg — community-led growth
    "aaborovoy",          # Amir — growth marketing
    "aaborovoy",          # growth
    "randfish",           # Rand Fishkin — SparkToro, SEO/marketing
    "alexgarcia_atx",     # Alex Garcia — growth marketing
    "marketingmax",       # Max — marketing insights
    "demaborin",          # Dema Borin — B2B growth
    "amandanat",          # Amanda Natividad — SparkToro, audience research
    "caborovoy",          # growth
    "ShaanVP",            # Shaan Puri — business/startups
    "thegaryvee",         # Gary Vee — marketing/social
    "naborovoy",          # growth
    # AI / tech founders
    "emaborovoy",         # AI
    "dhaborovoy",         # AI
    "skiaborovoy",        # AI marketing
    # PPC / paid media specific
    "navaborovoy",        # PPC
    "PPCKirk",            # Kirk Williams — PPC expert
    "AmaliaEFowler",      # Amalia Fowler — PPC
    "JuliaVyse",          # Julia Vyse — PPC
    "stevenjpope",        # Steven Pope — Amazon ads
]

# Also search these topic queries for high-engagement tweets
TOPIC_QUERIES = [
    "paid media strategy -is:retweet -is:reply",
    "performance marketing AI -is:retweet -is:reply",
    "ad spend optimization -is:retweet -is:reply",
    "marketing automation AI agents -is:retweet -is:reply",
    "cross-platform advertising -is:retweet -is:reply",
    "PPC management AI -is:retweet -is:reply",
    "ROAS optimization -is:retweet -is:reply",
    "MCP server marketing -is:retweet -is:reply",
    "AI replacing agencies -is:retweet -is:reply",
    "demand generation strategy 2026 -is:retweet -is:reply",
    "growth marketing playbook -is:retweet -is:reply",
    "media buying AI -is:retweet -is:reply",
]

# Never reply to these accounts
SKIP_USERNAMES = {"jshorwitz", "synterai", "syntermedia"}

# Minimum engagement thresholds for topic queries
# Lower follower threshold — mid-tier accounts (1K-10K) have open replies
# and are more likely to engage back than locked 100K+ accounts
MIN_LIKES_TOPIC = 3
MIN_FOLLOWERS_TOPIC = 500
# Lower thresholds for target accounts (we want to catch their tweets early)
MIN_LIKES_TARGET = 3
MIN_FOLLOWERS_TARGET = 0  # target accounts are pre-vetted

REPLY_SYSTEM_PROMPT = """\
you write X (twitter) replies as @JSHorwitz, a founder who has been doing paid media \
for 20+ years and is building synter (syntermedia.ai), an AI ad execution platform.

YOUR GOAL: write replies that are so insightful that people click your profile. \
you are NOT selling synter in replies. you are sharing genuine expertise.

VOICE:
- lowercase casual, no periods at end of lines
- line breaks between thoughts
- confident but not arrogant
- share specific data points or experiences when possible
- agree or respectfully disagree with substance, never generic praise
- 3-6 short lines max

ABSOLUTE RULES:
- NO emojis. none.
- NO em dashes. use commas or line breaks instead.
- NO exclamation marks.
- NO hashtags.
- NO self-promotion or mentioning synter unless directly relevant
- NO "great point", "love this", "so true", "couldn't agree more"
- NO words: leverage, unlock, game-changer, cutting-edge, streamline, elevate, \
supercharge, revolutionize, next-level, synergy, robust, seamless
- must be under 260 characters
- must add genuine value or a contrarian perspective

WHAT MAKES A GREAT REPLY:
- adds a specific data point or experience the original poster didn't mention
- respectfully challenges an assumption with evidence
- extends the idea with a practical application
- shares a failure or lesson learned related to the topic
- asks a genuinely interesting follow-up question

EXAMPLES OF GREAT REPLIES:
---
we tested this exact approach across 500 campaigns

the counterintuitive finding: broad targeting with AI-optimized creative beat \
hyper-targeted with generic creative by 40%

the targeting layer matters less than the creative layer now
---
ran into this at scale last year

the fix wasn't better automation, it was better attribution

most teams optimize for the wrong metric because their tracking is broken from day one
---
interesting take but I'd push back on one thing

cross-platform doesn't mean cross-channel strategy

most brands run the same creative on 6 platforms and wonder why only 2 work
---
"""


def get_bearer_token() -> str | None:
    return (
        os.environ.get("X_BEARER_TOKEN")
        or os.environ.get("X_API_BEARER_TOKEN")
        or os.environ.get("JOEL_X_BEARER_TOKEN")
    )


def get_joel_oauth():
    """Get OAuth 1.0a session for @JSHorwitz."""
    from requests_oauthlib import OAuth1Session

    consumer_key = os.environ.get("JOEL_X_CONSUMER_KEY")
    consumer_secret = os.environ.get("JOEL_X_CONSUMER_SECRET")
    access_token = os.environ.get("JOEL_X_ACCESS_TOKEN")
    access_secret = os.environ.get("JOEL_X_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_secret]):
        raise RuntimeError("Missing JOEL_X_* OAuth credentials for @JSHorwitz")

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_secret,
    )


def search_tweets(bearer_token: str, query: str, limit: int = 20) -> list:
    """Search recent tweets matching query."""
    import httpx

    url = "https://api.x.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(max(limit, 10), 100),
        "tweet.fields": "created_at,public_metrics,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified,description",
    }

    headers = {"Authorization": f"Bearer {bearer_token}"}
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
        author = users_by_id.get(tweet.get("author_id", ""), {})
        username = author.get("username", "")

        if username.lower() in SKIP_USERNAMES:
            continue

        tweet_id = tweet.get("id", "")
        results.append({
            "tweet_id": tweet_id,
            "text": tweet.get("text", ""),
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "created_at": tweet.get("created_at", ""),
            "conversation_id": tweet.get("conversation_id", ""),
            "likes": metrics.get("like_count", 0),
            "retweets": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
            "bookmarks": metrics.get("bookmark_count", 0),
            "impressions": metrics.get("impression_count", 0),
            "author_username": username,
            "author_name": author.get("name", ""),
            "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
            "source": "target_account" if username.lower() in {a.lower() for a in TARGET_ACCOUNTS} else "topic_query",
            "matched_query": "",
        })

    return results


def fetch_target_account_tweets(bearer_token: str) -> list:
    """Fetch recent tweets from target accounts."""
    import httpx

    headers = {"Authorization": f"Bearer {bearer_token}"}
    all_tweets = []

    # Deduplicate target accounts
    unique_accounts = list(dict.fromkeys(a.lower() for a in TARGET_ACCOUNTS))

    for username in unique_accounts:
        try:
            # Look up user ID
            with httpx.Client(timeout=15.0) as client:
                user_resp = client.get(
                    f"https://api.x.com/2/users/by/username/{username}",
                    headers=headers,
                    params={"user.fields": "public_metrics"},
                )
                if user_resp.status_code != 200:
                    continue
                user_id = user_resp.json().get("data", {}).get("id")
                if not user_id:
                    continue

                # Get their recent tweets
                tweets_resp = client.get(
                    f"https://api.x.com/2/users/{user_id}/tweets",
                    headers=headers,
                    params={
                        "max_results": 10,
                        "tweet.fields": "created_at,public_metrics,conversation_id",
                        "exclude": "retweets,replies",
                    },
                )
                if tweets_resp.status_code != 200:
                    continue

                tweets = tweets_resp.json().get("data", [])
                user_data = user_resp.json().get("data", {})
                followers = user_data.get("public_metrics", {}).get("followers_count", 0)

                for tweet in tweets:
                    metrics = tweet.get("public_metrics", {})
                    tid = tweet.get("id", "")
                    all_tweets.append({
                        "tweet_id": tid,
                        "text": tweet.get("text", ""),
                        "url": f"https://x.com/{username}/status/{tid}",
                        "created_at": tweet.get("created_at", ""),
                        "conversation_id": tweet.get("conversation_id", tid),
                        "likes": metrics.get("like_count", 0),
                        "retweets": metrics.get("retweet_count", 0),
                        "replies": metrics.get("reply_count", 0),
                        "bookmarks": metrics.get("bookmark_count", 0),
                        "impressions": metrics.get("impression_count", 0),
                        "author_username": username,
                        "author_name": user_data.get("name", ""),
                        "author_followers": followers,
                        "source": "target_account",
                        "matched_query": f"from:{username}",
                    })

            time.sleep(0.5)  # rate limit courtesy
        except Exception as e:
            logger.debug("failed to fetch tweets for @%s: %s", username, e)

    return all_tweets


def run_scan(bearer_token: str) -> list:
    """Scan target accounts + topic queries, return ranked candidates."""
    replied = load_replied()
    all_results = []

    # 1. Fetch tweets from target accounts
    logger.info("fetching tweets from %d target accounts...", len(set(a.lower() for a in TARGET_ACCOUNTS)))
    target_tweets = fetch_target_account_tweets(bearer_token)
    # Filter: at least MIN_LIKES_TARGET likes
    target_tweets = [t for t in target_tweets if t["likes"] >= MIN_LIKES_TARGET]
    all_results.extend(target_tweets)
    logger.info("found %d tweets from target accounts", len(target_tweets))

    # 2. Search topic queries
    logger.info("searching %d topic queries...", len(TOPIC_QUERIES))
    for query in TOPIC_QUERIES:
        try:
            results = search_tweets(bearer_token, query)
            # Filter by engagement thresholds
            results = [
                r for r in results
                if r["likes"] >= MIN_LIKES_TOPIC and r["author_followers"] >= MIN_FOLLOWERS_TOPIC
            ]
            all_results.extend(results)
            time.sleep(1)
        except Exception as e:
            logger.debug("query failed (%s): %s", query, e)

    # Deduplicate by tweet_id, exclude already-replied
    seen_ids = set()
    unique = []
    for r in all_results:
        tid = r["tweet_id"]
        if tid in seen_ids or tid in replied:
            continue
        seen_ids.add(tid)
        unique.append(r)

    # Score: prioritize target accounts, then engagement
    for r in unique:
        base = r["likes"] * 2 + r["retweets"] * 3 + r.get("bookmarks", 0) * 5
        # Boost target account tweets (reply early = more visibility)
        if r["source"] == "target_account":
            base += 50
        r["score"] = base

    unique.sort(key=lambda x: x["score"], reverse=True)
    return unique[:20]


def generate_reply(tweet_text: str, author_username: str) -> str:
    """Generate a contextual reply using OpenAI."""
    try:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, skipping")
            return ""

        client = OpenAI(api_key=api_key)

        prompt = (
            f"tweet from @{author_username}:\n"
            f'"""\n{tweet_text}\n"""\n\n'
            "write a reply. just the reply text, nothing else."
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

        # Strip quotes
        if reply.startswith('"') and reply.endswith('"'):
            reply = reply[1:-1].strip()

        # Clean up
        reply = reply.replace("—", ",").replace("–", ",")

        if len(reply) > 280:
            reply = reply[:277] + "..."

        if not reply or len(reply) < 20:
            logger.warning("AI reply too short or empty")
            return ""

        return reply

    except Exception as e:
        logger.error("AI reply generation failed: %s", e)
        return ""


def post_reply(tweet_id: str, text: str) -> dict:
    """Engage with a tweet from @JSHorwitz.

    Strategy: try reply first, then quote tweet, then standalone mention.
    Most big accounts have replies locked, so quote tweets are the primary
    engagement method — they still show up in the author's notifications
    and on @JSHorwitz's timeline.
    """
    oauth = get_joel_oauth()

    # 1. Try direct reply
    body = {"text": text, "reply": {"in_reply_to_tweet_id": tweet_id}}
    resp = oauth.post("https://api.x.com/2/tweets", json=body)
    if resp.status_code in (200, 201):
        reply_data = resp.json().get("data", {})
        return {"success": True, "reply_id": reply_data.get("id", ""), "method": "reply"}

    logger.debug("direct reply failed, trying quote tweet...")

    # 2. Try quote tweet
    quote_body = {"text": text, "quote_tweet_id": tweet_id}
    quote_resp = oauth.post("https://api.x.com/2/tweets", json=quote_body)
    if quote_resp.status_code in (200, 201):
        quote_data = quote_resp.json().get("data", {})
        return {"success": True, "reply_id": quote_data.get("id", ""), "method": "quote"}

    logger.debug("quote tweet failed, trying standalone with link...")

    # 3. Standalone tweet mentioning the original (always works)
    tweet_url = f"https://x.com/i/status/{tweet_id}"
    standalone = f"{text}\n\n{tweet_url}" if len(text) + len(tweet_url) + 2 <= 280 else text
    standalone_resp = oauth.post("https://api.x.com/2/tweets", json={"text": standalone})
    if standalone_resp.status_code in (200, 201):
        standalone_data = standalone_resp.json().get("data", {})
        return {"success": True, "reply_id": standalone_data.get("id", ""), "method": "standalone"}

    # All methods failed
    err = ""
    try:
        err = standalone_resp.json().get("detail", standalone_resp.text[:200])
    except Exception:
        err = str(standalone_resp.status_code)
    logger.warning("all engagement methods failed: %s", err[:80])
    return {"success": False, "error": err}


def load_replied() -> dict:
    if REPLIED_LOG.exists():
        with open(REPLIED_LOG) as f:
            return json.load(f)
    return {}


def save_replied(replied: dict):
    with open(REPLIED_LOG, "w") as f:
        json.dump(replied, f, indent=2)


def run_scan_and_reply(max_replies: int = 5, dry_run: bool = False) -> dict:
    """Scan for tweets and reply as @JSHorwitz."""
    bearer_token = get_bearer_token()
    if not bearer_token:
        return {"success": False, "error": "X_API_BEARER_TOKEN not set"}

    candidates = run_scan(bearer_token)
    replied = load_replied()
    results = []

    for candidate in candidates[:max_replies]:
        reply_text = generate_reply(candidate["text"], candidate["author_username"])
        if not reply_text:
            continue

        if dry_run:
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "likes": candidate["likes"],
                "score": candidate["score"],
                "source": candidate["source"],
                "tweet_text": candidate["text"][:140],
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
                "method": result.get("method", ""),
            }
            save_replied(replied)
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "reply_id": result.get("reply_id", ""),
                "reply_url": f"https://x.com/JSHorwitz/status/{result.get('reply_id', '')}",
                "status": "sent",
                "method": result.get("method", ""),
            })
            logger.info("replied to @%s: %s", candidate["author_username"], candidate["url"])
            time.sleep(3)  # spacing between replies — don't look spammy
        else:
            results.append({
                "tweet_id": candidate["tweet_id"],
                "url": candidate["url"],
                "author": f"@{candidate['author_username']}",
                "status": "failed",
                "error": result.get("error", ""),
            })

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "candidates_found": len(candidates),
        "replies": results,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Founder reply engine — reply to big accounts as @JSHorwitz")
    parser.add_argument("--scan-only", action="store_true", help="Scan without replying")
    parser.add_argument("--dry-run", action="store_true", help="Preview matches + AI replies")
    parser.add_argument("--review", action="store_true", help="Show reply history")
    parser.add_argument("--max", type=int, default=5, help="Max replies per run (default 5)")
    args = parser.parse_args()

    if args.review:
        replied = load_replied()
        print(json.dumps({"total": len(replied), "replies": replied}, indent=2))
        return

    if args.scan_only:
        bearer_token = get_bearer_token()
        if not bearer_token:
            print(json.dumps({"success": False, "error": "X_API_BEARER_TOKEN not set"}))
            sys.exit(1)
        candidates = run_scan(bearer_token)
        print(json.dumps({
            "success": True,
            "candidate_count": len(candidates),
            "candidates": [{
                "url": c["url"],
                "author": f"@{c['author_username']}",
                "likes": c["likes"],
                "score": c["score"],
                "source": c["source"],
                "text": c["text"][:140],
            } for c in candidates[:15]],
        }, indent=2))
        return

    result = run_scan_and_reply(max_replies=args.max, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
