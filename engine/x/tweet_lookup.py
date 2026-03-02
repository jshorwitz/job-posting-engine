#!/usr/bin/env python3
"""
Look up a specific tweet by ID with full engagement metrics and author details.

Usage:
    python x_tweet_lookup.py --tweet-id 2025846968245948795
    python x_tweet_lookup.py --tweet-id 2025846968245948795 --include-context

Arguments:
    --tweet-id: The tweet ID to look up
    --include-context: Include conversation context (quoted tweet, reply chain)

Output: JSON with tweet content, engagement metrics, and author info
"""

import argparse
import json
import os
import sys


def get_bearer_token() -> str:
    token = os.environ.get("X_API_BEARER_TOKEN")
    if not token:
        print(json.dumps({"success": False, "error": "X_API_BEARER_TOKEN not set"}))
        sys.exit(1)
    return token


def lookup_tweet(bearer_token: str, tweet_id: str, include_context: bool) -> dict:
    import httpx

    url = f"https://api.x.com/2/tweets/{tweet_id}"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {
        "tweet.fields": "created_at,public_metrics,context_annotations,entities,conversation_id,in_reply_to_user_id,referenced_tweets,source,lang,organic_metrics,non_public_metrics",
        "expansions": "author_id,referenced_tweets.id,referenced_tweets.id.author_id,entities.mentions.username,attachments.media_keys",
        "user.fields": "username,name,description,public_metrics,verified,profile_image_url,created_at,location,url",
        "media.fields": "type,url,preview_image_url,alt_text,public_metrics,duration_ms",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        if response.status_code == 401:
            # Try without non_public_metrics (requires user-context auth)
            params["tweet.fields"] = "created_at,public_metrics,context_annotations,entities,conversation_id,in_reply_to_user_id,referenced_tweets,source,lang"
            response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()


def format_output(data: dict) -> dict:
    tweet = data.get("data", {})
    includes = data.get("includes", {})
    users_by_id = {u["id"]: u for u in includes.get("users", [])}
    media_by_key = {m["media_key"]: m for m in includes.get("media", [])} if "media" in includes else {}

    author_id = tweet.get("author_id", "")
    author = users_by_id.get(author_id, {})
    author_metrics = author.get("public_metrics", {})
    tweet_metrics = tweet.get("public_metrics", {})

    # Handle article tweets (X Articles have a nested article object)
    article = tweet.get("article", {})

    # Calculate engagement rate
    impressions = tweet_metrics.get("impression_count", 0)
    total_engagement = (
        tweet_metrics.get("like_count", 0)
        + tweet_metrics.get("retweet_count", 0)
        + tweet_metrics.get("reply_count", 0)
        + tweet_metrics.get("quote_count", 0)
        + tweet_metrics.get("bookmark_count", 0)
    )
    engagement_rate = (total_engagement / impressions * 100) if impressions > 0 else 0

    # Extract hashtags and mentions
    entities = tweet.get("entities", {})
    hashtags = [h.get("tag", "") for h in entities.get("hashtags", [])]
    mentions = [m.get("username", "") for m in entities.get("mentions", [])]
    urls = [u.get("expanded_url", "") for u in entities.get("urls", [])]

    # Context annotations (topics X detected)
    contexts = tweet.get("context_annotations", [])
    topics = list({c.get("entity", {}).get("name", "") for c in contexts if c.get("entity", {}).get("name")})

    # Referenced tweets (quotes, replies)
    referenced = []
    for ref in tweet.get("referenced_tweets", []):
        ref_tweet = next((t for t in includes.get("tweets", []) if t["id"] == ref["id"]), None)
        ref_author = users_by_id.get(ref_tweet.get("author_id", ""), {}) if ref_tweet else {}
        referenced.append({
            "type": ref.get("type", ""),
            "id": ref.get("id", ""),
            "text": ref_tweet.get("text", "") if ref_tweet else "",
            "author": ref_author.get("username", ""),
        })

    # Media attachments
    media = []
    for key in tweet.get("attachments", {}).get("media_keys", []):
        m = media_by_key.get(key, {})
        media.append({
            "type": m.get("type", ""),
            "url": m.get("url", m.get("preview_image_url", "")),
        })

    username = author.get("username", "")
    tweet_id = tweet.get("id", "")

    return {
        "success": True,
        "tweet": {
            "id": tweet_id,
            "text": tweet.get("text", ""),
            "article_title": article.get("title", ""),
            "created_at": tweet.get("created_at", ""),
            "source": tweet.get("source", ""),
            "lang": tweet.get("lang", ""),
            "url": f"https://x.com/{username}/status/{tweet_id}",
            "conversation_id": tweet.get("conversation_id", ""),
        },
        "metrics": {
            "impressions": impressions,
            "likes": tweet_metrics.get("like_count", 0),
            "retweets": tweet_metrics.get("retweet_count", 0),
            "replies": tweet_metrics.get("reply_count", 0),
            "quotes": tweet_metrics.get("quote_count", 0),
            "bookmarks": tweet_metrics.get("bookmark_count", 0),
            "total_engagement": total_engagement,
            "engagement_rate_pct": round(engagement_rate, 2),
        },
        "author": {
            "id": author_id,
            "username": username,
            "display_name": author.get("name", ""),
            "bio": author.get("description", ""),
            "location": author.get("location", ""),
            "url": author.get("url", ""),
            "verified": author.get("verified", False),
            "profile_image": author.get("profile_image_url", ""),
            "created_at": author.get("created_at", ""),
            "followers": author_metrics.get("followers_count", 0),
            "following": author_metrics.get("following_count", 0),
            "tweets_count": author_metrics.get("tweet_count", 0),
            "listed_count": author_metrics.get("listed_count", 0),
        },
        "entities": {
            "hashtags": hashtags,
            "mentions": mentions,
            "urls": urls,
        },
        "topics_detected": topics,
        "referenced_tweets": referenced,
        "media": media,
    }


def main():
    parser = argparse.ArgumentParser(description="Look up a tweet by ID")
    parser.add_argument("--tweet-id", required=True, help="Tweet ID to look up")
    parser.add_argument("--include-context", action="store_true", help="Include conversation context")
    args = parser.parse_args()

    bearer_token = get_bearer_token()

    try:
        data = lookup_tweet(bearer_token, args.tweet_id, args.include_context)
        output = format_output(data)
        print(json.dumps(output, indent=2))
    except Exception as e:
        error_msg = str(e)
        try:
            import httpx
            if isinstance(e, httpx.HTTPStatusError) and e.response is not None:
                error_body = e.response.json()
                error_msg = error_body.get("detail", error_body.get("title", str(e)))
        except Exception:
            pass
        print(json.dumps({"success": False, "error": error_msg}))
        sys.exit(1)


if __name__ == "__main__":
    main()
