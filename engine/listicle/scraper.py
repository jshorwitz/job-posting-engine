"""Listicle article discovery — find 'best of' articles for Synter placement.

Scrapes Google search results for listicle-style articles, extracts URLs and titles,
deduplicates, and stores in SQLite for outreach tracking.

Usage:
    python -m engine.listicle.scraper --discover
    python -m engine.listicle.scraper --discover --dry-run
    python -m engine.listicle.scraper --list
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from urllib.parse import urlparse

import httpx

from engine.config import Settings
from engine.db.database import init_db
from engine.db.models import ListicleTarget, ListicleStatus

logger = logging.getLogger(__name__)

# Search queries targeting listicle articles in our category
SEARCH_QUERIES = [
    "best AI ad management tools",
    "best AI advertising platforms",
    "top ad management software",
    "best AI marketing tools",
    "best programmatic advertising platforms",
    "best AI media buying tools",
    "best cross-platform ad management",
    "best AI campaign management tools",
    "top AI tools for digital advertising",
    "best ad automation platforms",
    # Gumshoe high-volume topics (added 2026-03-17)
    "best cross-channel advertising tools 2026",
    "best AI tools for cross-channel advertising",
    "best ad campaign automation platforms",
    "best automated ad campaign management tools",
    "best attribution software for marketing teams",
    "best multi-touch attribution tools",
    "best reporting tools for multi-channel ads",
    "best multi-channel ad reporting platforms",
    "best AI ad management platforms 2026",
    "best AI PPC management tools",
]

PODCAST_QUERIES = [
    "best marketing podcasts",
    "best digital marketing podcasts",
    "best advertising podcasts",
    "top paid media podcasts",
    "best adtech podcasts",
    "best growth marketing podcasts",
    "best AI marketing podcasts",
    "best performance marketing podcasts",
    "best SaaS marketing podcasts",
    "best B2B marketing podcasts",
    "top podcasts for marketers",
    "best podcasts about advertising technology",
]

# Domains to exclude (search engines, social, our own)
EXCLUDED_DOMAINS = {
    "google.com", "youtube.com", "facebook.com", "twitter.com", "x.com",
    "linkedin.com", "reddit.com", "quora.com", "wikipedia.org",
    "syntermedia.ai", "synter.ai",
    "amazon.com", "apple.com", "microsoft.com",
}

# Google Custom Search API (free tier: 100 queries/day)
GOOGLE_CSE_URL = "https://www.googleapis.com/customsearch/v1"


def _extract_domain(url: str) -> str:
    """Extract root domain from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def _is_listicle_title(title: str) -> bool:
    """Check if a title looks like a listicle article AND is relevant to ad management."""
    title_lower = title.lower()

    # Must look like a listicle
    listicle_patterns = [
        r"\bbest\b", r"\btop\b", r"\d+\s+best", r"\d+\s+top",
        r"ultimate guide", r"comparison", r"vs\.?\b", r"alternatives",
        r"review", r"ranked", r"compared", r"picks",
    ]
    if not any(re.search(p, title_lower) for p in listicle_patterns):
        return False

    # Must be relevant to advertising / ad management (not generic marketing)
    relevance_keywords = [
        r"\bad\b", r"\bads\b", r"advertis", r"campaign", r"ppc",
        r"paid media", r"media buy", r"programmatic", r"ad tech",
        r"adtech", r"ad management", r"ad platform", r"ad tool",
        r"cross.?platform", r"cross.?channel", r"attribution",
        r"multi.?touch", r"reporting tool", r"marketing analytics",
        r"ai market", r"ai tool",
    ]
    return any(re.search(p, title_lower) for p in relevance_keywords)


def _is_podcast_title(title: str) -> bool:
    """Check if a title references podcasts."""
    title_lower = title.lower()
    patterns = [
        r"\bpodcast", r"\bbest\b.*podcast", r"\btop\b.*podcast",
        r"listen", r"\bepisode", r"\bshow\b.*market",
    ]
    return any(re.search(p, title_lower) for p in patterns)


def discover_via_google_cse(
    api_key: str, cse_id: str, queries: list[str] | None = None,
) -> list[dict]:
    """Discover listicle articles via Google Custom Search API.

    Returns list of dicts with keys: url, title, domain, search_query
    """
    if not api_key or not cse_id:
        logger.warning("GOOGLE_CSE_API_KEY or GOOGLE_CSE_ID not set — using fallback scraper")
        return []

    results = []
    seen_urls = set()

    for query in (queries or SEARCH_QUERIES):
        try:
            with httpx.Client(timeout=15.0) as client:
                for start in [1, 11]:  # pages 1 and 2 (10 results each)
                    resp = client.get(GOOGLE_CSE_URL, params={
                        "key": api_key,
                        "cx": cse_id,
                        "q": query,
                        "start": start,
                        "num": 10,
                    })

                    if resp.status_code != 200:
                        logger.warning(f"Google CSE returned {resp.status_code} for '{query}'")
                        break

                    data = resp.json()
                    for item in data.get("items", []):
                        url = item.get("link", "")
                        title = item.get("title", "")
                        domain = _extract_domain(url)

                        if domain in EXCLUDED_DOMAINS:
                            continue
                        if url in seen_urls:
                            continue
                        if not _is_listicle_title(title):
                            continue

                        seen_urls.add(url)
                        results.append({
                            "url": url,
                            "title": title,
                            "domain": domain,
                            "search_query": query,
                        })

                    time.sleep(1)  # rate limit

        except Exception as e:
            logger.error(f"Google CSE error for '{query}': {e}")

    logger.info(f"Discovered {len(results)} listicle articles from {len(queries or SEARCH_QUERIES)} queries")
    return results


def discover_via_serper(
    api_key: str,
    queries: list[str] | None = None,
    target_type: str = "listicle",
) -> list[dict]:
    """Discover articles via Serper.dev API (Google SERP API).

    Args:
        target_type: "listicle" or "podcast" — controls default queries and title filter.
    """
    if queries:
        default_queries = queries
    elif target_type == "podcast":
        default_queries = PODCAST_QUERIES
    else:
        default_queries = SEARCH_QUERIES

    title_filter = _is_podcast_title if target_type == "podcast" else _is_listicle_title

    results = []
    seen_urls = set()

    for query in default_queries:
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 30},
                )

                if resp.status_code != 200:
                    logger.warning(f"Serper returned {resp.status_code} for '{query}'")
                    continue

                data = resp.json()
                for item in data.get("organic", []):
                    url = item.get("link", "")
                    title = item.get("title", "")
                    domain = _extract_domain(url)

                    if domain in EXCLUDED_DOMAINS:
                        continue
                    if url in seen_urls:
                        continue
                    if not title_filter(title):
                        continue

                    seen_urls.add(url)
                    results.append({
                        "url": url,
                        "title": title,
                        "domain": domain,
                        "search_query": query,
                        "target_type": target_type,
                    })

            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Serper error for '{query}': {e}")

    logger.info(f"Discovered {len(results)} {target_type} targets via Serper")
    return results


def store_targets(session, targets: list[dict]) -> dict:
    """Store discovered listicle targets in the database. Returns stats."""
    stats = {"new": 0, "existing": 0, "total": len(targets)}

    for target in targets:
        existing = session.query(ListicleTarget).filter_by(url=target["url"]).first()
        if existing:
            stats["existing"] += 1
            continue

        row = ListicleTarget(
            url=target["url"],
            title=target["title"],
            domain=target["domain"],
            search_query=target["search_query"],
            target_type=target.get("target_type", "listicle"),
            domain_rating=target.get("domain_rating"),
            domain_traffic=target.get("domain_traffic"),
            article_traffic=target.get("article_traffic"),
            status=ListicleStatus.DISCOVERED,
        )
        session.add(row)
        stats["new"] += 1

    session.commit()
    return stats


def list_targets(session, target_type: str | None = None) -> list[dict]:
    """List targets with status, optionally filtered by type."""
    query = session.query(ListicleTarget)
    if target_type:
        query = query.filter(ListicleTarget.target_type == target_type)
    targets = query.order_by(ListicleTarget.discovered_at.desc()).all()
    results = []
    for t in targets:
        results.append({
            "id": t.id,
            "url": t.url,
            "title": t.title[:80],
            "domain": t.domain,
            "status": t.status.value,
            "target_type": t.target_type,
            "editor_name": t.editor_name,
            "editor_email": t.editor_email,
            "domain_rating": t.domain_rating,
            "article_traffic": t.article_traffic,
        })
    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Listicle article discovery")
    parser.add_argument("--discover", action="store_true", help="Discover new listicle articles")
    parser.add_argument("--list", action="store_true", help="List all targets")
    parser.add_argument("--dry-run", action="store_true", help="Preview without storing")
    parser.add_argument("--queries", nargs="+", help="Custom search queries")
    args = parser.parse_args()

    settings = Settings()
    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()

    if args.list:
        targets = list_targets(session)
        for t in targets:
            status_icon = "✅" if t["status"] == "listed" else "📧" if "outreach" in t["status"] else "⬜"
            print(f"  {status_icon} [{t['id']:3d}] DR:{t['domain_rating'] or '?':>3} | {t['domain']:>30} | {t['status']:>15} | {t['title']}")
        print(f"\nTotal: {len(targets)}")
        return

    if args.discover:
        # Try Serper first (cheaper), fall back to Google CSE
        serper_key = getattr(settings, "serper_api_key", "")
        google_key = getattr(settings, "google_cse_api_key", "")
        google_cse_id = getattr(settings, "google_cse_id", "")

        targets = []
        if serper_key:
            targets = discover_via_serper(serper_key, args.queries)
        elif google_key and google_cse_id:
            targets = discover_via_google_cse(google_key, google_cse_id, args.queries)
        else:
            logger.error("Set SERPER_API_KEY or (GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID) for discovery")
            sys.exit(1)

        if args.dry_run:
            print(json.dumps({"success": True, "dry_run": True, "targets": targets}, indent=2))
            return

        stats = store_targets(session, targets)
        print(json.dumps({"success": True, **stats}, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
