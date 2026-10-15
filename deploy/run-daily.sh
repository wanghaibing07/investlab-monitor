#!/usr/bin/env bash
# Preserve the monitoring exit status even if notification delivery is unavailable.
set -u
CLI="${INVESTLAB_CLI:-/opt/investlab/.venv/bin/investlab}"
HOME_DIR="${INVESTLAB_HOME:-/var/lib/investlab}"
"$CLI" --home "$HOME_DIR" daily-cycle
result=$?
"$CLI" --home "$HOME_DIR" notify-pending || true
exit "$result"
