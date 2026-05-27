import os
from dotenv import load_dotenv

# Load .env from the same directory as this file, regardless of where Python is called from
_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_here, ".env"), override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
SGO_API_KEY = os.getenv("SGO_API_KEY", "")   # SportsGameOdds free fallback

# Bankroll settings — 1 unit = this many dollars. Set to your comfort level.
UNIT_SIZE_DOLLARS = float(os.getenv("UNIT_SIZE_DOLLARS", "50"))

# Hard cap: max wagers placed per calendar day
MAX_WAGERS_PER_DAY = 5


# Default book (DK per ESM Operations Addendum)
DEFAULT_BOOK = "draftkings"

# Time zone for output (MDT per ESM Operations Addendum)
TIMEZONE = "America/Denver"

# Straight-bet juice limit (ESM: avoid worse than -150 without explicit approval)
MAX_JUICE = -150

# Sports tracked by The Odds API sport key
ACTIVE_SPORTS = [
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "americanfootball_nfl",
    "basketball_ncaab",
]

# Player prop markets to pull per sport
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
}

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
BET_LOG_PATH = os.path.join(DATA_DIR, "bets.csv")
