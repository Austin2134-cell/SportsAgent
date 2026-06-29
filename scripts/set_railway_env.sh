#!/bin/bash
# Run after: railway login && railway link (in backend/)
# Reads backend/.env and pushes AgentEdge vars to Railway

set -e
cd "$(dirname "$0")/../backend"

if ! railway whoami &>/dev/null; then
  echo "Run: railway login"
  exit 1
fi

if [ ! -f .env ]; then
  echo "Create backend/.env first (copy from .env.example)"
  exit 1
fi

set -a
source .env
set +a

railway variables set \
  ODDS_PRIMARY_SOURCE="${ODDS_PRIMARY_SOURCE:-sgo}" \
  TOA_MONTHLY_QUOTA="${TOA_MONTHLY_QUOTA:-20000}" \
  TOA_RESERVE="${TOA_RESERVE:-500}" \
  TOA_PROPS_MIN="${TOA_PROPS_MIN:-1000}" \
  TOA_MAX_CREDITS_PER_SNAPSHOT="${TOA_MAX_CREDITS_PER_SNAPSHOT:-150}" \
  TOA_MORNING_SNAPSHOT="${TOA_MORNING_SNAPSHOT:-true}" \
  SGO_MONTHLY_OBJECTS="${SGO_MONTHLY_OBJECTS:-2500}" \
  SGO_RESERVE="${SGO_RESERVE:-200}" \
  ODDS_POLL_INTERVAL_MINUTES="${ODDS_POLL_INTERVAL_MINUTES:-360}" \
  AGENT_SCAN_INTERVAL_MINUTES="${AGENT_SCAN_INTERVAL_MINUTES:-180}" \
  SNAPSHOT_MAX_AGE_MINUTES="${SNAPSHOT_MAX_AGE_MINUTES:-360}" \
  ODDS_API_KEY="${ODDS_API_KEY}" \
  SGO_API_KEY="${SGO_API_KEY}" \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  SUPABASE_URL="${SUPABASE_URL}" \
  SUPABASE_SERVICE_KEY="${SUPABASE_SERVICE_KEY}" \
  FRONTEND_URL="${FRONTEND_URL}" \
  TIMEZONE="${TIMEZONE:-America/Denver}" \
  WC_CARD_ENABLED="${WC_CARD_ENABLED:-true}" \
  WC_CARD_USER_EMAIL="${WC_CARD_USER_EMAIL:-austin.noyes21@gmail.com}" \
  EMAIL_FROM="${EMAIL_FROM:-cards@edgebet.com}" \
  EMAIL_SMTP_HOST="${EMAIL_SMTP_HOST}" \
  EMAIL_SMTP_PORT="${EMAIL_SMTP_PORT:-587}" \
  EMAIL_SMTP_USER="${EMAIL_SMTP_USER}" \
  EMAIL_SMTP_PASS="${EMAIL_SMTP_PASS}" \
  GOOGLE_SHEET_ID="${GOOGLE_SHEET_ID}" \
  GOOGLE_SHEETS_SYNC_EMAIL="${GOOGLE_SHEETS_SYNC_EMAIL:-austin.noyes21@gmail.com}" \
  GOOGLE_SHEETS_CREDENTIALS_JSON="${GOOGLE_SHEETS_CREDENTIALS_JSON}"

echo "Railway env vars set. Trigger redeploy from Railway dashboard or: railway up"
