#!/usr/bin/env bash
# run_weekly.sh — Weekly content-automation orchestration script
#
# Designed to be called by an OpenClaw cron job (see openclaw-cron.example.json).
# Schedule: Tuesday 14:00 UTC (0 14 * * 2) = 10:00 ET / 16:00 CEST
#
# What this script does:
#   1. Publishes the next queued DEV.to article (if DEVTO_QUEUE_FILE is set)
#   2. Gathers curation candidates and writes them to CURATION_OUTPUT
#   3. Exits — LinkedIn drafting is NOT done here.
#
# LinkedIn drafting step:
#   After this script exits, the OpenClaw agent reads CURATION_OUTPUT,
#   selects or drafts a LinkedIn post, and calls queue_buffer.py directly.
#   This separation keeps the shell script free of LLM logic and lets the
#   agent iterate on the post text without re-running the pipeline.
#
# Required env vars (set in .env or passed by the cron runner):
#   DEVTO_API_KEY              — DEV.to / Forem API key
#   BUFFER_ACCESS_TOKEN        — Buffer OAuth access token
#   BUFFER_LINKEDIN_CHANNEL_ID — Buffer LinkedIn channel id
#
# Optional env vars:
#   DEVTO_QUEUE_FILE  — path to a file containing the path of the next
#                       Markdown article to publish; if unset, the publish
#                       step is skipped with a notice.
#   CURATION_TAGS     — space-separated list of DEV.to tags to curate
#                       (default: ai security devops)
#   CURATION_LIMIT    — max articles to output (default: 15)
#   CURATION_OUTPUT   — path where curated JSON is written
#                       (default: /tmp/devto_curation_$(date +%Y%m%d).json)
#   SOCIAL_DIR        — directory containing the Python scripts
#                       (default: directory of this script)
#
# Usage:
#   bash run_weekly.sh            # live run
#   DRY_RUN=1 bash run_weekly.sh  # dry-run all steps
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOCIAL_DIR="${SOCIAL_DIR:-"${SCRIPT_DIR}"}"

CURATION_TAGS="${CURATION_TAGS:-"ai security devops"}"
CURATION_LIMIT="${CURATION_LIMIT:-15}"
CURATION_OUTPUT="${CURATION_OUTPUT:-"/tmp/devto_curation_$(date +%Y%m%d).json"}"

DRY_RUN="${DRY_RUN:-0}"
DRY_RUN_FLAG=""
if [[ "${DRY_RUN}" == "1" ]]; then
    DRY_RUN_FLAG="--dry-run"
    echo "[run_weekly] DRY_RUN=1 — no real HTTP requests will be sent."
fi

# ---------------------------------------------------------------------------
# Step 1: Publish next queued DEV.to article
# ---------------------------------------------------------------------------

echo "[run_weekly] Step 1: Publish DEV.to article"

if [[ -z "${DEVTO_QUEUE_FILE:-}" ]]; then
    echo "[run_weekly]   DEVTO_QUEUE_FILE not set — skipping publish step."
else
    if [[ ! -f "${DEVTO_QUEUE_FILE}" ]]; then
        echo "[run_weekly]   Queue file not found: ${DEVTO_QUEUE_FILE} — skipping." >&2
    else
        NEXT_ARTICLE="$(cat "${DEVTO_QUEUE_FILE}")"
        NEXT_ARTICLE="${NEXT_ARTICLE%%$'\n'*}"  # first line only, trim newline
        if [[ -z "${NEXT_ARTICLE}" ]]; then
            echo "[run_weekly]   Queue file is empty — nothing to publish."
        else
            echo "[run_weekly]   Publishing: ${NEXT_ARTICLE}"
            python3 "${SOCIAL_DIR}/publish_devto.py" \
                --file "${NEXT_ARTICLE}" \
                --publish \
                ${DRY_RUN_FLAG}
            echo "[run_weekly]   Publish complete."
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Step 2: Curate DEV.to articles
# ---------------------------------------------------------------------------

echo "[run_weekly] Step 2: Curate DEV.to articles"

# Convert space-separated tags to --tags args
# shellcheck disable=SC2206
TAGS_ARRAY=(${CURATION_TAGS})

if [[ "${DRY_RUN}" == "1" ]]; then
    python3 "${SOCIAL_DIR}/curate_devto.py" \
        --tags "${TAGS_ARRAY[@]}" \
        --limit "${CURATION_LIMIT}" \
        --dry-run
    echo "[run_weekly]   Dry-run: curation output would be written to ${CURATION_OUTPUT}"
else
    python3 "${SOCIAL_DIR}/curate_devto.py" \
        --tags "${TAGS_ARRAY[@]}" \
        --limit "${CURATION_LIMIT}" \
        > "${CURATION_OUTPUT}"
    echo "[run_weekly]   Curation results written to ${CURATION_OUTPUT}"
fi

# ---------------------------------------------------------------------------
# Step 3: LinkedIn drafting (performed by OpenClaw agent, not this script)
# ---------------------------------------------------------------------------

echo "[run_weekly] Step 3: LinkedIn drafting"
echo "[run_weekly]   This step is handled by the OpenClaw agent."
echo "[run_weekly]   The agent reads ${CURATION_OUTPUT}, drafts a LinkedIn post,"
echo "[run_weekly]   and calls: python3 ${SOCIAL_DIR}/queue_buffer.py --text <post> --link <url>"
echo "[run_weekly]   The post lands in Buffer as a draft requiring manual approval."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "[run_weekly] Done. Check Buffer drafts for the LinkedIn post to approve."
