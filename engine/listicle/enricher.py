"""Listicle editor enrichment — find contact details for article authors.

Uses Hunter.io domain search to find editors/writers at publication domains,
then stores contact info on the ListicleTarget record.

Usage:
    python -m engine.listicle.enricher --enrich
    python -m engine.listicle.enricher --enrich --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from engine.clients.hunter import HunterClient
from engine.config import Settings
from engine.db.database import init_db
from engine.db.models import ListicleTarget, ListicleStatus

logger = logging.getLogger(__name__)

# Job titles likely to control listicle content
EDITOR_TITLES = [
    "editor", "content manager", "content strategist", "writer",
    "content lead", "managing editor", "seo manager", "head of content",
    "content director", "editorial", "blog manager",
]


def enrich_targets(
    session, hunter: HunterClient, dry_run: bool = False, limit: int = 20,
    target_type: str | None = None,
) -> dict:
    """Find editor/host contacts for DISCOVERED targets.

    Uses Hunter.io domain-search to find people at the publication domain
    with editor/writer/host titles.
    """
    query = (
        session.query(ListicleTarget)
        .filter(ListicleTarget.status == ListicleStatus.DISCOVERED)
        .filter(ListicleTarget.editor_email.is_(None))
    )
    if target_type:
        query = query.filter(ListicleTarget.target_type == target_type)
    targets = query.limit(limit).all()

    stats = {"enriched": 0, "no_contact": 0, "errors": 0, "skipped": 0}

    for target in targets:
        logger.info(f"Enriching: {target.domain} — {target.title[:60]}")

        try:
            result = _find_editor_at_domain(hunter, target.domain)

            if result:
                if not dry_run:
                    target.editor_name = result["name"]
                    target.editor_email = result["email"]
                    target.editor_linkedin = result.get("linkedin")
                    target.status = ListicleStatus.CONTACT_FOUND
                    session.commit()

                stats["enriched"] += 1
                logger.info(f"  Found: {result['name']} <{result['email']}> @ {target.domain}")
            else:
                stats["no_contact"] += 1
                logger.info(f"  No editor found at {target.domain}")

            time.sleep(0.3)  # rate limit

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"  Error enriching {target.domain}: {e}")

    return stats


def _find_editor_at_domain(hunter: HunterClient, domain: str) -> dict | None:
    """Search Hunter.io for an editor/content person at the given domain.

    Returns dict with name, email, linkedin or None.
    """
    import httpx

    params = {
        "domain": domain,
        "limit": 10,
        "api_key": hunter.api_key,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get("https://api.hunter.io/v2/domain-search", params=params)

        if resp.status_code != 200:
            return None

        data = resp.json().get("data", {})
        emails = data.get("emails", [])

        # Prioritize by editor-like titles
        for person in emails:
            position = (person.get("position") or "").lower()
            if any(title in position for title in EDITOR_TITLES):
                name_parts = [person.get("first_name", ""), person.get("last_name", "")]
                full_name = " ".join(p for p in name_parts if p).strip()
                if full_name and person.get("value"):
                    return {
                        "name": full_name,
                        "email": person["value"],
                        "linkedin": person.get("linkedin"),
                    }

        # Fallback: first person with a verified email
        for person in emails:
            conf = person.get("confidence", 0)
            if conf >= 50 and person.get("value"):
                name_parts = [person.get("first_name", ""), person.get("last_name", "")]
                full_name = " ".join(p for p in name_parts if p).strip()
                if full_name:
                    return {
                        "name": full_name,
                        "email": person["value"],
                        "linkedin": person.get("linkedin"),
                    }

        return None

    except Exception as e:
        logger.error(f"Hunter domain-search failed for {domain}: {e}")
        return None


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Listicle editor enrichment")
    parser.add_argument("--enrich", action="store_true", help="Enrich targets with editor contacts")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    parser.add_argument("--limit", type=int, default=20, help="Max targets to enrich")
    args = parser.parse_args()

    settings = Settings()
    if not settings.hunter_api_key:
        print(json.dumps({"success": False, "error": "HUNTER_API_KEY not set"}))
        sys.exit(1)

    SessionFactory = init_db(settings.database_path)
    session = SessionFactory()
    hunter = HunterClient(settings)

    if args.enrich:
        stats = enrich_targets(session, hunter, dry_run=args.dry_run, limit=args.limit)
        print(json.dumps({"success": True, "dry_run": args.dry_run, **stats}, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
