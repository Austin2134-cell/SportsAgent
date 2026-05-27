"""
Bet tracker — persists every official play to a CSV and provides
daily/cumulative record summaries per ESM Operations Addendum format.

CSV columns:
  date, sport, game, bet, market, odds, book, units, confidence,
  result, units_result, post_slate_tag, notes
"""

import csv
import os
from datetime import date, datetime
from typing import Optional
from config import BET_LOG_PATH, UNIT_SIZE_DOLLARS

COLUMNS = [
    "date",
    "sport",
    "game",
    "bet",
    "market",
    "odds",
    "book",
    "units",
    "confidence",
    "result",        # W / L / P / pending
    "units_result",  # positive = won, negative = lost, 0 = push/pending
    "post_slate_tag",
    "notes",
]


def _ensure_file():
    if not os.path.exists(BET_LOG_PATH):
        with open(BET_LOG_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()


def log_plays(plays: list[dict], run_date: str = None) -> None:
    """
    Write official plays from today's card to the CSV.
    plays: list of dicts matching the official_plays schema from system_prompt.py
    """
    _ensure_file()
    today = run_date or date.today().isoformat()

    with open(BET_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        for play in plays:
            writer.writerow({
                "date": today,
                "sport": play.get("sport", ""),
                "game": play.get("game", ""),
                "bet": play.get("bet", ""),
                "market": play.get("market", ""),
                "odds": play.get("odds", ""),
                "book": play.get("book", ""),
                "units": play.get("units", 2),
                "confidence": play.get("confidence", ""),
                "result": "pending",
                "units_result": 0,
                "post_slate_tag": "",
                "notes": play.get("edge_summary", ""),
            })


def update_result(
    bet_date: str,
    bet_description: str,
    result: str,
    units_result: float,
    post_slate_tag: str = "",
    notes: str = "",
) -> bool:
    """
    Update a pending bet with its result.
    result: 'W', 'L', or 'P'
    units_result: net units (e.g., +1.91 for a 2u win at -110, -2.0 for a loss)
    Returns True if a matching row was found and updated.
    """
    _ensure_file()
    rows = []
    updated = False

    with open(BET_LOG_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (
                row["date"] == bet_date
                and bet_description.lower() in row["bet"].lower()
                and row["result"] == "pending"
                and not updated
            ):
                row["result"] = result.upper()
                row["units_result"] = round(units_result, 2)
                row["post_slate_tag"] = post_slate_tag
                if notes:
                    row["notes"] = notes
                updated = True
            rows.append(row)

    if updated:
        with open(BET_LOG_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    return updated


def get_daily_record(target_date: str = None) -> dict:
    """Return W-L-P record and units for a specific date."""
    _ensure_file()
    day = target_date or date.today().isoformat()
    return _summarize(_load_rows(date_filter=day))


def get_all_time_record() -> dict:
    """Return cumulative W-L-P record and units across all logged bets."""
    _ensure_file()
    return _summarize(_load_rows())


def get_pending_bets(target_date: str = None) -> list[dict]:
    """Return all bets still marked 'pending' for a given date (default: today)."""
    _ensure_file()
    day = target_date or date.today().isoformat()
    return [r for r in _load_rows(date_filter=day) if r["result"] == "pending"]


def wagers_placed_today(target_date: str = None) -> int:
    """Return count of bets logged today (to enforce the 5-wager daily cap)."""
    _ensure_file()
    day = target_date or date.today().isoformat()
    return len(_load_rows(date_filter=day))


def format_record_string(record: dict) -> str:
    """
    Format per ESM Operations Addendum:
    [DATE] | [SPORT] Record: W-L-P | Units: +/- X.X | ROI: X.X%
    """
    w = record["wins"]
    l = record["losses"]
    p = record["pushes"]
    units = record["net_units"]
    roi = record["roi_pct"]
    total_wagered = record["total_units_wagered"]

    sign = "+" if units >= 0 else ""
    roi_sign = "+" if roi >= 0 else ""

    return (
        f"Record: {w}-{l}-{p} | "
        f"Units: {sign}{units:.1f} | "
        f"Wagered: {total_wagered:.1f}u | "
        f"ROI: {roi_sign}{roi:.1f}%"
    )


def format_dollar_summary(record: dict) -> str:
    """Show dollar P&L based on configured unit size."""
    net = record["net_units"] * UNIT_SIZE_DOLLARS
    sign = "+" if net >= 0 else ""
    return f"P&L: {sign}${net:,.2f} (at ${UNIT_SIZE_DOLLARS:.0f}/unit)"


def _load_rows(date_filter: str = None) -> list[dict]:
    rows = []
    with open(BET_LOG_PATH, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if date_filter and row["date"] != date_filter:
                continue
            rows.append(row)
    return rows


def _summarize(rows: list[dict]) -> dict:
    wins = losses = pushes = 0
    net_units = 0.0
    total_wagered = 0.0

    for row in rows:
        if row["result"] == "pending":
            continue
        units = float(row.get("units", 2))
        units_result = float(row.get("units_result", 0))
        total_wagered += units

        if row["result"] == "W":
            wins += 1
            net_units += units_result
        elif row["result"] == "L":
            losses += 1
            net_units += units_result  # will be negative
        elif row["result"] == "P":
            pushes += 1

    total_settled = wins + losses + pushes
    roi_pct = (net_units / total_wagered * 100) if total_wagered > 0 else 0.0

    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "total_settled": total_settled,
        "net_units": round(net_units, 2),
        "total_units_wagered": round(total_wagered, 2),
        "roi_pct": round(roi_pct, 1),
    }


def calculate_win_units(units: float, odds: int) -> float:
    """Calculate net units won given stake and American odds."""
    if odds >= 0:
        return round(units * (odds / 100), 2)
    else:
        return round(units * (100 / abs(odds)), 2)
