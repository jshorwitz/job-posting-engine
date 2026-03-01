#!/usr/bin/env bash
# Cron runner for the Job Posting Outreach Engine.
# Runs daily via launchd, logs to logs/cron-YYYY-MM-DD.log.

set -euo pipefail

ENGINE_DIR="/Users/joelhorwitz/work/job-posting-engine"
cd "$ENGINE_DIR"

LOG_FILE="logs/cron-$(date +%Y-%m-%d).log"
mkdir -p logs

echo "=== Outreach run started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"

DRY_RUN=false \
  /opt/homebrew/bin/doppler run \
    --project synter-media \
    --config prd \
    -- .venv/bin/python -m engine.pipeline \
      --channel email \
      --limit 20 \
  >> "$LOG_FILE" 2>&1

echo "=== Outreach run finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"
