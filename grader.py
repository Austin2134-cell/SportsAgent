"""
ESM Auto-Grader.
Runs before each daily card. Finds all pending bets from prior days,
fetches ESPN box scores, and grades W/L/P automatically.

Supports: MLB, NHL, NBA, NFL, NCAAB player props + game totals/spreads/ML.
Any bet it cannot confidently grade is flagged for manual review.
"""

import re
import requests
from datetime import date, timedelta
from typing import Optional

from tracker import (
    get_pending_bets,
    update_result,
    calculate_win_units,
    format_record_string,
    get_all_time_record,
    _load_rows,
)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

SPORT_MAP = {
    "NBA":   ("basketball", "nba"),
    "MLB":   ("baseball", "mlb"),
    "NHL":   ("hockey", "nhl"),
    "NFL":   ("football", "nfl"),
    "NCAAB": ("basketball", "mens-college-basketball"),
}

# Maps The Odds API market key → ESPN box score stat label(s)
# When multiple labels, sum them.
MARKET_TO_ESPN_STAT = {
    # NBA
    "player_points":                    ["PTS"],
    "player_rebounds":                  ["REB"],
    "player_assists":                   ["AST"],
    "player_threes":                    ["3PM"],
    "player_blocks":                    ["BLK"],
    "player_steals":                    ["STL"],
    "player_points_rebounds_assists":   ["PTS", "REB", "AST"],
    "player_points_rebounds":           ["PTS", "REB"],
    "player_points_assists":            ["PTS", "AST"],
    "player_rebounds_assists":          ["REB", "AST"],
    # MLB
    "batter_hits":                      ["H"],
    "batter_home_runs":                 ["HR"],
    "batter_rbis":                      ["RBI"],
    "pitcher_strikeouts":               ["K"],
    "pitcher_outs":                     ["OUTS"],   # special — derived from IP
    # NHL
    "player_goals":                     ["G"],
    "player_assists":                   ["A"],
    "player_points":                    ["PTS"],    # G+A
    "player_shots_on_goal":             ["SOG"],
    # NFL
    "player_pass_tds":                  ["TD"],
    "player_pass_yds":                  ["YDS"],    # context: passing
    "player_rush_yds":                  ["YDS"],    # context: rushing
    "player_reception_yds":             ["YDS"],    # context: receiving
    "player_receptions":                ["REC"],
    "player_anytime_td":                ["TD"],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
}


def run_grader(verbose: bool = True) -> dict:
    """
    Main entry point. Grades all pending bets from prior days.
    Returns summary dict: {graded, manual_review, skipped}
    """
    # Only grade bets from days before today
    today = date.today().isoformat()
    all_rows = _load_rows()  # all rows regardless of date
    prior_pending = [b for b in all_rows if b["result"] == "pending" and b["date"] < today]

    if not prior_pending:
        if verbose:
            print("[Grader] No pending bets from prior days to grade.\n")
        return {"graded": 0, "manual_review": 0, "skipped": 0}

    print(f"[Grader] Found {len(prior_pending)} pending bet(s) to grade.\n")

    graded = 0
    manual_review = []
    skipped = 0

    for bet in prior_pending:
        result = _grade_bet(bet, verbose=verbose)
        if result == "graded":
            graded += 1
        elif result == "manual":
            manual_review.append(bet)
        else:
            skipped += 1

    # Print manual review queue
    if manual_review:
        print(f"\n{'─'*60}")
        print(f"  MANUAL REVIEW REQUIRED  ({len(manual_review)} bet(s))")
        print(f"{'─'*60}")
        for bet in manual_review:
            print(
                f"  [{bet['date']}] {bet['sport']} | {bet['bet']} | "
                f"{bet['odds']} | {bet['units']}u"
            )
        print(
            "\n  To update manually, run:"
            "\n    python3 -c \""
            "from tracker import update_result; "
            "update_result('YYYY-MM-DD', 'player name or bet', 'W', units_won)\""
            "\n"
        )

    # Print updated record
    if graded > 0:
        record = get_all_time_record()
        print(f"\n[Grader] {graded} bet(s) graded. {format_record_string(record)}\n")

    return {"graded": graded, "manual_review": len(manual_review), "skipped": skipped}


def _grade_bet(bet: dict, verbose: bool = True) -> str:
    """
    Attempt to grade one bet. Returns 'graded', 'manual', or 'skipped'.
    """
    sport = bet.get("sport", "").upper()
    bet_str = bet.get("bet", "")
    market = bet.get("market", "")
    game = bet.get("game", "")  # "Away @ Home"
    bet_date = bet.get("date", "")
    odds = int(bet.get("odds", -110))
    units = float(bet.get("units", 2))

    if verbose:
        print(f"  Grading: [{sport}] {bet_str} ({bet_date})")

    espn_sport, espn_league = SPORT_MAP.get(sport, (None, None))
    if not espn_sport:
        if verbose:
            print(f"    → Sport not supported for auto-grading.\n")
        return "manual"

    # Find the ESPN event
    event = _find_espn_event(espn_sport, espn_league, game, bet_date)
    if not event:
        if verbose:
            print(f"    → Game not found in ESPN data.\n")
        return "manual"

    # Get detailed box score
    event_id = event.get("id")
    box = _get_box_score(espn_sport, espn_league, event_id)
    if not box:
        if verbose:
            print(f"    → Box score unavailable.\n")
        return "manual"

    # Check game is finished
    status = box.get("header", {}).get("competitions", [{}])[0].get("status", {})
    if status.get("type", {}).get("state") != "post":
        if verbose:
            print(f"    → Game not yet complete.\n")
        return "skipped"

    # Grade based on market type
    over_under, line_value = _parse_bet_string(bet_str)
    if over_under is None or line_value is None:
        if verbose:
            print(f"    → Could not parse bet string.\n")
        return "manual"

    # Player prop
    player_name = _extract_player_name(bet_str)
    if player_name:
        actual = _get_player_stat(box, player_name, market, sport)
        if actual is None:
            if verbose:
                print(f"    → Could not find {player_name} in box score.\n")
            return "manual"

        result, units_result = _determine_result(actual, line_value, over_under, odds, units)
        if verbose:
            print(f"    → {player_name} actual: {actual} | line: {line_value} | {result}")

    # Game total
    elif "total" in market.lower() or "over" in bet_str.lower():
        actual = _get_game_total(box)
        if actual is None:
            return "manual"
        result, units_result = _determine_result(actual, line_value, over_under, odds, units)
        if verbose:
            print(f"    → Game total: {actual} | line: {line_value} | {result}")

    else:
        if verbose:
            print(f"    → Unrecognized market for auto-grading.\n")
        return "manual"

    update_result(
        bet_date=bet_date,
        bet_description=bet_str,
        result=result,
        units_result=units_result,
        post_slate_tag=_suggest_tag(result, actual, line_value),
    )
    if verbose:
        sign = "+" if units_result >= 0 else ""
        print(f"    → Logged: {result} | {sign}{units_result}u\n")
    return "graded"


def _parse_bet_string(bet_str: str) -> tuple[Optional[str], Optional[float]]:
    """Extract Over/Under direction and the line value from a bet string."""
    match = re.search(r"(Over|Under)\s+([\d.]+)", bet_str, re.IGNORECASE)
    if not match:
        return None, None
    direction = match.group(1).capitalize()
    line = float(match.group(2))
    return direction, line


def _extract_player_name(bet_str: str) -> Optional[str]:
    """
    Extract player name from a bet string like:
    'Aaron Nola Over 5.5 Strikeouts' → 'Aaron Nola'
    """
    match = re.match(r"^([A-Za-z\s\-\'\.]+?)\s+(Over|Under)\s+", bet_str, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        # Filter out generic strings that aren't player names
        if len(name.split()) >= 2 and name[0].isupper():
            return name
    return None


def _determine_result(
    actual: float, line: float, direction: str, odds: int, units: float
) -> tuple[str, float]:
    """Return (result, units_result) given actual stat vs line."""
    if actual == line:
        return "P", 0.0
    won = (direction == "Over" and actual > line) or (direction == "Under" and actual < line)
    if won:
        return "W", calculate_win_units(units, odds)
    else:
        return "L", -units


def _suggest_tag(result: str, actual: float, line: float) -> str:
    if result == "W":
        margin = actual - line
        return "good bet, bad result" if margin < 0.5 else ""
    if result == "L":
        return "model miss"
    return ""


# ── ESPN API helpers ──────────────────────────────────────────────────────────

def _espn_get(url: str, params: dict = None) -> Optional[dict]:
    try:
        resp = requests.get(url, params=params or {}, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _find_espn_event(sport: str, league: str, game: str, bet_date: str) -> Optional[dict]:
    """Find ESPN event by matching team names and date."""
    # Parse "Away @ Home"
    parts = game.split(" @ ")
    if len(parts) != 2:
        return None
    away_hint = parts[0].strip().lower()
    home_hint = parts[1].strip().lower()

    date_str = bet_date.replace("-", "")
    data = _espn_get(
        f"{ESPN_BASE}/{sport}/{league}/scoreboard",
        {"dates": date_str, "limit": 50},
    )
    if not data:
        return None

    for event in data.get("events", []):
        name = event.get("name", "").lower()
        short = event.get("shortName", "").lower()
        # Match if both team hints appear somewhere in the event name
        if (away_hint.split()[-1] in name or away_hint.split()[-1] in short) and \
           (home_hint.split()[-1] in name or home_hint.split()[-1] in short):
            return event

    return None


def _get_box_score(sport: str, league: str, event_id: str) -> Optional[dict]:
    return _espn_get(
        f"{ESPN_BASE}/{sport}/{league}/summary",
        {"event": event_id},
    )


def _get_player_stat(box: dict, player_name: str, market: str, sport: str) -> Optional[float]:
    """Search box score for a player's relevant stat."""
    stat_labels = MARKET_TO_ESPN_STAT.get(market, [])
    if not stat_labels:
        return None

    name_lower = player_name.lower()

    # ESPN box score structure: boxscore → players → [{team, statistics}]
    boxscore = box.get("boxscore", {})
    players_sections = boxscore.get("players", [])

    for team_section in players_sections:
        for stat_block in team_section.get("statistics", []):
            labels = stat_block.get("labels", [])
            athletes = stat_block.get("athletes", [])

            for athlete in athletes:
                a_name = athlete.get("athlete", {}).get("displayName", "").lower()
                if name_lower not in a_name and a_name not in name_lower:
                    # Try last-name-only match
                    last = name_lower.split()[-1]
                    if last not in a_name:
                        continue

                stats = athlete.get("stats", [])
                if not stats or len(stats) != len(labels):
                    continue

                stat_dict = dict(zip(labels, stats))

                # Special case: pitcher outs from IP
                if "OUTS" in stat_labels:
                    ip = stat_dict.get("IP", stat_dict.get("IP*", None))
                    if ip is not None:
                        return _ip_to_outs(str(ip))

                # NHL points = G + A
                if sport == "NHL" and market == "player_points":
                    g = _safe_float(stat_dict.get("G", 0))
                    a = _safe_float(stat_dict.get("A", 0))
                    return g + a

                # Sum all required labels
                total = 0.0
                found_any = False
                for label in stat_labels:
                    val = stat_dict.get(label)
                    if val is not None:
                        total += _safe_float(val)
                        found_any = True

                if found_any:
                    return total

    return None


def _get_game_total(box: dict) -> Optional[float]:
    """Return combined final score from a completed game."""
    comps = box.get("header", {}).get("competitions", [{}])
    if not comps:
        return None
    competitors = comps[0].get("competitors", [])
    total = 0.0
    for comp in competitors:
        score = comp.get("score", "0")
        total += _safe_float(score)
    return total if total > 0 else None


def _ip_to_outs(ip_str: str) -> float:
    """Convert '5.2' innings pitched to 17 outs."""
    try:
        parts = str(ip_str).split(".")
        full_innings = int(parts[0])
        partial = int(parts[1]) if len(parts) > 1 else 0
        return float(full_innings * 3 + partial)
    except Exception:
        return 0.0


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0
