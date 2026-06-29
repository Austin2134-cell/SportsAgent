#!/usr/bin/env python3
"""
One-shot production setup: grade pending bets, backfill bankroll, refresh memory.
Uses SUPABASE_URL + SUPABASE_SERVICE_KEY (no admin JWT required).
Triggered via GitHub Actions workflow "Production Setup" or: python scripts/production_setup.py
See .github/workflows/production-setup.yml
Requires SUPABASE_DB_URL in GitHub Secrets and Cursor Secrets for SQL migrations.
Last verified after DB password reset.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_SERVICE_KEY"):
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        return 1

    from database import db
    from services.grader import grade_all_pending
    from agent.bankroll_backfill import backfill_all_agent_bankrolls
    from learning.memory import refresh_memory_all_users

    print("1/3 Grading pending bets...")
    grade_result = grade_all_pending(db)
    print(f"    {grade_result}")

    print("2/3 Backfilling agent bankrolls from history...")
    backfill_result = backfill_all_agent_bankrolls(db)
    print(
        f"    processed={backfill_result['users_processed']} "
        f"updated={backfill_result['users_updated']}"
    )

    print("3/4 Refreshing user + platform memory...")
    memory_result = refresh_memory_all_users(db)
    print(f"    {memory_result}")

    print("4/4 Syncing Google Sheet...")
    try:
        from services.sheets_sync import is_configured, sync_bets_to_sheet
        if is_configured():
            sheet_result = sync_bets_to_sheet(db)
            print(f"    synced {sheet_result['rows']} rows at {sheet_result['synced_at']}")
        else:
            print("    skipped — GOOGLE_SHEET_ID / credentials not set")
    except Exception as e:
        print(f"    sheet sync failed: {e}")

    # Ensure platform_memory seed row exists (service role bypasses RLS)
    try:
        db.table("platform_memory").upsert(
            {"key": "global", "stats": {}},
            on_conflict="key",
        ).execute()
        print("    platform_memory global row ensured")
    except Exception as e:
        print(f"    platform_memory seed skipped: {e}")

    print("Production setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
