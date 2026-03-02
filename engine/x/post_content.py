#!/usr/bin/env python3
"""
Publish posts to X via API v2. Supports single posts, threads, and replies.

Usage:
    python x_post_content.py --text "Check out Synter for AI ad management" --dry-run
    python x_post_content.py --text "First post" --text "Second post (thread)"
    python x_post_content.py --text "Great insight!" --reply-to 1234567890
    python x_post_content.py --text "Post with link" --dry-run

Arguments:
    --text: Post text, can be repeated for threads (each max 280 chars)
    --reply-to: Tweet ID to reply to
    --dry-run: Validate without posting

Auth: Uses X_API_ACCESS_TOKEN (OAuth 2.0) or falls back to OAuth 1.0a
      (X_ADS_CONSUMER_KEY, X_ADS_CONSUMER_SECRET, X_ADS_ACCESS_TOKEN, X_ADS_ACCESS_TOKEN_SECRET)

Output: JSON with created post details
"""

import argparse
import json
import os
import sys

TWEETS_URL = "https://api.x.com/2/tweets"


def get_oauth2_headers() -> dict | None:
    """Try OAuth 2.0 user-context token."""
    token = os.environ.get("X_API_ACCESS_TOKEN")
    if token:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    return None


def get_oauth1_session():
    """Fall back to OAuth 1.0a session. Prefer Joel's personal app, then Synter app."""
    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        return None

    consumer_key = os.environ.get("JOEL_X_CONSUMER_KEY") or os.environ.get("X_ADS_CONSUMER_KEY") or os.environ.get("TWITTER_CONSUMER_KEY")
    consumer_secret = os.environ.get("JOEL_X_CONSUMER_SECRET") or os.environ.get("X_ADS_CONSUMER_SECRET") or os.environ.get("TWITTER_CONSUMER_SECRET")
    access_token = os.environ.get("JOEL_X_ACCESS_TOKEN") or os.environ.get("X_ADS_ACCESS_TOKEN") or os.environ.get("TWITTER_ACCESS_TOKEN")
    access_token_secret = os.environ.get("JOEL_X_ACCESS_TOKEN_SECRET") or os.environ.get("X_ADS_ACCESS_TOKEN_SECRET") or os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

    if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
        return None

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_token_secret,
    )


def post_tweet(text: str, reply_to: str = None, quote_tweet_id: str = None, oauth2_headers: dict = None, oauth1_session=None) -> dict:
    """Post a single tweet via X API v2."""
    import httpx

    body = {"text": text}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    if quote_tweet_id:
        body["quote_tweet_id"] = quote_tweet_id

    if oauth2_headers:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(TWEETS_URL, headers=oauth2_headers, json=body)
            response.raise_for_status()
            return response.json()
    elif oauth1_session:
        response = oauth1_session.post(TWEETS_URL, json=body)
        response.raise_for_status()
        return response.json()
    else:
        raise RuntimeError("No auth method available")


def main():
    parser = argparse.ArgumentParser(description="Publish posts to X")
    parser.add_argument("--text", action="append", required=True,
                        help="Post text (repeat for threads, each max 280 chars)")
    parser.add_argument("--reply-to", help="Tweet ID to reply to")
    parser.add_argument("--quote", help="Tweet ID to quote retweet")
    parser.add_argument("--dry-run", action="store_true", help="Validate without posting")
    args = parser.parse_args()

    # Validate all texts
    for i, text in enumerate(args.text):
        if len(text) > 280:
            print(json.dumps({
                "success": False,
                "error": f"Post {i + 1} exceeds 280 characters ({len(text)} chars)"
            }))
            sys.exit(1)

    # Dry run: return mock response
    if args.dry_run:
        mock_posts = []
        for i, text in enumerate(args.text):
            mock_posts.append({
                "post_id": f"dry_run_{i}",
                "text": text,
                "url": f"https://x.com/i/status/dry_run_{i}",
                "char_count": len(text),
            })
        print(json.dumps({
            "success": True,
            "dry_run": True,
            "posts": mock_posts,
        }, indent=2))
        return

    # Resolve auth method
    oauth2_headers = get_oauth2_headers()
    oauth1_session = None
    if not oauth2_headers:
        oauth1_session = get_oauth1_session()

    if not oauth2_headers and not oauth1_session:
        print(json.dumps({
            "success": False,
            "error": "No auth credentials found. Set X_API_ACCESS_TOKEN (OAuth 2.0) "
                     "or X_ADS_CONSUMER_KEY + X_ADS_CONSUMER_SECRET + "
                     "X_ADS_ACCESS_TOKEN + X_ADS_ACCESS_TOKEN_SECRET (OAuth 1.0a)"
        }))
        sys.exit(1)

    try:
        posted = []
        reply_to = args.reply_to
        quote_id = args.quote

        for i, text in enumerate(args.text):
            result = post_tweet(
                text=text,
                reply_to=reply_to,
                quote_tweet_id=quote_id if i == 0 else None,
                oauth2_headers=oauth2_headers,
                oauth1_session=oauth1_session,
            )
            tweet_data = result.get("data", {})
            tweet_id = tweet_data.get("id", "")

            posted.append({
                "post_id": tweet_id,
                "text": text,
                "url": f"https://x.com/i/status/{tweet_id}" if tweet_id else "",
            })

            # For threads, each subsequent tweet replies to the previous one
            if tweet_id:
                reply_to = tweet_id

        print(json.dumps({
            "success": True,
            "posts": posted,
        }, indent=2))

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
