#!/bin/sh
# Cron entrypoint — runs on Railway cron schedule (weekdays 9 AM ET).
# Step 1: Discover new leads, enrich, push to Loops, enroll in drip
# Step 2: Send due drip emails for all active contacts

set -e

echo "=== Step 1: Enrich + Export ==="
python -m engine.pipeline --enrich --export loops

echo "=== Step 2: Drip Scheduler ==="
python -m engine.pipeline --drip
