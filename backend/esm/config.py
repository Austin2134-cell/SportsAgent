import os

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
SGO_API_KEY = os.getenv("SGO_API_KEY", "")

ACTIVE_SPORTS = [
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "americanfootball_nfl",
    "basketball_ncaab",
    "soccer_fifa_world_cup",
]

PROP_MARKETS = {
    "basketball_nba": [
        "player_points",
        "player_rebounds",
        "player_assists",
        "player_threes",
        "player_blocks",
        "player_steals",
        "player_points_rebounds_assists",
    ],
    "baseball_mlb": [
        "batter_hits",
        "batter_home_runs",
        "batter_rbis",
        "pitcher_strikeouts",
        "pitcher_outs",
    ],
    "icehockey_nhl": [
        "player_points",
        "player_goals",
        "player_shots_on_goal",
        "player_assists",
    ],
    "americanfootball_nfl": [
        "player_pass_tds",
        "player_pass_yds",
        "player_rush_yds",
        "player_reception_yds",
        "player_receptions",
        "player_anytime_td",
    ],
    "basketball_ncaab": [
        "player_points",
        "player_rebounds",
        "player_assists",
    ],
    "soccer_fifa_world_cup": [
        "player_goal_scorer_anytime",
        "player_shots_on_target",
    ],
}

DEFAULT_BOOK = "draftkings"
