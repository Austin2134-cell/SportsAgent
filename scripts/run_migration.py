#!/usr/bin/env python3
"""Run all AgentEdge Supabase migrations in order (idempotent)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"

MIGRATION_ORDER = (
    "002_agentedge_idempotent.sql",
    "003_platform_memory.sql",
)


def main() -> int:
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("Missing SUPABASE_DB_URL — add it to GitHub Secrets or backend/.env")
        print("Supabase → Project Settings → Database → Connection string (URI)")
        return 1

    try:
        import psycopg2
    except ImportError:
        os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
        import psycopg2

    ran = 0
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    for name in MIGRATION_ORDER:
        path = MIGRATIONS_DIR / name
        if not path.exists():
            print(f"Skip missing migration: {name}")
            continue
        print(f"Running migration: {name}")
        cur.execute(path.read_text())
        ran += 1
    cur.close()
    conn.close()
    print(f"Migration complete ({ran} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
