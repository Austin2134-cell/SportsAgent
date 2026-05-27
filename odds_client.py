"""
Unified Odds Client.

Primary source  : The Odds API  (500 req/month free, resets monthly)
Fallback source : SportsGameOdds (2,500 objects/month free, player props incl.)

Flow:
  1. Attempt The Odds API with existing key.
  2. If quota is exhausted (401/422) or key is missing, switch to
     SportsGameOdds automatically.
  3. Both sources return the same snapshot dict consumed by esm_agent.py.

Sign up for a free SportsGameOdds key at https://sportsgameodds.com
Add SGO_API_KEY=<your_key> to your .env file.
"""

import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
from config import ODDS_API_KEY, SGO_API_KEY, ACTIVE_SPORTS, PROP_MARKETS, DEFAULT_BOOK

# ── The Odds API ───────────────────────────────────────────────────────────────
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── SportsGameOdds API ─────────────────────────────────────────────────────────
SGO_BASE = "https://api.sportsgameodds.com/v2"

# Map our internal sport key → SGO leagueID
SPORT_TO_SGO_LEAGUE = {
    "basketball_nba":       "NBA",
    "baseball_mlb":         "MLB",
    "icehockey_nhl":        "NHL",
    "americanfootball_nfl": "NFL",
    "basketball_ncaab":     "NCAAB",
}

# Map SGO statID → our market key, keyed by sport
SGO_STAT_MAP = {
    "basketball_nba": {
        "points":                   "player_points",
        "rebounds":                 "player_rebounds",
        "assists":                  "player_assists",
        "blocks":                   "player_blocks",
        "steals":                   "player_steals",
        "threePointersMade":        "player_threes",
        "points+rebounds+assists":  "player_points_rebounds_assists",
        "points+rebounds":          "player_points_rebounds",
        "points+assists":           "player_points_assists",
        "rebounds+assists":         "player_rebounds_assists",
    },
    "baseball_mlb": {
        "batting_hits":             "batter_hits",
        "batting_homeRuns":         "batter_home_runs",
        "batting_RBI":              "batter_rbis",
        "pitching_strikeouts":      "pitcher_strikeouts",
        "pitching_outs":            "pitcher_outs",       # SGO reports outs directly
        "batting_totalBases":       "batter_total_bases",
        "batting_stolenBases":      "batter_stolen_bases",
    },
    "icehockey_nhl": {
        "goals":                    "player_goals",
        "assists":                  "player_assists",
        "goals+assists":            "player_points",
        "shots":                    "player_shots_on_goal",
        "shotsOnGoal":              "player_shots_on_goal",
    },
    "americanfootball_nfl": {
        "passing_touchdowns":       "player_pass_tds",
        "passing_yards":            "player_pass_yds",
        "rushing_yards":            "player_rush_yds",
        "receiving_yards":          "player_reception_yds",
        "receptions":               "player_receptions",
    },
    "basketball_ncaab": {
        "points":                   "player_points",
        "rebounds":                 "player_rebounds",
        "assists":                  "player_assists",
    },
}

# Sport suffixes embedded in SGO entity IDs (to strip when parsing player names)
_SGO_SPORT_TOKENS = {"NBA", "MLB", "NHL", "NFL", "NCAAB", "NCAAF", "MLS"}

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


# ──────────────────────────────────────────────────────────────────────────────
# Public facade
# ──────────────────────────────────────────────────────────────────────────────

class OddsClient:
    """
    Auto-selects data source. Exposes the single method build_market_snapshot()
    which is the only surface used by esm_agent.py.
    """

    def __init__(self):
        self.requests_remaining = None
        self._source = None  # "theoddsapi" or "sgo"

    # ── main entry point ───────────────────────────────────────────────────────

    def build_market_snapshot(self, target_date: Optional[str] = None) -> dict:
        today = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Try The Odds API first
        if ODDS_API_KEY:
            snapshot = _toa_build_snapshot(today, self)
            if snapshot.get("sports"):
                self._source = "theoddsapi"
                return snapshot
            print("[OddsClient] The Odds API quota exhausted or returned no data.")

        # Fall back to SportsGameOdds
        if SGO_API_KEY:
            print("[OddsClient] Switching to SportsGameOdds (free fallback)...")
            snapshot = _sgo_build_snapshot(today)
            self._source = "sgo"
            snapshot["requests_remaining_after"] = "SGO (objects-based quota)"
            return snapshot

        print("[OddsClient] No odds API keys available. Running with ESPN context only.")
        return {"date": today, "sports": {}, "requests_remaining_after": "N/A"}


# ──────────────────────────────────────────────────────────────────────────────
# The Odds API implementation (unchanged logic from original odds_client.py)
# ──────────────────────────────────────────────────────────────────────────────

def _toa_get(endpoint: str, params: dict, client: OddsClient) -> Optional[dict | list]:
    params["apiKey"] = ODDS_API_KEY
    try:
        resp = requests.get(f"{ODDS_API_BASE}{endpoint}", params=params,
                            headers=HEADERS, timeout=15)
        client.requests_remaining = int(resp.headers.get("x-requests-remaining", 0))
        if resp.status_code in (401, 402, 422):
            return None   # quota exhausted signal
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[OddsClient/TOA] Request failed: {e}")
        return None


def _toa_build_snapshot(today: str, client: OddsClient) -> dict:
    snapshot = {"date": today, "sports": {}}

    # Get active sports
    active_keys_data = _toa_get("/sports", {"all": "false"}, client)
    if active_keys_data is None:
        return snapshot
    active_sport_keys = {s["key"] for s in active_keys_data}

    for sport in ACTIVE_SPORTS:
        if sport not in active_sport_keys:
            continue

        games = _toa_get(f"/sports/{sport}/odds", {
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
            "bookmakers": "draftkings,fanduel,betmgm",
        }, client)
        if not games:
            continue

        today_games = [g for g in games if g.get("commence_time", "").startswith(today)]
        if not today_games:
            continue

        sport_data = {"games": []}
        for game in today_games:
            game_entry = {
                "event_id": game["id"],
                "home_team":     game["home_team"],
                "away_team":     game["away_team"],
                "commence_time": game["commence_time"],
                "lines": _toa_extract_best_lines(game),
                "props": {},
            }

            # Fetch props if quota allows
            remaining = client.requests_remaining
            if remaining is None or remaining > 10:
                prop_markets = PROP_MARKETS.get(sport, [])
                batches = [prop_markets[i:i+4] for i in range(0, len(prop_markets), 4)]
                for batch in batches:
                    prop_data = _toa_get(
                        f"/sports/{sport}/events/{game['id']}/odds", {
                            "regions": "us",
                            "markets": ",".join(batch),
                            "oddsFormat": "american",
                            "dateFormat": "iso",
                            "bookmakers": "draftkings,fanduel,betmgm",
                        }, client)
                    if prop_data:
                        game_entry["props"].update(_toa_extract_props(prop_data, batch))

            sport_data["games"].append(game_entry)

        snapshot["sports"][sport] = sport_data

    snapshot["requests_remaining_after"] = client.requests_remaining
    return snapshot


def _toa_extract_best_lines(game: dict) -> dict:
    best = {
        "home_ml": None, "away_ml": None,
        "home_spread": None, "away_spread": None, "spread_line": None,
        "total": None, "over_odds": None, "under_odds": None,
        "books_checked": [],
    }
    priority = ["draftkings", "fanduel", "betmgm"]
    bookmakers = {b["key"]: b for b in game.get("bookmakers", [])}
    best["books_checked"] = list(bookmakers.keys())

    for book_key in priority:
        book = bookmakers.get(book_key)
        if not book:
            continue
        for market in book.get("markets", []):
            if market["key"] == "h2h" and best["home_ml"] is None:
                for outcome in market["outcomes"]:
                    if outcome["name"] == game["home_team"]:
                        best["home_ml"] = outcome["price"]
                    else:
                        best["away_ml"] = outcome["price"]
            elif market["key"] == "spreads" and best["spread_line"] is None:
                for outcome in market["outcomes"]:
                    if outcome["name"] == game["home_team"]:
                        best["home_spread"] = outcome["point"]
                    else:
                        best["away_spread"] = outcome["point"]
                best["spread_line"] = best["home_spread"]
            elif market["key"] == "totals" and best["total"] is None:
                for outcome in market["outcomes"]:
                    if outcome["name"] == "Over":
                        best["total"] = outcome["point"]
                        best["over_odds"] = outcome["price"]
                    else:
                        best["under_odds"] = outcome["price"]
    return best


def _toa_extract_props(prop_data: dict, markets: list[str]) -> dict:
    result = {}
    bookmakers = {b["key"]: b for b in prop_data.get("bookmakers", [])}
    for market_key in markets:
        market_result = {}
        for book_key in ["draftkings", "fanduel", "betmgm"]:
            book = bookmakers.get(book_key)
            if not book:
                continue
            for market in book.get("markets", []):
                if market["key"] != market_key:
                    continue
                for outcome in market["outcomes"]:
                    player    = outcome.get("description", outcome["name"])
                    direction = outcome["name"]
                    line      = outcome.get("point")
                    price     = outcome["price"]
                    if player not in market_result:
                        market_result[player] = {}
                    if direction not in market_result[player]:
                        market_result[player][direction] = {
                            "line": line, "best_odds": price, "best_book": book_key
                        }
                    elif _is_better_price(price, market_result[player][direction]["best_odds"]):
                        market_result[player][direction] = {
                            "line": line, "best_odds": price, "best_book": book_key
                        }
        if market_result:
            result[market_key] = market_result
    return result


# ──────────────────────────────────────────────────────────────────────────────
# SportsGameOdds implementation
# ──────────────────────────────────────────────────────────────────────────────

def _sgo_get(endpoint: str, params: dict) -> Optional[dict]:
    params["apiKey"] = SGO_API_KEY
    try:
        resp = requests.get(f"{SGO_BASE}{endpoint}", params=params,
                            headers=HEADERS, timeout=20)
        if resp.status_code == 401:
            print("[OddsClient/SGO] Invalid or missing SGO_API_KEY.")
            return None
        if resp.status_code == 429:
            print("[OddsClient/SGO] SGO rate limit hit.")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[OddsClient/SGO] Request failed: {e}")
        return None


def _sgo_build_snapshot(today: str) -> dict:
    snapshot = {"date": today, "sports": {}}

    # Build league filter from active sports
    sgo_leagues = [
        SPORT_TO_SGO_LEAGUE[s]
        for s in ACTIVE_SPORTS
        if s in SPORT_TO_SGO_LEAGUE
    ]
    if not sgo_leagues:
        return snapshot

    # Fetch today's events with odds
    today_start = f"{today}T00:00:00Z"
    tomorrow    = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    today_end   = f"{tomorrow}T00:00:00Z"

    data = _sgo_get("/events/", {
        "leagueID":    ",".join(sgo_leagues),
        "startsAfter": today_start,
        "startsBefore": today_end,
        "oddsAvailable": "true",
    })
    if not data:
        print("[OddsClient/SGO] No event data returned.")
        return snapshot

    events = data.get("data", data) if isinstance(data, dict) else data

    # Group events by sport key
    sport_events: dict[str, list] = {}
    for event in events:
        league_id = event.get("leagueID", "")
        # Reverse-map SGO league → our sport key
        sport_key = next(
            (k for k, v in SPORT_TO_SGO_LEAGUE.items() if v == league_id), None
        )
        if not sport_key:
            continue
        sport_events.setdefault(sport_key, []).append(event)

    for sport_key, evts in sport_events.items():
        stat_map = SGO_STAT_MAP.get(sport_key, {})
        sport_data = {"games": []}

        for event in evts:
            teams = event.get("teams", {})
            home = (teams.get("home", {}).get("names", {}).get("long")
                    or event.get("homeTeamName", "?"))
            away = (teams.get("away", {}).get("names", {}).get("long")
                    or event.get("awayTeamName", "?"))
            start = (event.get("status", {}).get("startsAt")
                     or event.get("startTime")
                     or event.get("commenceTime", ""))

            game_entry = {
                "event_id":     event.get("eventID", ""),
                "home_team":    home,
                "away_team":    away,
                "commence_time": start,
                "lines": _sgo_extract_lines(event, home, away),
                "props": _sgo_extract_props(event, stat_map),
            }
            sport_data["games"].append(game_entry)

        if sport_data["games"]:
            snapshot["sports"][sport_key] = sport_data

    return snapshot


def _sgo_extract_lines(event: dict, home_name: str, away_name: str) -> dict:
    """Extract H2H, spread, and total from SGO odds object."""
    best = {
        "home_ml": None, "away_ml": None,
        "home_spread": None, "away_spread": None, "spread_line": None,
        "total": None, "over_odds": None, "under_odds": None,
    }
    odds_obj = event.get("odds", {})
    if not odds_obj:
        return best

    for odd_id, odd in odds_obj.items():
        parts = odd_id.split("-")
        if len(parts) < 5:
            continue
        stat_id, entity, period, bet_type, side = parts[0], parts[1], parts[2], parts[3], parts[4]

        if period != "game":
            continue

        # Moneyline
        if bet_type == "ml":
            price = _sgo_best_book_price(odd)
            if price is None:
                continue
            if side == "home" and best["home_ml"] is None:
                best["home_ml"] = price
            elif side == "away" and best["away_ml"] is None:
                best["away_ml"] = price

        # Spread
        elif bet_type == "spread" and best["spread_line"] is None:
            spread_val = odd.get("bookSpread") or odd.get("fairSpread")
            price = _sgo_best_book_price(odd)
            if side == "home" and spread_val is not None:
                best["home_spread"] = float(spread_val)
                best["spread_line"] = float(spread_val)

        # Game total (over/under) — SGO uses entity "all" for full-game totals
        elif bet_type == "ou" and entity in ("all", "game", "total", "both"):
            total_val = odd.get("bookOverUnder") or odd.get("fairOverUnder")
            price = _sgo_best_book_price(odd)
            if total_val is not None and best["total"] is None:
                best["total"] = float(total_val)
            if side == "over" and price is not None and best["over_odds"] is None:
                best["over_odds"] = price
            elif side == "under" and price is not None and best["under_odds"] is None:
                best["under_odds"] = price

    return best


def _sgo_extract_props(event: dict, stat_map: dict) -> dict:
    """
    Parse SGO odds object for player props.
    Returns same structure as _toa_extract_props:
    {market_key: {player_name: {Over: {line, best_odds, best_book}, Under: {...}}}}
    """
    result: dict = {}
    odds_obj = event.get("odds", {})
    if not odds_obj:
        return result

    # Invert stat_map so we can look up by sgo stat id
    # stat_map: {sgo_stat_id: market_key}

    for odd_id, odd in odds_obj.items():
        # Format: {statID}-{entityID}-{periodID}-{betTypeID}-{sideID}
        # We only want full-game over/under player props
        parts = odd_id.split("-")
        if len(parts) != 5:
            continue
        stat_id, entity_id, period, bet_type, side = parts

        if period != "game" or bet_type != "ou":
            continue
        if side not in ("over", "under"):
            continue

        # Map stat to our market key
        market_key = stat_map.get(stat_id)
        if not market_key:
            continue

        # Parse player name from entity ID
        player_name = _sgo_entity_to_name(entity_id)
        if not player_name:
            continue  # team/game entity, skip

        # Extract line and best odds
        line_val  = odd.get("bookOverUnder") or odd.get("fairOverUnder")
        direction = side.capitalize()  # "Over" or "Under"

        if line_val is None:
            continue

        # Find best odds across our target bookmakers
        best_price, best_book = _sgo_best_book_price_with_name(odd)
        if best_price is None:
            best_price = odd.get("bookOdds") or odd.get("fairOdds")
            best_book  = "consensus"

        if best_price is None:
            continue

        # Write to result
        if market_key not in result:
            result[market_key] = {}
        if player_name not in result[market_key]:
            result[market_key][player_name] = {}
        result[market_key][player_name][direction] = {
            "line":       float(line_val),
            "best_odds":  int(best_price),
            "best_book":  best_book,
        }

    return result


def _sgo_best_book_price(odd: dict) -> Optional[int]:
    """Return best price from our target bookmakers, fallback to consensus."""
    price, _ = _sgo_best_book_price_with_name(odd)
    return price


def _sgo_best_book_price_with_name(odd: dict) -> tuple[Optional[int], str]:
    """Return (best_price, book_name) from our target bookmakers."""
    priority = ["draftkings", "fanduel", "betmgm"]
    by_book = odd.get("byBookmaker", {})
    for book in priority:
        entry = by_book.get(book)
        if entry:
            price = entry.get("odds")
            if price is not None:
                try:
                    return int(price), book
                except (TypeError, ValueError):
                    pass
    # Fallback to consensus
    price = odd.get("bookOdds") or odd.get("fairOdds")
    if price is not None:
        try:
            return int(price), "consensus"
        except (TypeError, ValueError):
            pass
    return None, ""


def _sgo_entity_to_name(entity_id: str) -> Optional[str]:
    """
    Convert SGO entity ID to readable player name.
    'CADE_CUNNINGHAM_1_NBA'  → 'Cade Cunningham'
    'JACOB_DEGROM_1_MLB'     → 'Jacob Degrom'
    Returns None for team/game entities like 'home', 'away', 'game', 'total'.
    """
    if entity_id.lower() in ("home", "away", "game", "total", "both", "draw"):
        return None

    parts = entity_id.split("_")

    # Strip trailing sport token
    if parts and parts[-1].upper() in _SGO_SPORT_TOKENS:
        parts = parts[:-1]

    # Strip trailing numeric token(s) (player number / ID)
    while parts and parts[-1].isdigit():
        parts = parts[:-1]

    if not parts or len(parts) < 2:
        return None  # Single-word → likely a team/game entity

    return " ".join(p.title() for p in parts)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_better_price(new_price: int, current_price: int) -> bool:
    """Return True if new_price is better for the bettor (higher payout)."""
    if new_price >= 0 and current_price >= 0:
        return new_price > current_price
    if new_price < 0 and current_price < 0:
        return new_price > current_price
    return new_price >= 0
