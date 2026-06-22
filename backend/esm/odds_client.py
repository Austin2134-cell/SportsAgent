"""
Unified Odds Client.

Primary source  : SportsGameOdds (2,500 objects/month free — 1 req = all markets per event)
Fallback source : The Odds API (500 credits/month free — expensive for props)

Strategy (see esm/api_budget.py):
  - SGO primary for continuous polling (cost-efficient)
  - TOA fallback for mainlines; props only when credit budget allows
  - Shared snapshot cache — never fetch per-user (see snapshot_cache.py)

Sign up for a free SportsGameOdds key at https://sportsgameodds.com
Add SGO_API_KEY=<your_key> to your .env file.
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from esm.config import ODDS_API_KEY, SGO_API_KEY, ACTIVE_SPORTS, PROP_MARKETS, DEFAULT_BOOK
from esm.api_budget import (
    ApiUsageState,
    ODDS_PRIMARY_SOURCE,
    TOA_MAX_CREDITS_PER_SNAPSHOT,
    TOA_MAINLINE_MARKETS,
    TOA_PROPS_PER_GAME_RESERVE,
    should_use_toa,
    should_fetch_toa_props,
    should_use_sgo,
)

# ── The Odds API ───────────────────────────────────────────────────────────────
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── SportsGameOdds API ─────────────────────────────────────────────────────────
SGO_BASE = "https://api.sportsgameodds.com/v2"

# Map our internal sport key → SGO leagueID.
# World Cup is NOT on SGO free tier (GET /leagues has no WC league) — use TOA_ONLY_SPORTS.
SPORT_TO_SGO_LEAGUE = {
    "basketball_nba":           "NBA",
    "baseball_mlb":             "MLB",
    "icehockey_nhl":            "NHL",
    "americanfootball_nfl":     "NFL",
    "basketball_ncaab":         "NCAAB",
}

# Sports that must be fetched from The Odds API (not available on our SGO plan).
TOA_ONLY_SPORTS = frozenset({"soccer_fifa_world_cup"})

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
    "soccer_fifa_world_cup": {
        "goals":                    "player_goal_scorer_anytime",
        "shotsOnTarget":            "player_shots_on_target",
        "shots_on_target":          "player_shots_on_target",
    },
}

# Sport suffixes embedded in SGO entity IDs (to strip when parsing player names)
_SGO_SPORT_TOKENS = {"NBA", "MLB", "NHL", "NFL", "NCAAB", "NCAAF", "MLS", "WC", "FIFAWC"}

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TIMEZONE = os.getenv("TIMEZONE", "America/Denver")


# ──────────────────────────────────────────────────────────────────────────────
# Public facade
# ──────────────────────────────────────────────────────────────────────────────

class OddsClient:
    """
    Auto-selects data source based on api_budget config.
    Exposes build_market_snapshot() and usage state for monitoring.
    """

    # Shared usage state across instances (last known quota from API headers)
    _usage = ApiUsageState()

    def __init__(self):
        self.requests_remaining = None
        self._source = None
        self._credits_spent = 0

    @classmethod
    def get_usage(cls) -> ApiUsageState:
        return cls._usage

    def build_market_snapshot(
        self,
        target_date: Optional[str] = None,
        sport_keys: Optional[list[str]] = None,
        force_source: Optional[str] = None,
    ) -> dict:
        today = target_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sports_filter = sport_keys or ACTIVE_SPORTS

        if force_source == "toa":
            snapshot = self._try_toa_only(today, sports_filter)
        elif force_source == "sgo":
            snapshot = self._try_sgo_only(today, sports_filter)
        elif ODDS_PRIMARY_SOURCE == "sgo":
            snapshot = self._try_sgo_then_toa(today, sports_filter)
        else:
            snapshot = self._try_toa_then_sgo(today, sports_filter)

        if not snapshot.get("sports"):
            print("[OddsClient] No odds data from either source.")
            return {"date": today, "sports": {}, "requests_remaining_after": "N/A", "source": None}

        return snapshot

    def _try_toa_only(self, today: str, sports_filter: list[str]) -> dict:
        if not ODDS_API_KEY:
            print("[OddsClient] TOA forced but no ODDS_API_KEY set.")
            return {"date": today, "sports": {}}
        if not should_use_toa(self._usage, TOA_MAINLINE_MARKETS):
            print("[OddsClient] TOA below reserve — skipping forced snapshot.")
            return {"date": today, "sports": {}}
        snapshot = _toa_build_snapshot(today, self, sports_filter)
        if snapshot.get("sports"):
            self._source = "theoddsapi"
            snapshot["source"] = "theoddsapi"
            snapshot["requests_remaining_after"] = self._usage.toa_remaining
        return snapshot

    def _try_sgo_only(self, today: str, sports_filter: list[str]) -> dict:
        if not SGO_API_KEY:
            return {"date": today, "sports": {}}
        if not should_use_sgo(self._usage):
            return {"date": today, "sports": {}}
        snapshot = _sgo_build_snapshot(today, sports_filter, self)
        if snapshot.get("sports"):
            self._source = "sgo"
            snapshot["source"] = "sgo"
            snapshot["requests_remaining_after"] = self._usage.sgo_objects_remaining
        return snapshot

    def _try_sgo_then_toa(self, today: str, sports_filter: list[str]) -> dict:
        sgo_sports = [s for s in sports_filter if s not in TOA_ONLY_SPORTS and s in SPORT_TO_SGO_LEAGUE]
        toa_only = [s for s in sports_filter if s in TOA_ONLY_SPORTS]
        snapshot = {"date": today, "sports": {}}

        if SGO_API_KEY and should_use_sgo(self._usage) and sgo_sports:
            sgo_snapshot = _sgo_build_snapshot(today, sgo_sports, self)
            snapshot = _merge_snapshots(snapshot, sgo_snapshot)
            if sgo_snapshot.get("sports"):
                self._source = "sgo"
                snapshot["source"] = "sgo"
                snapshot["requests_remaining_after"] = self._usage.sgo_objects_remaining
            elif sgo_sports:
                print("[OddsClient] SGO returned no data — trying The Odds API for remaining sports...")

        toa_sports = list(toa_only)
        if not snapshot.get("sports"):
            # SGO returned nothing — fall back to TOA for the full slate.
            toa_sports = list(dict.fromkeys(toa_sports + sports_filter))
        else:
            toa_sports.extend(
                s for s in sgo_sports if s not in snapshot.get("sports", {})
            )
            toa_sports = list(dict.fromkeys(toa_sports))

        if toa_sports and ODDS_API_KEY and should_use_toa(self._usage):
            toa_snapshot = _toa_build_snapshot(today, self, toa_sports)
            snapshot = _merge_snapshots(snapshot, toa_snapshot)
            if toa_snapshot.get("sports"):
                self._source = self._source or "theoddsapi"
                snapshot["source"] = snapshot.get("source") or "theoddsapi"
                if self._source == "theoddsapi":
                    snapshot["requests_remaining_after"] = self._usage.toa_remaining

        return snapshot

    def _try_toa_then_sgo(self, today: str, sports_filter: list[str]) -> dict:
        if ODDS_API_KEY and should_use_toa(self._usage):
            snapshot = _toa_build_snapshot(today, self, sports_filter)
            if snapshot.get("sports"):
                self._source = "theoddsapi"
                snapshot["source"] = "theoddsapi"
                snapshot["requests_remaining_after"] = self._usage.toa_remaining
                return snapshot
            print("[OddsClient] The Odds API quota exhausted or returned no data.")

        if SGO_API_KEY and should_use_sgo(self._usage):
            print("[OddsClient] Switching to SportsGameOdds...")
            snapshot = _sgo_build_snapshot(today, sports_filter, self)
            self._source = "sgo"
            snapshot["source"] = "sgo"
            snapshot["requests_remaining_after"] = self._usage.sgo_objects_remaining
            return snapshot

        return {"date": today, "sports": {}}


# ──────────────────────────────────────────────────────────────────────────────
# The Odds API implementation (unchanged logic from original odds_client.py)
# ──────────────────────────────────────────────────────────────────────────────

def _toa_day_window_utc(target_date: str) -> tuple[str, str]:
    """Convert a calendar date in TIMEZONE to UTC commenceTimeFrom/To for The Odds API."""
    tz = ZoneInfo(TIMEZONE)
    day = datetime.strptime(target_date, "%Y-%m-%d").date()
    start_local = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return (
        start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def _toa_get(endpoint: str, params: dict, client: OddsClient) -> Optional[dict | list]:
    params["apiKey"] = ODDS_API_KEY
    try:
        resp = requests.get(f"{ODDS_API_BASE}{endpoint}", params=params,
                            headers=HEADERS, timeout=15)
        remaining = resp.headers.get("x-requests-remaining")
        used = resp.headers.get("x-requests-used")
        last_cost = resp.headers.get("x-requests-last")
        if remaining is not None:
            client.requests_remaining = int(remaining)
            OddsClient._usage.toa_remaining = int(remaining)
        if used is not None:
            OddsClient._usage.toa_used = int(used)
        if last_cost is not None:
            cost = int(last_cost)
            OddsClient._usage.toa_last_cost = cost
            client._credits_spent += cost
        if resp.status_code in (401, 402, 422):
            OddsClient._usage.warnings.append(f"TOA quota exhausted (HTTP {resp.status_code})")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[OddsClient/TOA] Request failed: {e}")
        return None


def _toa_build_snapshot(today: str, client: OddsClient, sports_filter: list[str]) -> dict:
    snapshot = {"date": today, "sports": {}}
    client._credits_spent = 0

    active_keys_data = _toa_get("/sports", {"all": "false"}, client)
    if active_keys_data is None:
        return snapshot
    active_sport_keys = {s["key"] for s in active_keys_data}

    fetch_props = should_fetch_toa_props(OddsClient._usage)
    commence_from, commence_to = _toa_day_window_utc(today)

    for sport in sports_filter:
        if sport not in ACTIVE_SPORTS or sport not in active_sport_keys:
            continue
        if client._credits_spent + TOA_MAINLINE_MARKETS > TOA_MAX_CREDITS_PER_SNAPSHOT:
            OddsClient._usage.warnings.append(f"TOA snapshot cap reached — skipped {sport}")
            break
        if not should_use_toa(OddsClient._usage, TOA_MAINLINE_MARKETS):
            break

        games = _toa_get(f"/sports/{sport}/odds", {
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "dateFormat": "iso",
            "bookmakers": "draftkings,fanduel,betmgm",
            "commenceTimeFrom": commence_from,
            "commenceTimeTo": commence_to,
        }, client)
        if not games:
            continue

        sport_data = {"games": []}
        for game in games:
            game_entry = {
                "event_id": game["id"],
                "home_team":     game["home_team"],
                "away_team":     game["away_team"],
                "commence_time": game["commence_time"],
                "lines": _toa_extract_best_lines(game),
                "props": {},
            }

            if fetch_props and should_use_toa(OddsClient._usage, 1):
                remaining = client.requests_remaining
                if remaining is None or remaining > TOA_PROPS_PER_GAME_RESERVE:
                    prop_markets = PROP_MARKETS.get(sport, [])
                    batches = [prop_markets[i:i+4] for i in range(0, len(prop_markets), 4)]
                    for batch in batches:
                        if client._credits_spent + len(batch) > TOA_MAX_CREDITS_PER_SNAPSHOT:
                            break
                        if not should_use_toa(OddsClient._usage, len(batch)):
                            break
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

    OddsClient._usage.last_snapshot_credits = client._credits_spent
    OddsClient._usage.last_source = "theoddsapi"
    snapshot["credits_spent"] = client._credits_spent
    snapshot["requests_remaining_after"] = client.requests_remaining
    return snapshot


def _toa_extract_best_lines(game: dict) -> dict:
    best = {
        "home_ml": None, "away_ml": None, "draw_ml": None,
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
                    name = outcome["name"]
                    if name == game["home_team"]:
                        best["home_ml"] = outcome["price"]
                    elif name == game["away_team"]:
                        best["away_ml"] = outcome["price"]
                    elif name.lower() == "draw":
                        best["draw_ml"] = outcome["price"]
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

def _sgo_get(endpoint: str, params: dict, client: Optional[OddsClient] = None) -> Optional[dict]:
    params["apiKey"] = SGO_API_KEY
    try:
        resp = requests.get(f"{SGO_BASE}{endpoint}", params=params,
                            headers=HEADERS, timeout=20)
        if resp.status_code == 401:
            print("[OddsClient/SGO] Invalid or missing SGO_API_KEY.")
            OddsClient._usage.warnings.append("SGO auth failed (401)")
            return None
        if resp.status_code == 429:
            print("[OddsClient/SGO] SGO rate limit hit (429).")
            OddsClient._usage.warnings.append("SGO rate limit (429)")
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[OddsClient/SGO] Request failed: {e}")
        return None


def _sgo_fetch_usage() -> None:
    """Populate SGO quota from /account/usage endpoint."""
    data = _sgo_get("/account/usage", {})
    if not data:
        return
    # SGO returns nested usage — handle common shapes
    usage = data.get("data", data)
    if isinstance(usage, dict):
        objects = usage.get("objects") or usage.get("monthlyObjects") or {}
        if isinstance(objects, dict):
            OddsClient._usage.sgo_objects_remaining = objects.get("remaining")
            OddsClient._usage.sgo_objects_used = objects.get("used")
        requests_info = usage.get("requests") or usage.get("rateLimit") or {}
        if isinstance(requests_info, dict):
            OddsClient._usage.sgo_requests_remaining_min = requests_info.get("remaining")


def _merge_snapshots(base: dict, extra: dict) -> dict:
    """Merge sport entries from extra into base snapshot."""
    merged = {"date": base.get("date") or extra.get("date"), "sports": dict(base.get("sports", {}))}
    for sport_key, sport_data in extra.get("sports", {}).items():
        merged["sports"][sport_key] = sport_data
    for key in ("source", "credits_spent", "objects_consumed", "requests_remaining_after"):
        if extra.get(key) is not None:
            merged[key] = extra[key]
    return merged


def _sgo_build_snapshot(today: str, sports_filter: list[str], client: OddsClient) -> dict:
    snapshot = {"date": today, "sports": {}}
    _sgo_fetch_usage()

    sgo_sports = [
        s for s in sports_filter
        if s in SPORT_TO_SGO_LEAGUE and s not in TOA_ONLY_SPORTS
    ]
    if not sgo_sports:
        return snapshot

    today_start = f"{today}T00:00:00Z"
    tomorrow    = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    today_end   = f"{tomorrow}T00:00:00Z"

    all_events: list = []
    # One request per league — a bad/unsupported leagueID must not fail the whole batch.
    for sport_key in sgo_sports:
        league_id = SPORT_TO_SGO_LEAGUE[sport_key]
        data = _sgo_get("/events/", {
            "leagueID": league_id,
            "startsAfter": today_start,
            "startsBefore": today_end,
            "oddsAvailable": "true",
        }, client)
        if not data:
            print(f"[OddsClient/SGO] No event data for {league_id}.")
            continue
        events = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(events, list):
            all_events.extend(events)

    if not all_events:
        print("[OddsClient/SGO] No event data returned.")
        return snapshot

    OddsClient._usage.last_snapshot_credits = len(all_events)
    OddsClient._usage.last_source = "sgo"
    if OddsClient._usage.sgo_objects_remaining is not None:
        OddsClient._usage.sgo_objects_remaining = max(
            0, OddsClient._usage.sgo_objects_remaining - len(all_events)
        )

    sport_events: dict[str, list] = {}
    for event in all_events:
        league_id = event.get("leagueID", "")
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

    snapshot["objects_consumed"] = len(all_events)
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
