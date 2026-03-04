#!/usr/bin/env bash
# Cron runner for the Growth Engine.
# Customize ENGINE_DIR and secrets source for your setup.

set -euo pipefail

ENGINE_DIR="${ENGINE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ENGINE_DIR"

LOG_FILE="logs/cron-$(date +%Y-%m-%d).log"
mkdir -p logs

echo "=== Outreach run started at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"

# If using Doppler for secrets, wrap with: doppler run --project <project> --config <env> --
# Otherwise, ensure env vars are set (e.g., via .env or Railway/Docker env).

# Prefer python3 (macOS ships python3, not python)
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

DRY_RUN="${DRY_RUN:-false}" \
  "$PYTHON" -m engine.pipeline \
    --channel email \
    --limit "${MAX_EMAILS_PER_RUN:-20}" \
  >> "$LOG_FILE" 2>&1

echo "=== Outreach run finished at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG_FILE"
