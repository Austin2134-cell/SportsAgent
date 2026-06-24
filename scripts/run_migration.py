#!/usr/bin/env python3
"""Run AgentEdge Supabase migration using SUPABASE_DB_URL or service key from backend/.env"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")

MIGRATION = ROOT / "supabase" / "migrations" / "002_agentedge_idempotent.sql"
if not MIGRATION.exists():
    MIGRATION = ROOT / "supabase" / "migrations" / "001_agentedge.sql"


def main():
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("Missing SUPABASE_DB_URL in backend/.env")
        print("Get it from: Supabase → Project Settings → Database → Connection string (URI)")
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("Installing psycopg2-binary...")
        os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
        import psycopg2

    sql = MIGRATION.read_text()
    print(f"Running migration: {MIGRATION.name}")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql)
    cur.close()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
