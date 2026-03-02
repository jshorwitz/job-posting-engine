#!/bin/bash
# X Growth Engine cron runner — called by Railway cron or locally.
#
# Usage:
#   ./scripts/x_cron.sh post    # Post next from content calendar
#   ./scripts/x_cron.sh scan    # Scan for engagement opportunities
#   ./scripts/x_cron.sh list    # List calendar status
#
# Railway cron jobs should call this with Doppler:
#   doppler run -- ./scripts/x_cron.sh post

set -euo pipefail

ACTION="${1:-post}"

case "$ACTION" in
  post)
    echo "[x_cron] Posting next scheduled item..."
    python -m engine.pipeline --x-post
    ;;
  scan)
    echo "[x_cron] Scanning for engagement opportunities..."
    python -m engine.pipeline --x-scan
    ;;
  list)
    echo "[x_cron] Listing calendar status..."
    python -m engine.pipeline --x-list
    ;;
  *)
    echo "Unknown action: $ACTION"
    echo "Usage: $0 {post|scan|list}"
    exit 1
    ;;
esac
