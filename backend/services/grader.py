"""
grader.py — auto-grades pending bets against ESPN box scores and refreshes
agent performance memory for any users with newly graded bets.

Supports US player props (NBA/MLB/NHL/NFL) and soccer markets (DNB, ML, totals, BTTS).
"""

import re
import os
import requests
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")


def _today_mt() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SPORT_MAP = {
    "NBA": ("basketball", "nba"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
    "NFL": ("football", "nfl"),
    "SOCCER": ("soccer", "fifa.world"),
    "WC": ("soccer", "fifa.world"),
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
    "batter_total_bases": ["TB"],
    "pitcher_strikeouts": ["K"],
    "pitcher_outs": ["OUTS"],
    "player_goals": ["G"],
    "player_assists": ["A"],
    "player_shots_on_goal": ["SOG"],
}

SOCCER_MARKETS = frozenset({
    "draw_no_bet", "dnb", "h2h", "moneyline", "match_result",
    "totals", "total_goals", "over_under", "btts", "both_teams_to_score",
})


def grade_all_pending(db, *, as_of_date: str | None = None):
    """Grade all pending bets with game date strictly before as_of_date (default: today MT)."""
    today = as_of_date or _today_mt()
    result = db.table("bets").select("*").eq("result", "pending").lt("date", today).execute()
    bets = result.data or []
    if not bets:
        return {"graded": 0, "manual": 0, "as_of": today}
    graded = 0
    manual = 0
    affected_users: set = set()
    for bet in bets:
        outcome = _grade_bet(bet)
        if outcome:
            update = {
                "result": outcome["result"],
                "units_result": outcome["units_result"],
            }
            grade_tag = outcome.get("tag", "")
            source_tag = (bet.get("post_slate_tag") or "").strip().lower()
            if grade_tag:
                if source_tag in {"world_cup", "esm", "agent"}:
                    note = (bet.get("notes") or "").strip()
                    tag_note = f"[grade:{grade_tag}]"
                    if tag_note not in note:
                        update["notes"] = f"{note} {tag_note}".strip()
                else:
                    update["post_slate_tag"] = grade_tag
            db.table("bets").update(update).eq("id", bet["id"]).execute()
            graded += 1
            affected_users.add(bet["user_id"])
        else:
            manual += 1
    if affected_users:
        from learning.memory import refresh_memory
        for uid in affected_users:
            refresh_memory(db, uid)
    if graded:
        from services.sheets_sync import maybe_sync_sheets
        from agent.unit_tracker import sync_units_at_risk
        maybe_sync_sheets(db, reason="post-grade")
        for uid in affected_users:
            sync_units_at_risk(db, uid)
    return {"graded": graded, "manual": manual, "as_of": today}


def _grade_bet(bet: dict) -> Optional[dict]:
    sport = bet.get("sport", "").upper()
    bet_str = bet.get("bet", "")
    market = (bet.get("market") or "").lower()
    game = bet.get("game", "")
    bet_date = bet.get("date", "")
    odds = int(bet.get("odds", -110))
    units = float(bet.get("units", 2))
    espn_info = SPORT_MAP.get(sport)
    if not espn_info:
        return None
    espn_sport, espn_league = espn_info

    if sport in ("SOCCER", "WC") or market in SOCCER_MARKETS or _looks_like_soccer_bet(bet_str):
        return _grade_soccer_bet(bet_str, market, game, bet_date, odds, units, espn_sport, espn_league)

    if market in ("game_total", "totals", "total") or bet_str.lower().startswith("total "):
        return _grade_game_total_bet(bet_str, game, bet_date, odds, units, espn_sport, espn_league)

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


def _looks_like_soccer_bet(bet_str: str) -> bool:
    lower = bet_str.lower()
    soccer_signals = (
        "draw no bet", "dnb", "total goals", "both teams to score", "btts",
        "match result", " ml", "moneyline", "asian handicap 0",
    )
    return any(sig in lower for sig in soccer_signals)


def _grade_soccer_bet(
    bet_str: str,
    market: str,
    game: str,
    bet_date: str,
    odds: int,
    units: float,
    espn_sport: str,
    espn_league: str,
) -> Optional[dict]:
    event = _find_event(espn_sport, espn_league, game, bet_date)
    if not event:
        return None
    box = _get_box(espn_sport, espn_league, event["id"])
    if not box:
        return None
    comp = box.get("header", {}).get("competitions", [{}])[0]
    status = comp.get("status", {})
    if status.get("type", {}).get("state") != "post":
        return None

    scores = _get_match_scores(comp)
    if scores is None:
        return None
    home_team, away_team, home_score, away_score = scores

    outcome = _resolve_soccer_outcome(bet_str, market, home_team, away_team, home_score, away_score)
    if outcome is None:
        return None

    result, tag_extra = outcome
    if result == "P":
        return {"result": "P", "units_result": 0.0, "tag": tag_extra or ""}
    if result == "W":
        return {
            "result": "W",
            "units_result": calculate_win_units(units, odds),
            "tag": tag_extra or "",
        }
    return {"result": "L", "units_result": -units, "tag": tag_extra or "model miss"}


def _grade_game_total_bet(
    bet_str: str,
    game: str,
    bet_date: str,
    odds: int,
    units: float,
    espn_sport: str,
    espn_league: str,
) -> Optional[dict]:
    """Grade full-game Over/Under (MLB/NBA/NHL/NFL)."""
    direction, line = _parse_total(bet_str, "totals")
    if direction is None or line is None:
        direction, line = _parse_bet(bet_str)
    if direction is None or line is None:
        return None

    event = _find_event(espn_sport, espn_league, game, bet_date)
    if not event:
        return None
    box = _get_box(espn_sport, espn_league, event["id"])
    if not box:
        return None
    comp = box.get("header", {}).get("competitions", [{}])[0]
    if comp.get("status", {}).get("type", {}).get("state") != "post":
        return None

    scores = _get_match_scores(comp)
    if scores is None:
        return None
    _, _, home_score, away_score = scores
    total = home_score + away_score

    if total == line:
        return {"result": "P", "units_result": 0.0, "tag": "exact total"}
    if direction == "Over":
        won = total > line
    else:
        won = total < line
    if won:
        return {"result": "W", "units_result": calculate_win_units(units, odds), "tag": ""}
    return {"result": "L", "units_result": -units, "tag": "model miss"}


def _resolve_soccer_outcome(
    bet_str: str,
    market: str,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> Optional[tuple[str, str]]:
    """Return (W/L/P, optional tag) or None if bet type unrecognized."""
    total = home_score + away_score
    both_scored = home_score >= 1 and away_score >= 1
    home_win = home_score > away_score
    away_win = away_score > home_score
    is_draw = home_score == away_score

    # Draw No Bet / Asian Handicap 0.0
    dnb_team = _parse_dnb_team(bet_str, market)
    if dnb_team:
        picked_home = _team_matches(dnb_team, home_team)
        picked_away = _team_matches(dnb_team, away_team)
        if not picked_home and not picked_away:
            return None
        if is_draw:
            return ("P", "draw push")
        if picked_home:
            return ("W" if home_win else "L", "")
        return ("W" if away_win else "L", "")

    # Match Result / Moneyline (3-way — draw loses)
    ml_team = _parse_ml_team(bet_str, market)
    if ml_team:
        picked_home = _team_matches(ml_team, home_team)
        picked_away = _team_matches(ml_team, away_team)
        if not picked_home and not picked_away:
            return None
        if picked_home and home_win:
            return ("W", "")
        if picked_away and away_win:
            return ("W", "")
        return ("L", "")

    # Totals
    direction, line = _parse_total(bet_str, market)
    if direction and line is not None:
        if total == line:
            return ("P", "exact total")
        if direction == "Over":
            return ("W" if total > line else "L", "")
        return ("W" if total < line else "L", "")

    # Both Teams to Score
    btts = _parse_btts(bet_str, market)
    if btts:
        if btts == "Yes":
            return ("W" if both_scored else "L", "")
        return ("W" if not both_scored else "L", "")

    return None


def _parse_game_teams(game: str) -> tuple[Optional[str], Optional[str]]:
    game_clean = re.sub(r"\s*\([^)]+\)\s*$", "", (game or "").strip())
    for sep in (" @ ", " vs ", " v ", " at "):
        if sep in game_clean:
            parts = game_clean.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return None, None


def _parse_dnb_team(bet_str: str, market: str) -> Optional[str]:
    if market in ("draw_no_bet", "dnb"):
        m = re.search(r"(?:draw no bet|dnb)\s*[—\-–:]?\s*(.+)$", bet_str, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(
        r"(?:draw no bet|dnb|asian handicap 0\.?0?)\s*[—\-–:]?\s*(.+)$",
        bet_str,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    m = re.match(r"^(.+?)\s+(?:draw no bet|dnb)\b", bet_str, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _parse_ml_team(bet_str: str, market: str) -> Optional[str]:
    if market in ("h2h", "moneyline", "match_result"):
        m = re.search(r"(?:match result\s*[—\-–:]?\s*)?(.+?)\s*ml\b", bet_str, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"moneyline\s*[—\-–:]?\s*(.+)$", bet_str, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r"(?:match result\s*[—\-–:]?\s*)?(.+?)\s*ml\b", bet_str, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"moneyline\s*[—\-–:]?\s*(.+)$", bet_str, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _parse_total(bet_str: str, market: str) -> tuple[Optional[str], Optional[float]]:
    if market in ("totals", "total_goals", "over_under"):
        m = re.search(r"(over|under)\s+([\d.]+)", bet_str, re.IGNORECASE)
        if m:
            return m.group(1).capitalize(), float(m.group(2))
    m = re.search(
        r"(?:total goals?\s+)?(over|under)\s+([\d.]+)",
        bet_str,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).capitalize(), float(m.group(2))
    return None, None


def _parse_btts(bet_str: str, market: str) -> Optional[str]:
    if market in ("btts", "both_teams_to_score"):
        m = re.search(r"(yes|no)\b", bet_str, re.IGNORECASE)
        if m:
            return m.group(1).capitalize()
    m = re.search(
        r"(?:both teams to score|btts)\s*(yes|no)\b",
        bet_str,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).capitalize()
    return None


def _team_matches(picked: str, team_name: str) -> bool:
    p = picked.lower().strip()
    t = team_name.lower().strip()
    if not p or not t:
        return False
    if p == t or p in t or t in p:
        return True
    p_last = p.split()[-1]
    t_last = t.split()[-1]
    return p_last == t_last or p_last in t or t_last in p


def _get_match_scores(comp: dict) -> Optional[tuple[str, str, int, int]]:
    home_team = away_team = None
    home_score = away_score = None
    for c in comp.get("competitors", []):
        team = c.get("team", {}).get("displayName", "")
        score_raw = c.get("score")
        try:
            score = int(score_raw) if score_raw is not None else None
        except (TypeError, ValueError):
            score = None
        if c.get("homeAway") == "home":
            home_team, home_score = team, score
        elif c.get("homeAway") == "away":
            away_team, away_score = team, score
    if None in (home_team, away_team, home_score, away_score):
        return None
    return home_team, away_team, home_score, away_score


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
    away_hint, home_hint = _parse_game_teams(game)
    if not away_hint or not home_hint:
        return None
    away_key = away_hint.split()[-1].lower()
    home_key = home_hint.split()[-1].lower()
    date_str = bet_date.replace("-", "")
    data = _espn_get(f"{ESPN_BASE}/{sport}/{league}/scoreboard", {"dates": date_str, "limit": 50})
    if not data:
        return None
    for event in data.get("events", []):
        name = event.get("name", "").lower()
        short = event.get("shortName", "").lower()
        if (away_key in name or away_key in short) and (home_key in name or home_key in short):
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
                if market == "batter_total_bases" or "TB" in stat_labels:
                    tb = _batter_total_bases(stat_dict)
                    if tb is not None:
                        return tb
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


def _batter_total_bases(stat_dict: dict) -> Optional[float]:
    """Compute total bases from ESPN batting line (H + 3*HR when TB column absent)."""
    if stat_dict.get("TB") is not None:
        try:
            return float(stat_dict["TB"])
        except (TypeError, ValueError):
            pass
    try:
        hits = float(stat_dict.get("H", 0))
        hrs = float(stat_dict.get("HR", 0))
        doubles = float(stat_dict.get("2B", 0))
        triples = float(stat_dict.get("3B", 0))
        if doubles or triples:
            singles = hits - doubles - triples - hrs
            return singles + 2 * doubles + 3 * triples + 4 * hrs
        return hits + 3 * hrs
    except (TypeError, ValueError):
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
