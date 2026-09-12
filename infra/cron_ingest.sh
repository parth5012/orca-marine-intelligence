#!/usr/bin/env bash
# ==============================================================================
# ORCA Marine Intelligence - Daily INCOIS PFZ Ingest Cron Script (T11 #127)
#
# Owner: M-B (Data & Storage)
# Scheduled: 11:30 IST (06:00 UTC) daily (following INCOIS advisory refresh)
#
# Description:
#   Refreshes live INCOIS PFZ data, updates data/pfz-today.geojson,
#   upserts into PostGIS database (if available), and refreshes Redis cache.
#
# Usage:
#   bash infra/cron_ingest.sh [--sectors SEC005,SEC002]
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
LOG_DIR="${REPO_ROOT}/.tmp/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/cron_ingest.log"

echo "==============================================================================" | tee -a "${LOG_FILE}"
echo "[${TIMESTAMP}] Starting daily INCOIS PFZ refresh..." | tee -a "${LOG_FILE}"

PYTHON_CMD="python"
if command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    PYTHON_CMD="python"
elif command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v uv >/dev/null 2>&1; then
    PYTHON_CMD="uv run python"
fi

EXTRA_ARGS="${*:-}"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Running: ${PYTHON_CMD} -m backend.cron.fetch_pfz ${EXTRA_ARGS}" | tee -a "${LOG_FILE}"

if ${PYTHON_CMD} -m backend.cron.fetch_pfz ${EXTRA_ARGS} >> "${LOG_FILE}" 2>&1; then
    END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[${END_TIME}] INCOIS PFZ refresh completed successfully." | tee -a "${LOG_FILE}"
    echo "[${END_TIME}] Target: data/pfz-today.geojson updated." | tee -a "${LOG_FILE}"
    exit 0
else
    EXIT_CODE=$?
    END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[${END_TIME}] WARNING/ERROR: INCOIS PFZ refresh finished with code ${EXIT_CODE}." | tee -a "${LOG_FILE}"
    exit "${EXIT_CODE}"
fi
