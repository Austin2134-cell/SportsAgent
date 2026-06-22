"""
Push Supabase bets to a Google Sheet (full sync on each trigger).

Tabs created:
  All Bets         — every bet, all columns (including pending)
  Overall Record   — lifetime W-L-P, units, ROI
  Record by Sport  — breakdown per sport

Requires:
  GOOGLE_SHEET_ID
  GOOGLE_SHEETS_CREDENTIALS_JSON
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

BETS_HEADERS = [
    "Date",
    "Sport",
    "Game",
    "Bet",
    "Market",
    "Odds",
    "Units",
    "Book",
    "Confidence",
    "Result",
    "Units P/L",
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
    "Net Units",
    "Units Wagered",
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
    profiles = _fetch_profile_map(db)
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    bet_rows = [_bet_to_row(b, synced_at) for b in bets]
    overall_rows = _build_overall_record_rows(bets, synced_at)
    sport_rows = _build_by_sport_rows(bets)

    client = _get_gspread_client()
    spreadsheet = client.open_by_key(sheet_id)

    _write_worksheet(spreadsheet, bets_tab, BETS_HEADERS, bet_rows)
    _write_worksheet(spreadsheet, record_tab, OVERALL_RECORD_HEADERS, overall_rows)
    _write_worksheet(spreadsheet, by_sport_tab, BY_SPORT_HEADERS, sport_rows)

    # Remove legacy combined tab if present
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
    units = float(bet.get("units") or 0)
    units_result = bet.get("units_result")
    result = (bet.get("result") or "pending").upper()
    pl = ""
    if result not in ("PENDING", "P"):
        pl = f"{float(units_result or 0):+.2f}"

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
        units,
        bet.get("book", ""),
        bet.get("confidence", ""),
        result,
        pl,
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
    rec = _calc_record(graded)

    return [
        ["Last Synced", synced_at],
        ["Total Plays", str(len(bets))],
        ["Pending", str(len(pending))],
        ["Graded", str(len(graded))],
        ["Record (W-L-P)", rec["record_str"]],
        ["Wins", str(rec["wins"])],
        ["Losses", str(rec["losses"])],
        ["Pushes", str(rec["pushes"])],
        ["Net Units", rec["units_str"]],
        ["Units Wagered", f"{rec['wagered']:.1f}u"],
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
        rec = _calc_record(graded)
        rows.append([
            sport,
            rec["wins"],
            rec["losses"],
            rec["pushes"],
            pending,
            rec["record_str"],
            rec["net_units"],
            rec["wagered"],
            rec["roi_pct"],
            len(sport_bets),
        ])
    return rows


def _calc_record(bets: list[dict]) -> dict:
    wins = losses = pushes = 0
    net_units = 0.0
    wagered = 0.0
    for bet in bets:
        units = float(bet.get("units", 2))
        units_result = float(bet.get("units_result", 0))
        wagered += units
        r = bet.get("result", "")
        if r == "W":
            wins += 1
            net_units += units_result
        elif r == "L":
            losses += 1
            net_units += units_result
        elif r == "P":
            pushes += 1
    roi = (net_units / wagered * 100) if wagered > 0 else 0.0
    sign = "+" if net_units >= 0 else ""
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "net_units": round(net_units, 2),
        "wagered": round(wagered, 2),
        "roi_pct": round(roi, 1),
        "record_str": f"{wins}-{losses}-{pushes}",
        "units_str": f"{sign}{net_units:.1f}u",
    }


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
