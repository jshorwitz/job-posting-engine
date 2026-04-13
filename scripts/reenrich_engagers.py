#!/usr/bin/env python3
"""
Re-enrich top 50 engagers: resolve t.co URLs to real domains, then hit Apollo.
"""

import csv
import json
import os
import re
import sys
import time

import httpx

RAW_INPUT = "/tmp/irabukht_all_tweet_engagers.json"
CSV_OUTPUT = "data/tweet_engagers_enriched.csv"
TOP_N = 50


def get_env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"ERROR: {key} not set", file=sys.stderr)
        sys.exit(1)
    return val


def resolve_tco(url: str, client: httpx.Client) -> str:
    """Resolve a t.co URL to its final destination."""
    if not url or "t.co" not in url:
        return url
    try:
        resp = client.head(url, follow_redirects=True, timeout=10.0)
        final = str(resp.url)
        if final and final != url:
            return final
    except Exception:
        try:
            resp = client.get(url, follow_redirects=True, timeout=10.0)
            final = str(resp.url)
            if final and final != url:
                return final
        except Exception:
            pass
    return url


def extract_domain(url: str) -> str:
    """Extract clean domain from a URL."""
    if not url:
        return ""
    domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0].strip()
    # Skip social media domains - not useful for Apollo matching
    skip = {"twitter.com", "x.com", "instagram.com", "facebook.com", "linkedin.com",
            "youtube.com", "tiktok.com", "linktr.ee", "bit.ly", "t.co", "wa.me",
            "whatsapp.com", "calendly.com", "ko-fi.com", "buymeacoffee.com",
            "patreon.com", "gumroad.com", "substack.com", "medium.com",
            "beacons.ai", "stan.store", "bento.me"}
    if domain and '.' in domain and domain not in skip:
        return domain
    return ""


def enrich_apollo(client: httpx.Client, api_key: str, first_name: str, last_name: str,
                  domain: str, username: str) -> dict:
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
            print(f"  Apollo {resp.status_code}", file=sys.stderr)
            return {}
        data = resp.json()
        return data.get("person") or {}
    except Exception as e:
        print(f"  Apollo error: {e}", file=sys.stderr)
        return {}


def clean_name(raw_name: str) -> tuple:
    """Strip emojis and flags from name, split into first/last."""
    # Remove emoji characters
    cleaned = re.sub(r'[^\w\s\'-.]', '', raw_name, flags=re.UNICODE).strip()
    # Remove common suffixes like titles
    cleaned = re.sub(r'\s*\|.*$', '', cleaned).strip()
    parts = cleaned.split(None, 1)
    first = parts[0] if parts else ""
    last = parts[1] if len(parts) > 1 else ""
    return first, last


def main():
    apollo_key = get_env("APOLLO_API_KEY")

    with open(RAW_INPUT) as f:
        data = json.load(f)

    engagers = data["engagers"][:TOP_N]
    print(f"Re-enriching top {len(engagers)} engagers with t.co resolution + Apollo", file=sys.stderr)

    enriched_rows = []

    with httpx.Client(timeout=30.0) as client:
        for i, user in enumerate(engagers):
            username = user.get("username", "")
            followers = user.get("public_metrics", {}).get("followers_count", 0)
            raw_name = user.get("name", "") or ""
            first_name, last_name = clean_name(raw_name)
            bio = user.get("description", "") or ""
            profile_url = user.get("url", "") or ""
            tweets_engaged = user.get("tweets_engaged", 1)
            engagement_types = user.get("engagement_types", ["retweet"])
            if isinstance(engagement_types, list):
                engagement_types = ", ".join(engagement_types)

            # Resolve t.co URLs
            domain = ""

            # Try profile URL first
            if profile_url and "t.co" in profile_url:
                resolved = resolve_tco(profile_url, client)
                domain = extract_domain(resolved)

            # Try bio URLs if no domain yet
            if not domain:
                tco_urls = re.findall(r'https?://t\.co/\S+', bio)
                for tco in tco_urls[:2]:  # max 2 to avoid slowness
                    resolved = resolve_tco(tco, client)
                    d = extract_domain(resolved)
                    if d:
                        domain = d
                        break

            # Also check for non-t.co URLs in bio
            if not domain:
                urls = re.findall(r'https?://[^\s,)]+', bio)
                for u in urls:
                    if "t.co" not in u:
                        d = extract_domain(u)
                        if d:
                            domain = d
                            break

            print(f"  [{i+1}/{len(engagers)}] @{username} ({followers:,}) name=\"{first_name} {last_name}\" domain={domain or '(none)'}", file=sys.stderr)

            # Apollo enrichment
            person = {}
            if first_name:
                person = enrich_apollo(client, apollo_key, first_name, last_name, domain, username)
                time.sleep(0.4)

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
                "name": raw_name,
                "title": (person.get("title") or "") if person else "",
                "company": ((person.get("organization") or {}).get("name") or "") if person else "",
                "email": email or "",
                "email_status": email_status or "",
                "linkedin": (person.get("linkedin_url") or "") if person else "",
                "city": (person.get("city") or "") if person else "",
                "domain": domain,
                "tweets_engaged": tweets_engaged,
                "engagement_types": engagement_types,
                "x_bio": bio.replace("\n", " ")[:200],
            })

    # Export CSV
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)
    fieldnames = [
        "x_handle", "x_followers", "name", "title", "company",
        "email", "email_status", "linkedin", "city", "domain",
        "tweets_engaged", "engagement_types", "x_bio",
    ]
    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"\nCSV saved to {CSV_OUTPUT}", file=sys.stderr)

    with_email = sum(1 for r in enriched_rows if r["email"])
    with_linkedin = sum(1 for r in enriched_rows if r["linkedin"])
    with_title = sum(1 for r in enriched_rows if r["title"])

    print(f"\nResults:", file=sys.stderr)
    print(f"  Total enriched: {len(enriched_rows)}", file=sys.stderr)
    print(f"  With email: {with_email}", file=sys.stderr)
    print(f"  With LinkedIn: {with_linkedin}", file=sys.stderr)
    print(f"  With title: {with_title}", file=sys.stderr)

    print(f"\nTop engagers with data:", file=sys.stderr)
    for r in enriched_rows:
        if r["email"] or r["linkedin"] or r["title"]:
            print(f"  {r['x_handle']} ({r['x_followers']:,}) | {r['title']} @ {r['company']} | {r['email']} | {r['linkedin']}", file=sys.stderr)

    print(json.dumps({
        "success": True,
        "enriched_count": len(enriched_rows),
        "with_email": with_email,
        "with_linkedin": with_linkedin,
        "with_title": with_title,
        "csv_file": CSV_OUTPUT,
    }, indent=2))


if __name__ == "__main__":
    main()
