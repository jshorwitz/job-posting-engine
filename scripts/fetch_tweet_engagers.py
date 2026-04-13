#!/usr/bin/env python3
"""
Fetch liking users and retweeting users from a specific tweet,
enrich top 30 by follower count via Apollo, and export to CSV.
"""

import csv
import json
import os
import re
import sys
import time

import httpx
from requests_oauthlib import OAuth1

TWEET_ID = "2043297676360658962"
RAW_OUTPUT = "/tmp/irabukht_tweet_engagers.json"
CSV_OUTPUT = "data/tweet_engagers_enriched.csv"
USER_FIELDS = "username,name,description,public_metrics,verified,location,url,created_at,profile_image_url"


def get_env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"ERROR: {key} not set", file=sys.stderr)
        sys.exit(1)
    return val


def make_oauth1_auth():
    """Create OAuth1 auth for user-context endpoints."""
    return OAuth1(
        get_env("JOEL_X_CONSUMER_KEY"),
        get_env("JOEL_X_CONSUMER_SECRET"),
        get_env("JOEL_X_ACCESS_TOKEN"),
        get_env("JOEL_X_ACCESS_TOKEN_SECRET"),
    )


def paginate_users_oauth(url: str, auth) -> list:
    """Paginate through a tweet engager endpoint using OAuth1 (requests library)."""
    import requests

    all_users = []
    pagination_token = None

    while True:
        params = {"max_results": 100, "user.fields": USER_FIELDS}
        if pagination_token:
            params["pagination_token"] = pagination_token

        resp = requests.get(url, auth=auth, params=params, timeout=30)

        if resp.status_code == 429:
            reset = resp.headers.get("x-rate-limit-reset", "unknown")
            print(f"Rate limited. Reset at {reset}. Got {len(all_users)} so far.", file=sys.stderr)
            break

        if resp.status_code == 403:
            print(f"403 Forbidden for {url}. Endpoint may require Pro tier.", file=sys.stderr)
            break

        resp.raise_for_status()
        data = resp.json()

        users = data.get("data", [])
        if not users:
            break
        all_users.extend(users)
        print(f"  fetched {len(users)} users (total: {len(all_users)})", file=sys.stderr)

        pagination_token = data.get("meta", {}).get("next_token")
        if not pagination_token:
            break
        time.sleep(0.3)

    return all_users


def extract_domain(bio: str, profile_url: str) -> str:
    """Extract a usable domain from bio URLs or profile URL, skipping t.co links."""
    # Check bio for URLs first
    urls = re.findall(r'https?://[^\s,)]+', bio or "")
    for u in urls:
        if "t.co" in u:
            continue
        domain = re.sub(r'^https?://(www\.)?', '', u).split('/')[0].strip()
        if domain and '.' in domain:
            return domain

    # Fall back to profile URL
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

    domain = extract_domain(
        user.get("description", ""),
        user.get("url", ""),
    )

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
        resp.raise_for_status()
        data = resp.json()
        return data.get("person") or {}
    except Exception as e:
        print(f"  Apollo error for {name}: {e}", file=sys.stderr)
        return {}


def main():
    apollo_key = get_env("APOLLO_API_KEY")
    auth = make_oauth1_auth()

    # 1. Fetch liking users
    print(f"Fetching liking users for tweet {TWEET_ID}...", file=sys.stderr)
    likers = paginate_users_oauth(
        f"https://api.x.com/2/tweets/{TWEET_ID}/liking_users",
        auth,
    )
    print(f"Total likers: {len(likers)}", file=sys.stderr)

    # 2. Fetch retweeting users
    print(f"Fetching retweeting users for tweet {TWEET_ID}...", file=sys.stderr)
    retweeters = paginate_users_oauth(
        f"https://api.x.com/2/tweets/{TWEET_ID}/retweeted_by",
        auth,
    )
    print(f"Total retweeters: {len(retweeters)}", file=sys.stderr)

    # 3. Deduplicate by user ID
    seen = {}
    for u in likers:
        uid = u.get("id", "")
        if uid:
            seen[uid] = {**u, "engagement_type": "like"}
    for u in retweeters:
        uid = u.get("id", "")
        if uid:
            if uid in seen:
                seen[uid]["engagement_type"] = "like+retweet"
            else:
                seen[uid] = {**u, "engagement_type": "retweet"}

    all_engagers = list(seen.values())
    all_engagers.sort(
        key=lambda x: x.get("public_metrics", {}).get("followers_count", 0),
        reverse=True,
    )
    print(f"Unique engagers: {len(all_engagers)}", file=sys.stderr)

    # 4. Save raw JSON
    raw = {
        "tweet_id": TWEET_ID,
        "total_likers": len(likers),
        "total_retweeters": len(retweeters),
        "unique_engagers": len(all_engagers),
        "engagers": all_engagers,
    }
    with open(RAW_OUTPUT, "w") as f:
        json.dump(raw, f, indent=2)
    print(f"Raw data saved to {RAW_OUTPUT}", file=sys.stderr)

    # 5. Enrich top 30 via Apollo
    top30 = all_engagers[:30]
    enriched_rows = []

    with httpx.Client(timeout=30.0) as client:
        for i, user in enumerate(top30):
            username = user.get("username", "")
            followers = user.get("public_metrics", {}).get("followers_count", 0)
            print(f"  [{i+1}/30] Enriching @{username} ({followers:,} followers)...", file=sys.stderr)

            person = enrich_apollo(client, apollo_key, user)
            time.sleep(0.5)  # gentle rate limiting

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
                "x_bio": (user.get("description", "") or "").replace("\n", " ")[:200],
            })

    # 6. Export CSV
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "x_handle", "x_followers", "name", "title", "company",
            "email", "email_status", "linkedin", "city", "x_bio",
        ])
        writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"\nEnriched CSV saved to {CSV_OUTPUT}", file=sys.stderr)
    print(f"Top 5 engagers:", file=sys.stderr)
    for r in enriched_rows[:5]:
        print(f"  {r['x_handle']} ({r['x_followers']:,}) — {r['title']} @ {r['company']} | {r['email']}", file=sys.stderr)

    # Also print summary as JSON to stdout
    print(json.dumps({
        "success": True,
        "total_likers": len(likers),
        "total_retweeters": len(retweeters),
        "unique_engagers": len(all_engagers),
        "enriched_count": len(enriched_rows),
        "with_email": sum(1 for r in enriched_rows if r["email"]),
        "with_linkedin": sum(1 for r in enriched_rows if r["linkedin"]),
        "raw_file": RAW_OUTPUT,
        "csv_file": CSV_OUTPUT,
    }, indent=2))


if __name__ == "__main__":
    main()
