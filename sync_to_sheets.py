"""
sync_to_sheets.py — Mirror bets.csv to a Google Sheet for on-the-go viewing.

Setup (one-time, ~3 minutes):
  1. Go to https://console.cloud.google.com
  2. Create a project (or pick existing one)
  3. Enable "Google Sheets API" and "Google Drive API"
  4. Go to IAM & Admin → Service Accounts → Create Service Account
  5. Click the new account → Keys → Add Key → JSON → Download
  6. Save that JSON file as: esm_agent/google_service_account.json
  7. Go to your Google Sheet → Share → paste the service account email (ends in @...iam.gserviceaccount.com)
     Give it "Editor" access

Usage:
  python3 sync_to_sheets.py                    # full sync (clears + re-writes)
  python3 sync_to_sheets.py --sheet "ESM Bets" # use a specific sheet name
"""

import csv
import json
import os
import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BETS_CSV = Path(__file__).parent / "data" / "bets.csv"
SERVICE_ACCOUNT_FILE = Path(__file__).parent / "google_service_account.json"
SPREADSHEET_NAME = os.getenv("GSHEETS_SPREADSHEET_NAME", "ESM Bets Tracker")
SPREADSHEET_ID = os.getenv("GSHEETS_SPREADSHEET_ID", "1Vp9Ab79Lq7pG0rVGxN2r_c6tSuOtiaVHW5VgdeI35zM")

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Missing gspread. Run: pip install gspread")
    sys.exit(1)


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    if not SERVICE_ACCOUNT_FILE.exists():
        print(f"ERROR: Service account JSON not found at {SERVICE_ACCOUNT_FILE}")
        print("Follow the setup steps at the top of this file.")
        sys.exit(1)
    creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    return gspread.authorize(creds)


def load_bets():
    rows = []
    with open(BETS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def calculate_record(rows):
    wins = losses = pushes = pending = 0
    net_units = 0.0
    wagered = 0.0
    for row in rows:
        result = row.get("result", "").strip()
        units = float(row.get("units") or 0)
        units_result = float(row.get("units_result") or 0)
        if result == "pending":
            pending += 1
            continue
        if result == "W":
            wins += 1
            net_units += units_result
            wagered += units
        elif result == "L":
            losses += 1
            net_units += units_result
            wagered += units
        elif result == "P":
            pushes += 1
    roi = (net_units / wagered * 100) if wagered > 0 else 0.0
    sign = "+" if net_units >= 0 else ""
    return {
        "record": f"{wins}W - {losses}L - {pushes}P",
        "net_units": f"{sign}{net_units:.2f}u",
        "net_dollars": f"${net_units * 50:+.0f}",
        "roi": f"{roi:+.1f}%",
        "total_graded": wins + losses + pushes,
        "pending": pending,
    }


def sync(sheet_name_override=None):
    client = get_client()

    # Open by ID (most reliable — avoids Drive create permission issues)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    print(f"Opened sheet: {spreadsheet.title}")

    rows = load_bets()
    record = calculate_record(rows)
    today = date.today().isoformat()

    # ── Sheet 1: BETS ───────────────────────────────────────────
    try:
        bets_ws = spreadsheet.worksheet("Bets")
    except gspread.WorksheetNotFound:
        bets_ws = spreadsheet.add_worksheet("Bets", rows=500, cols=14)

    headers = ["date", "sport", "game", "bet", "market", "odds", "book",
               "units", "confidence", "result", "units_result", "post_slate_tag", "notes"]

    data = [headers]
    for row in rows:
        data.append([row.get(h, "") for h in headers])

    bets_ws.clear()
    bets_ws.update(data, value_input_option="USER_ENTERED")

    # Freeze header row, bold it
    bets_ws.freeze(rows=1)
    _format_header(spreadsheet, bets_ws)
    _color_results(spreadsheet, bets_ws, data)

    print(f"Bets sheet: {len(rows)} rows written")

    # ── Sheet 2: RECORD ─────────────────────────────────────────
    try:
        rec_ws = spreadsheet.worksheet("Record")
    except gspread.WorksheetNotFound:
        rec_ws = spreadsheet.add_worksheet("Record", rows=20, cols=4)

    rec_data = [
        ["Metric", "Value", "", ""],
        ["Last updated", today, "", ""],
        ["", "", "", ""],
        ["Record", record["record"], "", ""],
        ["Net units", record["net_units"], "", ""],
        ["Net $$ (at $50/unit)", record["net_dollars"], "", ""],
        ["ROI", record["roi"], "", ""],
        ["Total graded", str(record["total_graded"]), "", ""],
        ["Pending bets", str(record["pending"]), "", ""],
    ]
    rec_ws.clear()
    rec_ws.update(rec_data, value_input_option="USER_ENTERED")
    rec_ws.freeze(rows=1)

    print(f"Record sheet updated: {record['record']} | {record['net_units']} | ROI {record['roi']}")
    print(f"\nSheet URL: {spreadsheet.url}")
    return spreadsheet.url


def _format_header(spreadsheet, worksheet):
    """Bold the header row."""
    try:
        spreadsheet.batch_update({
            "requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": worksheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor,foregroundColor)",
                }
            }]
        })
    except Exception:
        pass  # formatting is optional


def _color_results(spreadsheet, worksheet, data):
    """Green W rows, red L rows, grey P rows."""
    requests = []
    for i, row in enumerate(data[1:], start=1):  # skip header
        result = row[9] if len(row) > 9 else ""
        if result == "W":
            color = {"red": 0.85, "green": 0.94, "blue": 0.83}
        elif result == "L":
            color = {"red": 0.96, "green": 0.80, "blue": 0.80}
        elif result == "P":
            color = {"red": 0.93, "green": 0.93, "blue": 0.93}
        elif result == "pending":
            color = {"red": 1.0, "green": 0.95, "blue": 0.80}
        else:
            continue
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": worksheet.id,
                    "startRowIndex": i,
                    "endRowIndex": i + 1,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })
    if requests:
        try:
            spreadsheet.batch_update({"requests": requests})
        except Exception:
            pass


if __name__ == "__main__":
    sheet_arg = None
    if "--sheet" in sys.argv:
        idx = sys.argv.index("--sheet")
        if idx + 1 < len(sys.argv):
            sheet_arg = sys.argv[idx + 1]
    url = sync(sheet_arg)
    print(f"\nOpen on mobile: {url}")
