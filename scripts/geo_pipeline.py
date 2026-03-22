#!/usr/bin/env python3
"""Geo-routed outbound pipeline.

Runs the growth engine pipeline across multiple countries, routing leads
to the correct Smartlead campaign based on geography.

Usage:
    python scripts/geo_pipeline.py              # Full run across all geos
    python scripts/geo_pipeline.py --dry-run    # Preview without sending
    python scripts/geo_pipeline.py --geo us     # Run US only

Runs daily via the x_scheduler.py job discovery hook.
"""

import argparse
import logging
import os
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("geo_pipeline")

# Geo → Smartlead campaign mapping
# Full query list for all geos
_FULL_QUERIES = [
    "PPC Manager",
    "Performance Marketing Manager",
    "Media Buyer",
    "Paid Media Manager",
    "Growth Marketing Manager",
    "Digital Advertising Manager",
    "Demand Generation Manager",
    "SEM Manager",
    "Paid Search Analyst",
    "Campaign Manager",
    "Marketing Operations Manager",
    "User Acquisition Manager",
    "Ecommerce Marketing Manager",
    "Programmatic Media Buyer",
    "Head of Paid Media",
    "Director of Paid Acquisition",
]

# Shorter query list for smaller markets (avoid burning Sumble credits on low-volume geos)
_CORE_QUERIES = [
    "PPC Manager",
    "Performance Marketing",
    "Media Buyer",
    "Paid Media Manager",
    "Growth Marketing Manager",
    "Digital Advertising Manager",
]

GEO_CAMPAIGNS = {
    "americas": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_AMERICAS",
        "countries": ["US", "CA", "MX", "BR", "AR", "CO"],
        "queries": _FULL_QUERIES,
    },
    "eu_west": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_EU",
        "countries": ["GB", "IE", "FR", "NL", "BE"],
        "queries": _FULL_QUERIES,
    },
    "eu_central": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_EU",
        "countries": ["DE", "AT", "CH", "PL", "CZ", "DK", "SE", "NO", "FI"],
        "queries": _CORE_QUERIES,
    },
    "eu_south": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_EU",
        "countries": ["ES", "PT", "IT", "GR", "IL"],
        "queries": _CORE_QUERIES,
    },
    "apac": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_APAC",
        "countries": ["AU", "NZ", "SG", "HK", "JP", "KR", "IN"],
        "queries": _FULL_QUERIES,
    },
    "mena_africa": {
        "campaign_id_env": "SMARTLEAD_CAMPAIGN_ID_EU",  # Send on EU timezone (close enough)
        "countries": ["AE", "SA", "ZA", "NG", "KE", "EG"],
        "queries": _CORE_QUERIES,
    },
}

LIMIT_PER_QUERY = int(os.environ.get("GEO_PIPELINE_LIMIT", "20"))


def run_pipeline(country: str, query: str, campaign_id: str, dry_run: bool) -> dict:
    """Run the pipeline for a single country + query combo."""
    cmd = [
        sys.executable, "-m", "engine.pipeline",
        "--query", query,
        "--limit", str(LIMIT_PER_QUERY),
        "--channel", "email",
    ]
    if dry_run:
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["JOB_COUNTRIES"] = country
    env["SMARTLEAD_CAMPAIGN_ID"] = campaign_id

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300, env=env,
        )
        # Parse results from output
        output = result.stdout + result.stderr
        new_jobs = 0
        emails_sent = 0
        for line in output.split("\n"):
            if "Complete" in line:
                for part in line.split():
                    if part.startswith("new_jobs="):
                        new_jobs = int(part.split("=")[1])
                    if part.startswith("emails_sent="):
                        emails_sent = int(part.split("=")[1])
        return {"new_jobs": new_jobs, "emails_sent": emails_sent}
    except subprocess.TimeoutExpired:
        logger.error(f"Pipeline timed out: {country}/{query}")
        return {"new_jobs": 0, "emails_sent": 0}
    except Exception as e:
        logger.error(f"Pipeline error: {country}/{query}: {e}")
        return {"new_jobs": 0, "emails_sent": 0}


def main():
    parser = argparse.ArgumentParser(description="Geo-routed outbound pipeline")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--geo", choices=["americas", "eu", "apac", "all"], default="all")
    args = parser.parse_args()

    geos = [args.geo] if args.geo != "all" else list(GEO_CAMPAIGNS.keys())
    total_new = 0
    total_sent = 0

    for geo in geos:
        config = GEO_CAMPAIGNS[geo]
        campaign_id = os.environ.get(config["campaign_id_env"], "")
        if not campaign_id:
            logger.warning(f"No campaign ID for {geo} ({config['campaign_id_env']}), skipping")
            continue

        logger.info(f"{'='*60}")
        logger.info(f"Running {geo.upper()} pipeline → campaign {campaign_id}")
        logger.info(f"Countries: {config['countries']}, Queries: {len(config['queries'])}")
        logger.info(f"{'='*60}")

        for country in config["countries"]:
            for query in config["queries"]:
                result = run_pipeline(country, query, campaign_id, args.dry_run)
                if result["new_jobs"] > 0:
                    logger.info(
                        f"  ✅ {country} | {query} → "
                        f"new={result['new_jobs']} sent={result['emails_sent']}"
                    )
                    total_new += result["new_jobs"]
                    total_sent += result["emails_sent"]

    logger.info(f"\n{'='*60}")
    logger.info(f"GEO PIPELINE COMPLETE: new_jobs={total_new} emails_sent={total_sent}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
