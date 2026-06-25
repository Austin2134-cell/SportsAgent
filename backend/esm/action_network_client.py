"""
Action Network public betting splits (no official API key required).

Fetches embedded Next.js data from:
  https://www.actionnetwork.com/{league}/public-betting

Returns ticket % (public bets) and money % (handle) per market side.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

BASE_URL = "https://www.actionnetwork.com"
DK_BOOK_ID = "15"
USER_AGENT = (
    "Mozilla/5.0 (compatible; AgentEdge/1.0; +https://edgebet.com)"
)

# Internal sport key → Action Network public-betting path segment
SPORT_TO_AN_PATH = {
    "baseball_mlb": "mlb",
    "basketball_nba": "nba",
    "icehockey_nhl": "nhl",
    "americanfootball_nfl": "nfl",
    "basketball_ncaab": "ncaab",
    "soccer_fifa_world_cup": "soccer",
}

# Fuzzy name aliases (AN display name → common variants in odds feeds)
TEAM_ALIASES = {
    "turkiye": "turkey",
    "usa": "united states",
}


def _normalize_team(name: str) -> str:
    n = (name or "").strip().lower()
    n = re.sub(r"\s+", " ", n)
    return TEAM_ALIASES.get(n, n)


def _fetch_next_data(league_path: str) -> dict:
    url = f"{BASE_URL}/{league_path}/public-betting"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        raise RuntimeError(f"No __NEXT_DATA__ on Action Network page: {url}")
    return json.loads(m.group(1))


def _classify_sharp(ticket_pct: float, money_pct: float) -> Optional[str]:
    """Derive sharp/public signal from ticket vs money divergence."""
    if ticket_pct is None or money_pct is None:
        return None
    diff = money_pct - ticket_pct
    if diff >= 15:
        return "sharp"
    if diff >= 10 and money_pct >= 55:
        return "big_money"
    if ticket_pct >= 70 and diff <= -10:
        return "public_heavy"
    return None


def _split_row(
    market_key: str,
    label: str,
    tickets: Optional[float],
    money: Optional[float],
    odds: Any = None,
    line: Any = None,
) -> dict:
    return {
        "market": market_key,
        "team": label,
        "public_bet_pct": tickets,
        "public_money_pct": money,
        "sharp_indicator": _classify_sharp(tickets, money),
        "odds": odds,
        "line": line,
    }


def _extract_dk_event_markets(game: dict) -> dict:
    """Pull moneyline, spread, and total splits from DraftKings (book 15) event markets."""
    markets = (game.get("markets") or {}).get(DK_BOOK_ID, {})
    event = markets.get("event") or {}
    teams = {t["id"]: t["full_name"] for t in game.get("teams", [])}
    home_id = game.get("home_team_id")
    away_id = game.get("away_team_id")
    home_name = teams.get(home_id, "")
    away_name = teams.get(away_id, "")

    out: dict[str, dict] = {}

    for row in event.get("moneyline") or []:
        side = row.get("side")
        team_id = row.get("team_id")
        tickets = (row.get("bet_info") or {}).get("tickets", {}).get("percent")
        money = (row.get("bet_info") or {}).get("money", {}).get("percent")
        if tickets is None and money is None:
            continue
        if side == "draw" or team_id is None:
            market_key = "h2h_draw"
            label = "Draw"
        elif team_id == home_id:
            market_key = "h2h_home"
            label = home_name
        elif team_id == away_id:
            market_key = "h2h_away"
            label = away_name
        else:
            continue
        out[market_key] = {
            "market": market_key,
            "team": label,
            "public_bet_pct": tickets,
            "public_money_pct": money,
            "sharp_indicator": _classify_sharp(tickets, money),
            "odds": row.get("odds"),
        }

    for row in event.get("spread") or []:
        team_id = row.get("team_id")
        tickets = (row.get("bet_info") or {}).get("tickets", {}).get("percent")
        money = (row.get("bet_info") or {}).get("money", {}).get("percent")
        if tickets is None and money is None:
            continue
        if team_id == home_id:
            market_key = "spread_home"
            label = home_name
        elif team_id == away_id:
            market_key = "spread_away"
            label = away_name
        else:
            continue
        out[market_key] = _split_row(
            market_key,
            label,
            tickets,
            money,
            odds=row.get("odds"),
            line=row.get("value"),
        )

    for row in event.get("total") or []:
        side = row.get("side")
        tickets = (row.get("bet_info") or {}).get("tickets", {}).get("percent")
        money = (row.get("bet_info") or {}).get("money", {}).get("percent")
        if tickets is None and money is None:
            continue
        market_key = f"total_{side}"
        out[market_key] = _split_row(
            market_key,
            side,
            tickets,
            money,
            odds=row.get("odds"),
            line=row.get("value"),
        )

    return {
        "event_id": str(game.get("id")),
        "core_id": game.get("core_id"),
        "home_team": home_name,
        "away_team": away_name,
        "start_time": game.get("start_time"),
        "league_name": game.get("league_name"),
        "num_bets": game.get("num_bets"),
        "splits": out,
    }


def fetch_public_splits(sport_key: str) -> list[dict]:
    """Return parsed public/money % for all games on the AN public-betting page."""
    path = SPORT_TO_AN_PATH.get(sport_key)
    if not path:
        return []

    data = _fetch_next_data(path)
    sb = data.get("props", {}).get("pageProps", {}).get("scoreboardResponse", {})
    games = sb.get("games") or []

    # World Cup games are league_name == worldcup inside soccer page
    if sport_key == "soccer_fifa_world_cup":
        games = [g for g in games if g.get("league_name") == "worldcup"]

    results = []
    for game in games:
        parsed = _extract_dk_event_markets(game)
        if parsed.get("splits"):
            results.append(parsed)
    return results


def all_mapped_sport_keys() -> list[str]:
    """All internal sport keys with Action Network public-betting pages."""
    return list(SPORT_TO_AN_PATH.keys())


def match_event_to_game(
    an_event: dict,
    away_team: str,
    home_team: str,
) -> bool:
    """Fuzzy match Action Network event to an odds snapshot game."""
    an_away = _normalize_team(an_event.get("away_team", ""))
    an_home = _normalize_team(an_event.get("home_team", ""))
    o_away = _normalize_team(away_team)
    o_home = _normalize_team(home_team)
    if an_away == o_away and an_home == o_home:
        return True
    # Allow swapped home/away labels between feeds
    if an_away == o_home and an_home == o_away:
        return True
    # Substring match for minor naming differences
    return (
        (an_away in o_away or o_away in an_away)
        and (an_home in o_home or o_home in an_home)
    )
