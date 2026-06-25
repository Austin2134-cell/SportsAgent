"""CLI wrapper for the MLB/major-league daily ESM card."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from services.daily_esm_card import default_recipient, run_daily_esm_card, today_mt


def main():
    parser = argparse.ArgumentParser(description="Generate MLB/ESM daily card (separate from World Cup)")
    parser.add_argument("--email", default=default_recipient())
    parser.add_argument("--date", default=today_mt())
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_daily_esm_card(
        target_date=args.date,
        email=args.email,
        send_email=not args.no_email,
        force=args.force,
        print_output=True,
    )


if __name__ == "__main__":
    main()
