"""
run_world_cup_card.py — CLI wrapper for the World Cup daily card.

Scheduled delivery runs on Railway (APScheduler in main.py at 8:50 AM MT).
Use this script for local/manual runs only.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from services.world_cup_card import default_recipient, run_world_cup_card, today_mt


def main():
    parser = argparse.ArgumentParser(description="Generate ESM World Cup daily card")
    parser.add_argument(
        "--email",
        default=default_recipient(),
        help=f"Recipient email (default: {default_recipient()})",
    )
    parser.add_argument(
        "--date",
        default=today_mt(),
        help="Target date YYYY-MM-DD (default: today in Mountain Time)",
    )
    parser.add_argument("--max-plays", type=int, default=5)
    parser.add_argument("--unit-size", type=float, default=50.0)
    parser.add_argument("--no-email", action="store_true", help="Skip email delivery")
    parser.add_argument("--no-persist", action="store_true", help="Skip Supabase log")
    args = parser.parse_args()

    run_world_cup_card(
        target_date=args.date,
        email=args.email,
        send_email=not args.no_email,
        persist=not args.no_persist,
        max_plays=args.max_plays,
        unit_size=args.unit_size,
    )


if __name__ == "__main__":
    main()
