"""
Push Supabase bets to a Google Sheet (full sync on each trigger).

Tabs created:
  All Bets         — every bet, all columns (including pending)
  Overall Record   — lifetime W-L-P, units, ROI
  Record by Sport  — breakdown per sport

Unit columns follow ESM rules:
  Units Risked = stake; Units Won = profit at odds (wins only);
  Units Lost = full risk lost (losses only); Net Units = W/L P/L.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from services.units import aggregate_record, format_net_units, format_units_lost, format_units_won, net_units, units_lost, units_won

BETS_HEADERS = [
    "Date",
    "Sport",
    "Game",
    "Bet",
    "Market",
    "Odds",
    "Units Risked",
    "Book",
    "Confidence",
    "Result",
    "Units Won",
    "Units Lost",
    "Net Units",
    "Tag",
    "Notes",
    "Bet ID",
    "Card ID",
    "Created",
    "Last Synced",
]

OVERALL_RECORD_HEADERS = ["Metric", "Value"]

BY_SPORT_HEADERS = [
    "Sport",
    "Wins",
    "Losses",
    "Pushes",
    "Pending",
    "Record",
    "Units Risked",
    "Units Won",
    "Units Lost",
    "Net Units",
    "ROI %",
    "Total Plays",
]


def is_configured() -> bool:
    return bool(os.getenv("GOOGLE_SHEET_ID") and _credentials_info())


def maybe_sync_sheets(db, *, reason: str = "") -> Optional[dict]:
    if not is_configured():
        return None
    try:
        result = sync_bets_to_sheet(db)
        label = f" ({reason})" if reason else ""
        print(f"[sheets_sync] Synced {result['rows']} bet(s) to Google Sheet{label}")
        return result
    except Exception as e:
        print(f"[sheets_sync] Sync failed{(' — ' + reason) if reason else ''}: {e}")
        return None


def sync_bets_to_sheet(db) -> dict:
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    bets_tab = os.getenv("GOOGLE_SHEETS_TAB_BETS", "All Bets")
    record_tab = os.getenv("GOOGLE_SHEETS_TAB_RECORD", "Overall Record")
    by_sport_tab = os.getenv("GOOGLE_SHEETS_TAB_BY_SPORT", "Record by Sport")
    sync_email = (os.getenv("GOOGLE_SHEETS_SYNC_EMAIL") or "").strip().lower()

    bets = _fetch_bets(db, sync_email)
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    bet_rows = [_bet_to_row(b, synced_at) for b in bets]
    overall_rows = _build_overall_record_rows(bets, synced_at)
    sport_rows = _build_by_sport_rows(bets)

    client = _get_gspread_client()
    spreadsheet = client.open_by_key(sheet_id)

    _write_worksheet(spreadsheet, bets_tab, BETS_HEADERS, bet_rows)
    _write_worksheet(spreadsheet, record_tab, OVERALL_RECORD_HEADERS, overall_rows)
    _write_worksheet(spreadsheet, by_sport_tab, BY_SPORT_HEADERS, sport_rows)

    _delete_worksheet_if_exists(spreadsheet, "Record")
    _delete_worksheet_if_exists(spreadsheet, "AgentEdge Bets")

    return {"rows": len(bet_rows), "sheet_id": sheet_id, "synced_at": synced_at}


def _fetch_bets(db, sync_email: str) -> list[dict]:
    result = db.table("bets").select("*").order("date", desc=True).execute()
    bets = result.data or []
    if not sync_email:
        return bets
    profiles = _fetch_profile_map(db)
    allowed = {uid for uid, email in profiles.items() if email == sync_email}
    return [b for b in bets if b.get("user_id") in allowed]


def _fetch_profile_map(db) -> dict[str, str]:
    result = db.table("profiles").select("id, email").execute()
    return {
        row["id"]: (row.get("email") or "").strip().lower()
        for row in (result.data or [])
    }


def _bet_to_row(bet: dict, synced_at: str) -> list:
    odds = int(bet.get("odds") or 0)
    units_risked = float(bet.get("units") or 0)
    result = (bet.get("result") or "pending").upper()

    created = bet.get("created_at") or ""
    if created and "T" in str(created):
        created = str(created).replace("T", " ")[:19]

    return [
        bet.get("date", ""),
        bet.get("sport", ""),
        bet.get("game", ""),
        bet.get("bet", ""),
        bet.get("market", ""),
        f"{odds:+d}" if odds else "",
        units_risked,
        bet.get("book", ""),
        bet.get("confidence", ""),
        result,
        format_units_won(units_won(bet)),
        format_units_lost(units_lost(bet)),
        format_net_units(net_units(bet)),
        bet.get("post_slate_tag", ""),
        bet.get("notes", ""),
        bet.get("id", ""),
        bet.get("card_id", ""),
        created,
        synced_at,
    ]


def _build_overall_record_rows(bets: list[dict], synced_at: str) -> list[list]:
    graded = [b for b in bets if b.get("result") not in (None, "pending")]
    pending = [b for b in bets if b.get("result") == "pending"]
    rec = aggregate_record(graded)

    return [
        ["Last Synced", synced_at],
        ["Total Plays", str(len(bets))],
        ["Pending", str(len(pending))],
        ["Graded", str(len(graded))],
        ["Record (W-L-P)", rec["record_str"]],
        ["Wins", str(rec["wins"])],
        ["Losses", str(rec["losses"])],
        ["Pushes", str(rec["pushes"])],
        ["Units Risked", f"{rec['units_risked']:.1f}u"],
        ["Units Won", f"{rec['units_won']:.1f}u"],
        ["Units Lost", f"{rec['units_lost']:.1f}u"],
        ["Net Units", rec["units_str"]],
        ["ROI %", f"{rec['roi_pct']:+.1f}%"],
    ]


def _build_by_sport_rows(bets: list[dict]) -> list[list]:
    by_sport: dict[str, list] = defaultdict(list)
    for b in bets:
        by_sport[(b.get("sport") or "Unknown").upper()].append(b)

    rows = []
    for sport in sorted(by_sport):
        sport_bets = by_sport[sport]
        graded = [b for b in sport_bets if b.get("result") not in (None, "pending")]
        pending = sum(1 for b in sport_bets if b.get("result") == "pending")
        rec = aggregate_record(graded)
        rows.append([
            sport,
            rec["wins"],
            rec["losses"],
            rec["pushes"],
            pending,
            rec["record_str"],
            rec["units_risked"],
            rec["units_won"],
            rec["units_lost"],
            rec["net_units"],
            rec["roi_pct"],
            len(sport_bets),
        ])
    return rows


def _calc_record(bets: list[dict]) -> dict:
    """Backward-compatible wrapper."""
    return aggregate_record(bets)


def _write_worksheet(spreadsheet, title: str, headers: list, rows: list[list]):
    import gspread

    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=max(len(rows) + 1, 100), cols=len(headers))

    ws.clear()
    ws.update([headers] + rows, value_input_option="USER_ENTERED")
    ws.freeze(rows=1)


def _delete_worksheet_if_exists(spreadsheet, title: str):
    import gspread

    try:
        ws = spreadsheet.worksheet(title)
        spreadsheet.del_worksheet(ws)
    except gspread.WorksheetNotFound:
        pass


def _get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(_credentials_info(), scopes=scopes)
    return gspread.authorize(creds)


def _credentials_info() -> dict:
    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
    if raw:
        return json.loads(raw)
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}
