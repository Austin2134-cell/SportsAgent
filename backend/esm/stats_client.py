"""
Stats enrichment using ESPN's unofficial API (no key required).
Provides recent player performance data to ground the agent's analysis.

Endpoints discovered via public research — ESPN does not officially document these.
"""

import requests
from typing import Optional

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
CDN_BASE = "https://cdn.espn.com/core"

SPORT_MAP = {
    "basketball_nba": ("basketball", "nba"),
    "baseball_mlb": ("baseball", "mlb"),
    "icehockey_nhl": ("hockey", "nhl"),
    "americanfootball_nfl": ("football", "nfl"),
    "basketball_ncaab": ("basketball", "mens-college-basketball"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


class StatsClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, url: str, params: dict = None) -> Optional[dict]:
        try:
            resp = self.session.get(url, params=params or {}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[StatsClient] {url} failed: {e}")
            return None

    def get_scoreboard(self, odds_sport_key: str, date_str: str = None) -> list[dict]:
        sport, league = SPORT_MAP.get(odds_sport_key, (None, None))
        if not sport:
            return []

        params = {}
        if date_str:
            params["dates"] = date_str.replace("-", "")

        data = self._get(f"{ESPN_BASE}/{sport}/{league}/scoreboard", params)
        if not data:
            return []

        games = []
        for event in data.get("events", []):
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            if len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})

            games.append({
                "event_id_espn": event.get("id"),
                "name": event.get("name"),
                "date": event.get("date"),
                "status": event.get("status", {}).get("type", {}).get("description"),
                "home_team": home.get("team", {}).get("displayName"),
                "away_team": away.get("team", {}).get("displayName"),
                "home_record": home.get("records", [{}])[0].get("summary") if home.get("records") else None,
                "away_record": away.get("records", [{}])[0].get("summary") if away.get("records") else None,
                "odds_summary": competition.get("odds", [{}])[0] if competition.get("odds") else {},
            })

        return games

    def get_player_recent_stats(
        self, odds_sport_key: str, player_name: str, num_games: int = 10
    ) -> Optional[dict]:
        sport, league = SPORT_MAP.get(odds_sport_key, (None, None))
        if not sport:
            return None

        athlete_id = self._find_athlete_id(sport, league, player_name)
        if not athlete_id:
            return None

        return self._get_game_log(sport, league, athlete_id, num_games)

    def _find_athlete_id(self, sport: str, league: str, name: str) -> Optional[str]:
        data = self._get(
            f"{ESPN_BASE}/{sport}/{league}/athletes",
            {"limit": 1000, "active": "true"},
        )
        if not data:
            return None

        name_lower = name.lower()
        for item in data.get("items", []):
            full_name = item.get("fullName", "").lower()
            if name_lower in full_name or full_name in name_lower:
                return item.get("id")

        return None

    def _get_game_log(
        self, sport: str, league: str, athlete_id: str, num_games: int
    ) -> Optional[dict]:
        data = self._get(
            f"{ESPN_BASE}/{sport}/{league}/athletes/{athlete_id}/gamelog"
        )
        if not data:
            return None

        categories = data.get("categories", [])
        events = data.get("events", {})
        labels = []
        for cat in categories:
            labels.extend(cat.get("labels", []))

        game_logs = []
        for event_id, event_data in list(events.items())[-num_games:]:
            stats = event_data.get("stats", [])
            opponent = event_data.get("opponent", {}).get("displayName", "Unknown")
            result = event_data.get("gameResult", "")
            game_date = event_data.get("gameDate", "")

            stat_dict = dict(zip(labels, stats)) if len(labels) == len(stats) else {}
            game_logs.append({
                "date": game_date,
                "opponent": opponent,
                "result": result,
                "stats": stat_dict,
            })

        return {
            "athlete_id": athlete_id,
            "last_n_games": game_logs,
            "games_returned": len(game_logs),
        }

    def get_injuries(self, odds_sport_key: str) -> list[dict]:
        sport, league = SPORT_MAP.get(odds_sport_key, (None, None))
        if not sport:
            return []

        data = self._get(f"{ESPN_BASE}/{sport}/{league}/injuries")
        if not data:
            return []

        injuries = []
        for team_entry in data.get("injuries", []):
            team_name = team_entry.get("team", {}).get("displayName", "")
            for player in team_entry.get("injuries", []):
                injuries.append({
                    "team": team_name,
                    "player": player.get("athlete", {}).get("fullName", ""),
                    "status": player.get("status", ""),
                    "detail": player.get("details", {}).get("detail", ""),
                    "return_date": player.get("details", {}).get("returnDate", ""),
                })

        return injuries

    def build_context_package(
        self, odds_sport_key: str, date_str: str = None
    ) -> dict:
        return {
            "sport": odds_sport_key,
            "scoreboard": self.get_scoreboard(odds_sport_key, date_str),
            "injuries": self.get_injuries(odds_sport_key),
        }
