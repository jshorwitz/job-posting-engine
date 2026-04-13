#!/usr/bin/env python3
"""
Fetch @irabukht's recent tweets, find high-engagement ones (100+ likes),
pull all liking/retweeting users across those tweets, deduplicate,
enrich top 50 by follower count via Apollo, and export to CSV.
"""

import csv
import json
import os
import re
import sys
import time

import httpx
import requests
from requests_oauthlib import OAuth1

USER_ID = "1844257725460709376"
RAW_OUTPUT = "/tmp/irabukht_all_tweet_engagers.json"
CSV_OUTPUT = "data/tweet_engagers_enriched.csv"
USER_FIELDS = "username,name,description,public_metrics,verified,location,url,created_at,profile_image_url"
TWEET_FIELDS = "public_metrics,created_at,text,conversation_id"
TOP_N = 50
MIN_LIKES = 100


def get_env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"ERROR: {key} not set", file=sys.stderr)
        sys.exit(1)
    return val


def make_oauth1():
    return OAuth1(
        get_env("JOEL_X_CONSUMER_KEY"),
        get_env("JOEL_X_CONSUMER_SECRET"),
        get_env("JOEL_X_ACCESS_TOKEN"),
        get_env("JOEL_X_ACCESS_TOKEN_SECRET"),
    )


def get_bearer_headers():
    return {"Authorization": f"Bearer {get_env('X_API_BEARER_TOKEN')}"}


# ── Step 1: Fetch recent tweets ──────────────────────────────────────────────

def fetch_user_tweets(user_id: str, max_tweets: int = 200) -> list:
    """Fetch recent tweets via bearer token with pagination."""
    headers = get_bearer_headers()
    all_tweets = []
    pagination_token = None

    with httpx.Client(timeout=30.0) as client:
        while len(all_tweets) < max_tweets:
            params = {
                "max_results": 100,
                "tweet.fields": TWEET_FIELDS,
                "exclude": "replies,retweets",
            }
            if pagination_token:
                params["pagination_token"] = pagination_token

            resp = client.get(
                f"https://api.x.com/2/users/{user_id}/tweets",
                headers=headers,
                params=params,
            )

            if resp.status_code == 429:
                reset = resp.headers.get("x-rate-limit-reset", "?")
                print(f"Rate limited on tweets endpoint. Reset: {reset}. Got {len(all_tweets)} so far.", file=sys.stderr)
                break

            resp.raise_for_status()
            data = resp.json()
            tweets = data.get("data", [])
            if not tweets:
                break

            all_tweets.extend(tweets)
            print(f"  fetched {len(tweets)} tweets (total: {len(all_tweets)})", file=sys.stderr)

            pagination_token = data.get("meta", {}).get("next_token")
            if not pagination_token:
                break
            time.sleep(0.3)

    return all_tweets


# ── Step 2: Pull liking/retweeting users (OAuth 1.0a) ────────────────────────

def paginate_users_oauth(url: str, auth) -> list:
    """Paginate through a tweet engager endpoint using OAuth1."""
    all_users = []
    pagination_token = None

    while True:
        params = {"max_results": 100, "user.fields": USER_FIELDS}
        if pagination_token:
            params["pagination_token"] = pagination_token

        resp = requests.get(url, auth=auth, params=params, timeout=30)

        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "?")
            remaining = resp.headers.get("x-rate-limit-remaining", "?")
            print(f"  Rate limited. Reset: {reset}. Got {len(all_users)} users so far.", file=sys.stderr)
            # Check how long to wait
            try:
                wait_seconds = int(reset) - int(time.time()) + 2
                if 0 < wait_seconds <= 900:
                    print(f"  Waiting {wait_seconds}s for rate limit reset...", file=sys.stderr)
                    time.sleep(wait_seconds)
                    continue
            except (ValueError, TypeError):
                pass
            break

        if resp.status_code == 403:
            print(f"  403 Forbidden for {url}.", file=sys.stderr)
            break

        resp.raise_for_status()
        data = resp.json()

        users = data.get("data", [])
        if not users:
            break
        all_users.extend(users)

        pagination_token = data.get("meta", {}).get("next_token")
        if not pagination_token:
            break
        time.sleep(0.35)

    return all_users


# ── Step 3: Apollo enrichment ─────────────────────────────────────────────────

def extract_domain(bio: str, profile_url: str) -> str:
    """Extract a usable domain from bio URLs or profile URL, skipping t.co."""
    urls = re.findall(r'https?://[^\s,)]+', bio or "")
    for u in urls:
        if "t.co" in u:
            continue
        domain = re.sub(r'^https?://(www\.)?', '', u).split('/')[0].strip()
        if domain and '.' in domain:
            return domain

    if profile_url and "t.co" not in profile_url:
        domain = re.sub(r'^https?://(www\.)?', '', profile_url).split('/')[0].strip()
        if domain and '.' in domain:
            return domain

    return ""


def enrich_apollo(client: httpx.Client, api_key: str, user: dict) -> dict:
    """Enrich a single user via Apollo people/match endpoint."""
    name = user.get("name", "") or ""
    parts = name.strip().split(None, 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""

    if not first_name:
        return {}

    domain = extract_domain(user.get("description", ""), user.get("url", ""))
    username = user.get("username", "")

    body = {
        "first_name": first_name,
        "last_name": last_name,
        "reveal_personal_emails": True,
    }
    if domain:
        body["domain"] = domain
    if username:
        body["twitter_url"] = f"https://x.com/{username}"

    try:
        resp = client.post(
            "https://api.apollo.io/api/v1/people/match",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json=body,
            timeout=15.0,
        )
        if resp.status_code == 429:
            print(f"  Apollo rate limited, sleeping 60s...", file=sys.stderr)
            time.sleep(60)
            resp = client.post(
                "https://api.apollo.io/api/v1/people/match",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json=body,
                timeout=15.0,
            )
        if resp.status_code >= 400:
            print(f"  Apollo {resp.status_code} for {name}", file=sys.stderr)
            return {}
        data = resp.json()
        return data.get("person") or {}
    except Exception as e:
        print(f"  Apollo error for {name}: {e}", file=sys.stderr)
        return {}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    apollo_key = get_env("APOLLO_API_KEY")
    auth = make_oauth1()

    # 1. Fetch recent tweets
    print(f"=== Fetching recent tweets for user {USER_ID} ===", file=sys.stderr)
    tweets = fetch_user_tweets(USER_ID, max_tweets=200)
    print(f"Total tweets fetched: {len(tweets)}", file=sys.stderr)

    # Sort by engagement
    for t in tweets:
        m = t.get("public_metrics", {})
        t["_engagement"] = m.get("like_count", 0) + m.get("retweet_count", 0) + m.get("quote_count", 0)

    tweets.sort(key=lambda t: t["_engagement"], reverse=True)

    # Show top tweets
    print(f"\nTop tweets by engagement:", file=sys.stderr)
    for t in tweets[:15]:
        m = t.get("public_metrics", {})
        text_preview = t.get("text", "")[:80].replace("\n", " ")
        print(f"  {t['id']} | L:{m.get('like_count',0)} RT:{m.get('retweet_count',0)} Q:{m.get('quote_count',0)} | {text_preview}...", file=sys.stderr)

    # Filter to 100+ likes
    high_engagement = [t for t in tweets if t.get("public_metrics", {}).get("like_count", 0) >= MIN_LIKES]
    print(f"\nTweets with {MIN_LIKES}+ likes: {len(high_engagement)}", file=sys.stderr)

    if not high_engagement:
        print("No tweets with 100+ likes found. Lowering threshold to 50...", file=sys.stderr)
        high_engagement = [t for t in tweets if t.get("public_metrics", {}).get("like_count", 0) >= 50]
        print(f"Tweets with 50+ likes: {len(high_engagement)}", file=sys.stderr)

    if not high_engagement:
        print("No tweets with 50+ likes found. Using top 10 tweets by engagement.", file=sys.stderr)
        high_engagement = tweets[:10]

    # 2. Pull liking + retweeting users for each qualifying tweet
    all_engagers = {}  # uid -> user dict with engagement info

    for idx, tweet in enumerate(high_engagement):
        tid = tweet["id"]
        m = tweet.get("public_metrics", {})
        likes = m.get("like_count", 0)
        rts = m.get("retweet_count", 0)
        text_preview = tweet.get("text", "")[:60].replace("\n", " ")
        print(f"\n--- [{idx+1}/{len(high_engagement)}] Tweet {tid} (L:{likes} RT:{rts}) {text_preview}... ---", file=sys.stderr)

        # Liking users
        print(f"  Fetching liking users...", file=sys.stderr)
        likers = paginate_users_oauth(
            f"https://api.x.com/2/tweets/{tid}/liking_users", auth
        )
        print(f"  Got {len(likers)} likers", file=sys.stderr)

        for u in likers:
            uid = u.get("id", "")
            if not uid:
                continue
            if uid in all_engagers:
                all_engagers[uid]["tweet_ids"].add(tid)
                all_engagers[uid]["engagement_types"].add("like")
            else:
                all_engagers[uid] = {
                    **u,
                    "tweet_ids": {tid},
                    "engagement_types": {"like"},
                }

        # Retweeting users
        print(f"  Fetching retweeting users...", file=sys.stderr)
        retweeters = paginate_users_oauth(
            f"https://api.x.com/2/tweets/{tid}/retweeted_by", auth
        )
        print(f"  Got {len(retweeters)} retweeters", file=sys.stderr)

        for u in retweeters:
            uid = u.get("id", "")
            if not uid:
                continue
            if uid in all_engagers:
                all_engagers[uid]["tweet_ids"].add(tid)
                all_engagers[uid]["engagement_types"].add("retweet")
            else:
                all_engagers[uid] = {
                    **u,
                    "tweet_ids": {tid},
                    "engagement_types": {"retweet"},
                }

        time.sleep(0.5)

    # Convert sets to lists for JSON serialization
    for uid, u in all_engagers.items():
        u["tweet_ids"] = sorted(u["tweet_ids"])
        u["engagement_types"] = sorted(u["engagement_types"])
        u["tweets_engaged"] = len(u["tweet_ids"])

    # Sort by follower count
    engager_list = sorted(
        all_engagers.values(),
        key=lambda x: x.get("public_metrics", {}).get("followers_count", 0),
        reverse=True,
    )

    print(f"\n=== Total unique engagers across all tweets: {len(engager_list)} ===", file=sys.stderr)

    # 3. Save raw JSON
    raw = {
        "user_id": USER_ID,
        "tweets_analyzed": len(high_engagement),
        "tweet_ids": [t["id"] for t in high_engagement],
        "unique_engagers": len(engager_list),
        "engagers": engager_list,
    }
    with open(RAW_OUTPUT, "w") as f:
        json.dump(raw, f, indent=2)
    print(f"Raw data saved to {RAW_OUTPUT}", file=sys.stderr)

    # 4. Enrich top N via Apollo
    top = engager_list[:TOP_N]
    enriched_rows = []

    print(f"\n=== Enriching top {len(top)} engagers via Apollo ===", file=sys.stderr)

    with httpx.Client(timeout=30.0) as client:
        for i, user in enumerate(top):
            username = user.get("username", "")
            followers = user.get("public_metrics", {}).get("followers_count", 0)
            print(f"  [{i+1}/{len(top)}] @{username} ({followers:,} followers, engaged with {user.get('tweets_engaged', 0)} tweets)...", file=sys.stderr)

            person = enrich_apollo(client, apollo_key, user)
            time.sleep(0.5)

            email = ""
            email_status = ""
            if person:
                for e in person.get("email_addresses", []):
                    if e.get("email"):
                        email = e["email"]
                        email_status = e.get("email_status", "")
                        break
                if not email:
                    email = person.get("email", "")
                    email_status = person.get("email_status", "")

            enriched_rows.append({
                "x_handle": f"@{username}",
                "x_followers": followers,
                "name": user.get("name", ""),
                "title": (person.get("title") or "") if person else "",
                "company": ((person.get("organization") or {}).get("name") or "") if person else "",
                "email": email or "",
                "email_status": email_status or "",
                "linkedin": (person.get("linkedin_url") or "") if person else "",
                "city": (person.get("city") or "") if person else "",
                "tweets_engaged": user.get("tweets_engaged", 0),
                "engagement_types": ", ".join(user.get("engagement_types", [])),
                "x_bio": (user.get("description", "") or "").replace("\n", " ")[:200],
            })

    # 5. Export CSV
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)
    fieldnames = [
        "x_handle", "x_followers", "name", "title", "company",
        "email", "email_status", "linkedin", "city",
        "tweets_engaged", "engagement_types", "x_bio",
    ]
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"\nEnriched CSV saved to {CSV_OUTPUT}", file=sys.stderr)
    print(f"\nTop 10 engagers:", file=sys.stderr)
    for r in enriched_rows[:10]:
        print(f"  {r['x_handle']} ({r['x_followers']:,}) | {r['tweets_engaged']} tweets | {r['title']} @ {r['company']} | {r['email']}", file=sys.stderr)

    # Summary to stdout
    print(json.dumps({
        "success": True,
        "tweets_analyzed": len(high_engagement),
        "unique_engagers": len(engager_list),
        "enriched_count": len(enriched_rows),
        "with_email": sum(1 for r in enriched_rows if r["email"]),
        "with_linkedin": sum(1 for r in enriched_rows if r["linkedin"]),
        "multi_tweet_engagers": sum(1 for r in enriched_rows if r["tweets_engaged"] > 1),
        "raw_file": RAW_OUTPUT,
        "csv_file": CSV_OUTPUT,
    }, indent=2))


if __name__ == "__main__":
    main()
