import re
import requests
from datetime import date
from typing import Optional

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SPORT_MAP = {
    "NBA": ("basketball", "nba"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
    "NFL": ("football", "nfl"),
}

MARKET_TO_ESPN_STAT = {
    "player_points": ["PTS"],
    "player_rebounds": ["REB"],
    "player_assists": ["AST"],
    "player_threes": ["3PM"],
    "player_blocks": ["BLK"],
    "player_steals": ["STL"],
    "player_points_rebounds_assists": ["PTS", "REB", "AST"],
    "player_points_rebounds": ["PTS", "REB"],
    "player_points_assists": ["PTS", "AST"],
    "player_rebounds_assists": ["REB", "AST"],
    "batter_hits": ["H"],
    "batter_home_runs": ["HR"],
    "batter_rbis": ["RBI"],
    "pitcher_strikeouts": ["K"],
    "pitcher_outs": ["OUTS"],
    "player_goals": ["G"],
    "player_assists": ["A"],
    "player_shots_on_goal": ["SOG"],
}


def grade_all_pending(db):
    today = date.today().isoformat()
    result = db.table("bets").select("*").eq("result", "pending").lt("date", today).execute()
    bets = result.data or []
    if not bets:
        return {"graded": 0, "manual": 0}
    graded = 0
    manual = 0
    for bet in bets:
        outcome = _grade_bet(bet)
        if outcome:
            db.table("bets").update({
                "result": outcome["result"],
                "units_result": outcome["units_result"],
                "post_slate_tag": outcome.get("tag", ""),
            }).eq("id", bet["id"]).execute()
            graded += 1
        else:
            manual += 1
    return {"graded": graded, "manual": manual}


def _grade_bet(bet: dict) -> Optional[dict]:
    sport = bet.get("sport", "").upper()
    bet_str = bet.get("bet", "")
    market = bet.get("market", "")
    game = bet.get("game", "")
    bet_date = bet.get("date", "")
    odds = int(bet.get("odds", -110))
    units = float(bet.get("units", 2))
    espn_info = SPORT_MAP.get(sport)
    if not espn_info:
        return None
    espn_sport, espn_league = espn_info
    event = _find_event(espn_sport, espn_league, game, bet_date)
    if not event:
        return None
    box = _get_box(espn_sport, espn_league, event["id"])
    if not box:
        return None
    status = box.get("header", {}).get("competitions", [{}])[0].get("status", {})
    if status.get("type", {}).get("state") != "post":
        return None
    direction, line = _parse_bet(bet_str)
    if direction is None:
        return None
    player_name = _extract_player(bet_str)
    if not player_name:
        return None
    actual = _get_player_stat(box, player_name, market, sport)
    if actual is None:
        return None
    if actual == line:
        result, units_result = "P", 0.0
    elif (direction == "Over" and actual > line) or (direction == "Under" and actual < line):
        result = "W"
        units_result = calculate_win_units(units, odds)
    else:
        result = "L"
        units_result = -units
    tag = "model miss" if result == "L" else ("close win" if result == "W" and abs(actual - line) < 0.5 else "")
    return {"result": result, "units_result": round(units_result, 2), "tag": tag}


def _parse_bet(bet_str):
    match = re.search(r"(Over|Under)\s+([\d.]+)", bet_str, re.IGNORECASE)
    if not match:
        return None, None
    return match.group(1).capitalize(), float(match.group(2))


def _extract_player(bet_str):
    match = re.match(r"^([A-Za-z\s\-\'\.]+?)\s+(Over|Under)\s+", bet_str, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        if len(name.split()) >= 2 and name[0].isupper():
            return name
    return None


def _find_event(sport, league, game, bet_date):
    parts = game.split(" @ ")
    if len(parts) != 2:
        return None
    away_hint = parts[0].strip().lower()
    home_hint = parts[1].strip().lower()
    date_str = bet_date.replace("-", "")
    data = _espn_get(f"{ESPN_BASE}/{sport}/{league}/scoreboard", {"dates": date_str, "limit": 50})
    if not data:
        return None
    for event in data.get("events", []):
        name = event.get("name", "").lower()
        short = event.get("shortName", "").lower()
        if (away_hint.split()[-1] in name or away_hint.split()[-1] in short) and \
           (home_hint.split()[-1] in name or home_hint.split()[-1] in short):
            return event
    return None


def _get_box(sport, league, event_id):
    return _espn_get(f"{ESPN_BASE}/{sport}/{league}/summary", {"event": event_id})


def _get_player_stat(box, player_name, market, sport):
    stat_labels = MARKET_TO_ESPN_STAT.get(market, [])
    if not stat_labels:
        return None
    name_lower = player_name.lower()
    for team_section in box.get("boxscore", {}).get("players", []):
        for stat_block in team_section.get("statistics", []):
            labels = stat_block.get("labels", [])
            for athlete in stat_block.get("athletes", []):
                a_name = athlete.get("athlete", {}).get("displayName", "").lower()
                if name_lower not in a_name and a_name not in name_lower:
                    if name_lower.split()[-1] not in a_name:
                        continue
                stats = athlete.get("stats", [])
                if not stats or len(stats) != len(labels):
                    continue
                stat_dict = dict(zip(labels, stats))
                if "OUTS" in stat_labels:
                    ip = stat_dict.get("IP") or stat_dict.get("IP*")
                    if ip is not None:
                        try:
                            parts = str(ip).split(".")
                            return float(int(parts[0]) * 3 + (int(parts[1]) if len(parts) > 1 else 0))
                        except Exception:
                            return 0.0
                total = 0.0
                found = False
                for label in stat_labels:
                    val = stat_dict.get(label)
                    if val is not None:
                        try:
                            total += float(val)
                            found = True
                        except Exception:
                            pass
                if found:
                    return total
    return None


def _espn_get(url, params=None):
    try:
        resp = requests.get(url, params=params or {}, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def calculate_win_units(units: float, odds: int) -> float:
    if odds >= 0:
        return round(units * (odds / 100), 2)
    return round(units * (100 / abs(odds)), 2)
