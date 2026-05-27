"""
seed_supabase.py — One-time import of bets.csv history into Supabase.

Prerequisites:
  1. Run the schema SQL in Supabase Dashboard → SQL Editor:
     Open: /Users/austin/Claude Agentic AI/edgebet/supabase/schema.sql
     Paste the entire contents → Run

  2. Then run this script:
     python3 seed_supabase.py

It will create your user account and import all historical bets.
"""

import csv
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / "edgebet/backend/.env.bak")

BETS_CSV = Path(__file__).parent / "data" / "bets.csv"

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://nlfalrpuspdezfnlakrv.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5sZmFscnB1c3BkZXpmbmxha3J2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODY5MzY2NSwiZXhwIjoyMDk0MjY5NjY1fQ.iToT857lsEHNrjn1yqtjwd9aeO5YdgkrauezHXuwj1Q"
)

USER_EMAIL = "Austin.Noyes21@gmail.com"
USER_PASSWORD = "ESMedge2026!"
USER_FULL_NAME = "Austin Noyes"


def main():
    try:
        from supabase import create_client
    except ImportError:
        print("Missing supabase. Run: pip install supabase")
        sys.exit(1)

    db = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # ── 1. Create or find user ──────────────────────────────────
    print("Creating user account...")
    user_id = None

    try:
        resp = db.auth.admin.create_user({
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
            "email_confirm": True,
        })
        user_id = resp.user.id
        print(f"  Created: {user_id}")
    except Exception as e:
        err = str(e)
        if "already been registered" in err or "already exists" in err:
            print("  User already exists, looking up...")
        else:
            print(f"  Create failed: {err}")
            print("\n  *** Make sure you've run schema.sql in the Supabase SQL Editor first! ***")
            print(f"  Schema file: /Users/austin/Claude Agentic AI/edgebet/supabase/schema.sql")
            sys.exit(1)

    # Find existing user if create failed
    if not user_id:
        try:
            users = db.auth.admin.list_users()
            for u in users:
                if hasattr(u, 'email') and u.email == USER_EMAIL:
                    user_id = u.id
                    print(f"  Found existing: {user_id}")
                    break
        except Exception as e:
            print(f"  Could not list users: {e}")

    if not user_id:
        print("Could not get user_id. Exiting.")
        sys.exit(1)

    # ── 2. Update profile + preferences ────────────────────────
    print("Setting up profile...")
    db.table("profiles").update({
        "full_name": USER_FULL_NAME,
        "is_active": True,
        "is_admin": True,
    }).eq("id", user_id).execute()

    db.table("preferences").upsert({
        "user_id": user_id,
        "sports": ["MLB", "NBA", "NHL"],
        "bet_types": ["player_props"],
        "risk_level": "MEDIUM",
        "max_plays": 5,
        "unit_size": 50.0,
        "include_parlays": False,
    }, on_conflict="user_id").execute()
    print("  Profile + preferences set")

    # ── 3. Check for existing bets ──────────────────────────────
    existing = db.table("bets").select("id", count="exact").eq("user_id", user_id).execute()
    if existing.count and existing.count > 0:
        print(f"\nFound {existing.count} existing bets. Delete them first? [y/N]")
        ans = input().strip().lower()
        if ans == "y":
            db.table("bets").delete().eq("user_id", user_id).execute()
            print("  Cleared existing bets")
        else:
            print("Skipping seed — bets already exist.")
            sys.exit(0)

    # ── 4. Seed bets from CSV ───────────────────────────────────
    print(f"\nReading {BETS_CSV}...")
    rows = []
    with open(BETS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"Inserting {len(rows)} bets...")
    inserted = 0
    skipped = 0

    for row in rows:
        try:
            units = float(row.get("units") or 2)
            units_result = float(row.get("units_result") or 0)
            odds_raw = row.get("odds", "")
            odds = int(float(odds_raw)) if odds_raw else -110

            result = row.get("result", "pending").strip()
            if result not in ("W", "L", "P", "pending"):
                result = "pending"

            db.table("bets").insert({
                "user_id": user_id,
                "card_id": None,
                "date": row["date"],
                "sport": row.get("sport", ""),
                "game": row.get("game", ""),
                "bet": row.get("bet", ""),
                "market": row.get("market", ""),
                "odds": odds,
                "book": row.get("book", "DraftKings"),
                "units": units,
                "confidence": row.get("confidence", "MEDIUM"),
                "result": result,
                "units_result": units_result,
                "post_slate_tag": row.get("post_slate_tag", ""),
                "notes": row.get("notes", ""),
            }).execute()
            inserted += 1
        except Exception as e:
            print(f"  Skipped row ({row.get('bet', '?')}): {e}")
            skipped += 1

    print(f"\nDone! Inserted {inserted} bets, skipped {skipped}")
    print(f"\nLogin at your EdgeBet frontend:")
    print(f"  Email:    {USER_EMAIL}")
    print(f"  Password: {USER_PASSWORD}")


if __name__ == "__main__":
    main()
