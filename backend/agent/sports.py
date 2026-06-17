"""
Sport registry — maps user-facing sport labels to odds API keys.
Supports all major ESM sports; season status controls what's actively polled.
"""

from esm.config import ACTIVE_SPORTS, PROP_MARKETS

# User preference label → internal config
SPORT_REGISTRY: dict[str, dict] = {
    "MLB": {
        "key": "baseball_mlb",
        "label": "MLB",
        "display": "MLB",
        "season_active": True,
    },
    "NBA": {
        "key": "basketball_nba",
        "label": "NBA",
        "display": "NBA",
        "season_active": False,
    },
    "NHL": {
        "key": "icehockey_nhl",
        "label": "NHL",
        "display": "NHL",
        "season_active": False,
    },
    "NFL": {
        "key": "americanfootball_nfl",
        "label": "NFL",
        "display": "NFL",
        "season_active": False,
    },
    "WC": {
        "key": "soccer_fifa_world_cup",
        "label": "World Cup Soccer",
        "display": "WC",
        "season_active": True,
    },
    "NCAAB": {
        "key": "basketball_ncaab",
        "label": "NCAAB",
        "display": "NCAAB",
        "season_active": False,
    },
    "NCAAF": {
        "key": "americanfootball_ncaaf",
        "label": "NCAAF",
        "display": "NCAAF",
        "season_active": False,
    },
}

MAJOR_SPORTS = ["MLB", "NBA", "NHL", "NFL", "WC"]


def user_sport_to_key(sport_label: str) -> str | None:
    entry = SPORT_REGISTRY.get(sport_label.upper() if sport_label != "WC" else "WC")
    if not entry:
        # Allow direct API keys passed through
        if sport_label in ACTIVE_SPORTS:
            return sport_label
        return None
    return entry["key"]


def resolve_user_sports(user_sports: list[str]) -> list[str]:
    """Return odds API keys for a user's selected sports."""
    keys = []
    for sport in user_sports:
        key = user_sport_to_key(sport)
        if key and key not in keys:
            keys.append(key)
    return keys


def get_active_sports_for_polling() -> list[str]:
    """Sports with live seasons — used by shared market poller."""
    return [
        entry["key"]
        for entry in SPORT_REGISTRY.values()
        if entry["season_active"] and entry["key"] in ACTIVE_SPORTS
    ]


def get_all_supported_sports() -> list[dict]:
    """All sports users can select (including off-season)."""
    return [
        {
            "id": label,
            "label": entry["label"],
            "display": entry["display"],
            "season_active": entry["season_active"],
            "has_props": entry["key"] in PROP_MARKETS,
        }
        for label, entry in SPORT_REGISTRY.items()
        if label in MAJOR_SPORTS or label in ("NCAAB", "NCAAF")
    ]


def sport_key_to_display(sport_key: str) -> str:
    for entry in SPORT_REGISTRY.values():
        if entry["key"] == sport_key:
            return entry["display"]
    return sport_key.replace("_", " ").upper()
