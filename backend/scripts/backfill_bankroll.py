#!/usr/bin/env python3
"""
One-time CLI: rebuild agent_instances.bankroll_current from graded bet history.

Usage:
  cd backend
  python3 scripts/backfill_bankroll.py              # all agent users
  python3 scripts/backfill_bankroll.py --user-id UUID  # single user
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill agent bankroll from graded bets")
    parser.add_argument("--user-id", help="Single user UUID (default: all agent instances)")
    args = parser.parse_args()

    from database import db
    from agent.bankroll_backfill import backfill_all_agent_bankrolls, replay_bankroll_for_user

    if args.user_id:
        result = replay_bankroll_for_user(db, args.user_id)
        print(result)
        return 0 if not result.get("error") else 1

    summary = backfill_all_agent_bankrolls(db)
    print(f"Processed {summary['users_processed']} users, updated {summary['users_updated']}")
    for row in summary["results"]:
        if row.get("skipped"):
            print(f"  skip {row['user_id']}: {row.get('reason')}")
        elif row.get("error"):
            print(f"  error {row['user_id']}: {row['error']}")
        else:
            print(
                f"  {row['user_id']}: ${row['bankroll_starting']:.0f} → "
                f"${row['bankroll_current']:.0f} ({row['bets_replayed']} bets, P&L {row['pnl']:+.2f})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
