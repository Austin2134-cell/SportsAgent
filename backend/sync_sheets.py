#!/usr/bin/env python3
"""Manual one-shot sync of Supabase bets → Google Sheet."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv

load_dotenv()

from database import db
from services.sheets_sync import is_configured, sync_bets_to_sheet


def main():
    if not is_configured():
        print("Set GOOGLE_SHEET_ID and GOOGLE_SHEETS_CREDENTIALS_JSON first.")
        sys.exit(1)
    result = sync_bets_to_sheet(db)
    print(f"Synced {result['rows']} rows at {result['synced_at']}")


if __name__ == "__main__":
    main()
