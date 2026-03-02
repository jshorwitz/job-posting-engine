#!/usr/bin/env python3
"""
Get followers of an X user, optionally filtered by bio keywords (e.g. investor, VC).

Usage:
    python x_get_followers.py --username irabukht --filter-bio "investor,VC,venture,fund,angel,partner,capital"
    python x_get_followers.py --user-id 123456 --min-followers 1000 --limit 200
    python x_get_followers.py --username elonmusk --filter-bio "investor" --min-followers 5000

Arguments:
    --username: X username (without @)
    --user-id: X user ID (alternative to username)
    --filter-bio: Comma-separated keywords to filter bios (case-insensitive)
    --min-followers: Minimum follower count for results (default 0)
    --limit: Max followers to scan (default 1000, API max per request is 1000)
    --output-csv: Optional CSV output path

Output: JSON with filtered follower profiles
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


def resolve_user_id(bearer_token: str, username: str) -> str:
    """Resolve a username to a user ID."""
    import httpx

    url = f"https://api.x.com/2/users/by/username/{username}"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    params = {"user.fields": "public_metrics,description"}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        user = data.get("data", {})
        return user.get("id", "")


def get_followers(bearer_token: str, user_id: str, limit: int) -> list:
    """Fetch followers with pagination."""
    import httpx

    all_followers = []
    pagination_token = None
    max_per_request = min(limit, 1000)

    with httpx.Client(timeout=30.0) as client:
        while len(all_followers) < limit:
            url = f"https://api.x.com/2/users/{user_id}/followers"
            headers = {"Authorization": f"Bearer {bearer_token}"}
            params = {
                "max_results": min(max_per_request, 1000),
                "user.fields": "username,name,description,public_metrics,verified,location,url,created_at,profile_image_url",
            }
            if pagination_token:
                params["pagination_token"] = pagination_token

            response = client.get(url, headers=headers, params=params)

            if response.status_code == 429:
                reset_time = response.headers.get("x-rate-limit-reset", "")
                print(json.dumps({
                    "success": False,
                    "error": "Rate limited on followers endpoint (15 req / 15 min)",
                    "rate_limit_reset": reset_time,
                    "followers_fetched_so_far": len(all_followers),
                }))
                sys.exit(1)

            response.raise_for_status()
            data = response.json()

            followers = data.get("data", [])
            all_followers.extend(followers)

            pagination_token = data.get("meta", {}).get("next_token")
            if not pagination_token:
                break

    return all_followers[:limit]


def filter_followers(followers: list, bio_keywords: list, min_followers: int) -> list:
    """Filter followers by bio keywords and minimum follower count."""
    filtered = []

    for user in followers:
        metrics = user.get("public_metrics", {})
        follower_count = metrics.get("followers_count", 0)

        if follower_count < min_followers:
            continue

        bio = (user.get("description", "") or "").lower()
        name = (user.get("name", "") or "").lower()

        if bio_keywords:
            matched_keywords = [kw for kw in bio_keywords if kw.lower() in bio or kw.lower() in name]
            if not matched_keywords:
                continue
        else:
            matched_keywords = []

        username = user.get("username", "")
        filtered.append({
            "user_id": user.get("id", ""),
            "username": username,
            "display_name": user.get("name", ""),
            "bio": user.get("description", ""),
            "location": user.get("location", ""),
            "url": user.get("url", ""),
            "verified": user.get("verified", False),
            "profile_image": user.get("profile_image_url", ""),
            "followers": follower_count,
            "following": metrics.get("following_count", 0),
            "tweets": metrics.get("tweet_count", 0),
            "listed": metrics.get("listed_count", 0),
            "profile_url": f"https://x.com/{username}",
            "matched_keywords": matched_keywords,
        })

    # Sort by follower count descending
    filtered.sort(key=lambda x: x["followers"], reverse=True)
    return filtered


def export_csv(followers: list, path: str):
    """Export filtered followers to CSV."""
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "username", "display_name", "bio", "location", "url",
            "followers", "following", "tweets", "verified",
            "matched_keywords", "profile_url",
        ])
        writer.writeheader()
        for user in followers:
            row = {**user}
            row["matched_keywords"] = ", ".join(row.get("matched_keywords", []))
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})


def main():
    parser = argparse.ArgumentParser(description="Get followers of an X user")
    parser.add_argument("--username", help="X username (without @)")
    parser.add_argument("--user-id", help="X user ID")
    parser.add_argument("--filter-bio", help="Comma-separated keywords to filter bios")
    parser.add_argument("--min-followers", type=int, default=0, help="Minimum follower count (default 0)")
    parser.add_argument("--limit", type=int, default=1000, help="Max followers to scan (default 1000)")
    parser.add_argument("--output-csv", help="Export results to CSV file")
    args = parser.parse_args()

    if not args.username and not args.user_id:
        print(json.dumps({"success": False, "error": "Provide --username or --user-id"}))
        sys.exit(1)

    bearer_token = get_bearer_token()

    try:
        # Resolve username to user ID if needed
        user_id = args.user_id
        if not user_id:
            user_id = resolve_user_id(bearer_token, args.username)
            if not user_id:
                print(json.dumps({"success": False, "error": f"Could not find user @{args.username}"}))
                sys.exit(1)

        # Fetch followers
        print(f"Fetching up to {args.limit} followers for user {user_id}...", file=sys.stderr)
        followers = get_followers(bearer_token, user_id, args.limit)

        # Filter
        bio_keywords = [kw.strip() for kw in args.filter_bio.split(",")] if args.filter_bio else []
        filtered = filter_followers(followers, bio_keywords, args.min_followers)

        # Export CSV if requested
        if args.output_csv and filtered:
            export_csv(filtered, args.output_csv)
            print(f"Exported {len(filtered)} results to {args.output_csv}", file=sys.stderr)

        output = {
            "success": True,
            "target_username": args.username or "",
            "target_user_id": user_id,
            "total_followers_scanned": len(followers),
            "filter_keywords": bio_keywords,
            "min_followers_filter": args.min_followers,
            "matched_count": len(filtered),
            "followers": filtered,
        }

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
