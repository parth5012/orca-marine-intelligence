#!/usr/bin/env bash
# ORCA Marine Intelligence — PFZ Data Extraction Script
# Owner: M-B (Data + Safety)
# Module: scripts/extract_pfz.sh
#
# Fetches today's INCOIS TextData and extracts PFZ coordinates.
# Run daily at 11:30 AM IST via cron or manually.
#
# Usage:
#   INCOIS_JSESSIONID=<session> bash scripts/extract_pfz.sh
#
# Dependencies:
#   - curl, python3 (with beautifulsoup4, geopandas)
#
# TODO:
#   - [ ] Implement INCOIS TextData page fetch
#   - [ ] Add session cookie validation
#   - [ ] Implement HTML table parsing
#   - [ ] Output GeoJSON to data/pfz-today.geojson
#   - [ ] Add error handling and logging
#   - [ ] Add PostGIS upsert step

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
OUTPUT="$DATA_DIR/pfz-today.geojson"

echo "[ORCA] Starting PFZ extraction — $(date -Iseconds)"

# Validate session cookie
if [ -z "${INCOIS_JSESSIONID:-}" ]; then
    echo "[ORCA] ERROR: INCOIS_JSESSIONID not set"
    exit 1
fi

# TODO: Fetch TextData page
# curl -s -b "JSESSIONID=$INCOIS_JSESSIONID" \
#     "https://incois.gov.in/TextDataHome" \
#     -o /tmp/orca_textdata.html

# TODO: Parse HTML and extract coordinates
# python3 "$SCRIPT_DIR/extract_pfz.py" /tmp/orca_textdata.html "$OUTPUT"

echo "[ORCA] PFZ extraction complete — output: $OUTPUT"
