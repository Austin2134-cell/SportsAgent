#!/usr/bin/env python3
"""Run all AgentEdge Supabase migrations in order (idempotent)."""
import os
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"

MIGRATION_ORDER = (
    "002_agentedge_idempotent.sql",
    "003_platform_memory.sql",
)


def parse_postgres_url(db_url: str) -> dict:
    """
    Parse a PostgreSQL URI, handling passwords with special characters (@, #, etc.).
    Supabase format: postgresql://postgres.[ref]:password@host:5432/postgres
    """
    url = db_url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if not url.startswith("postgresql://"):
        raise ValueError("SUPABASE_DB_URL must start with postgresql:// or postgres://")

    rest = url[len("postgresql://") :]
    if "@" not in rest:
        raise ValueError("Invalid SUPABASE_DB_URL — missing @ between credentials and host")

    user_pass, host_part = rest.rsplit("@", 1)
    if ":" not in user_pass:
        raise ValueError("Invalid SUPABASE_DB_URL — missing : between user and password")

    user, password = user_pass.split(":", 1)
    password = unquote(password)

    if "/" not in host_part:
        raise ValueError("Invalid SUPABASE_DB_URL — missing database name after host")

    host_port, dbname = host_part.split("/", 1)
    dbname = dbname.split("?")[0]  # strip query params

    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        port = int(port)
    else:
        host, port = host_port, 5432

    return {
        "host": host,
        "port": port,
        "user": unquote(user),
        "password": password,
        "dbname": dbname,
    }


def connect_postgres(db_url: str):
    import psycopg2

    params = parse_postgres_url(db_url)
    return psycopg2.connect(**params, sslmode="require")


def main() -> int:
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if not db_url:
        print("Missing SUPABASE_DB_URL — add it to GitHub Secrets or backend/.env")
        print("Supabase → Connect → Direct → Session pooler → URI")
        return 1

    try:
        conn = connect_postgres(db_url)
    except Exception as e:
        print(f"Database connection failed: {e}")
        print(
            "Tip: if your password has special characters (@ # % etc.), "
            "URL-encode them in the secret or reset your DB password in "
            "Supabase → Project Settings → Database."
        )
        return 1

    ran = 0
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
