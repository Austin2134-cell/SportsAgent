"""
Autonomous daily scheduler for the ESM Betting Agent.

Runs the agent once per day at a configured time (default: 11:00 AM MDT).
This is designed to run as a persistent background process on your Mac.

Usage:
  python scheduler.py                  # run on schedule indefinitely
  python scheduler.py --run-now        # fire immediately, then continue schedule
  python scheduler.py --time 09:30     # override run time (24h format, MDT)

To run autonomously at startup:
  See setup instructions at the bottom of this file.
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import schedule

from config import TIMEZONE, OUTPUT_DIR
from esm_agent import run_daily_card

MDT = ZoneInfo(TIMEZONE)
LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "agent.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ESM] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("esm_scheduler")


def _job():
    now = datetime.now(MDT)
    log.info(f"Daily card job triggered at {now.strftime('%Y-%m-%d %H:%M %Z')}")
    try:
        card = run_daily_card()
        official_count = len(card.get("official_plays", []))
        grade = card.get("slate_grade", "?")
        log.info(f"Card complete. Slate: {grade} | Plays: {official_count}")
    except Exception as e:
        log.error(f"Agent run failed: {e}", exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="ESM Agent Scheduler")
    parser.add_argument(
        "--time",
        type=str,
        default="11:00",
        help="Daily run time in 24h MDT format (e.g. 09:30). Default: 11:00",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the agent immediately before starting the schedule loop",
    )
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log.info(f"ESM Agent Scheduler starting. Daily run at {args.time} MDT.")

    if args.run_now:
        log.info("--run-now flag set. Firing immediately...")
        _job()

    schedule.every().day.at(args.time).do(_job)
    log.info(f"Next scheduled run: {schedule.next_run()}")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()


# ─────────────────────────────────────────────────────────────────────────────
# SETUP: Run the agent automatically at login on macOS
# ─────────────────────────────────────────────────────────────────────────────
#
# Option 1 — launchd (recommended, runs silently in background)
# ─────────────────────────────────────────────────────────────
# 1. Find your Python path:
#      which python3
#    Example: /opt/homebrew/bin/python3
#
# 2. Create the plist file:
#      nano ~/Library/LaunchAgents/com.esm.agent.plist
#
# 3. Paste this (update paths to match yours):
#
#   <?xml version="1.0" encoding="UTF-8"?>
#   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
#     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
#   <plist version="1.0">
#   <dict>
#     <key>Label</key>
#     <string>com.esm.agent</string>
#     <key>ProgramArguments</key>
#     <array>
#       <string>/opt/homebrew/bin/python3</string>
#       <string>/Users/austin/Claude Agentic AI/esm_agent/scheduler.py</string>
#     </array>
#     <key>RunAtLoad</key>
#     <true/>
#     <key>KeepAlive</key>
#     <true/>
#     <key>StandardOutPath</key>
#     <string>/Users/austin/Claude Agentic AI/esm_agent/data/agent.log</string>
#     <key>StandardErrorPath</key>
#     <string>/Users/austin/Claude Agentic AI/esm_agent/data/agent_error.log</string>
#     <key>WorkingDirectory</key>
#     <string>/Users/austin/Claude Agentic AI/esm_agent</string>
#   </dict>
#   </plist>
#
# 4. Load it:
#      launchctl load ~/Library/LaunchAgents/com.esm.agent.plist
#
# 5. Check it's running:
#      launchctl list | grep esm
#
# 6. To stop:
#      launchctl unload ~/Library/LaunchAgents/com.esm.agent.plist
#
# ─────────────────────────────────────────────────────────────────────────────
# Option 2 — cron (simpler, no auto-restart if process dies)
# ─────────────────────────────────────────────────────────────
# Run: crontab -e
# Add this line (fires at 11 AM MDT every day):
#   0 11 * * * cd "/Users/austin/Claude Agentic AI/esm_agent" && python3 esm_agent.py >> data/agent.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────
