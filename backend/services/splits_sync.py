"""
Sync Action Network public betting splits into market_splits table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from esm.action_network_client import (
    fetch_public_splits,
    match_event_to_game,
    SPORT_TO_AN_PATH,
)


def is_configured() -> bool:
    return True  # No API key — uses public HTML pages


def sync_splits_for_sport(db, sport_key: str) -> dict:
    """Pull Action Network public-betting page and write splits rows."""
    if sport_key not in SPORT_TO_AN_PATH:
        return {"sport_key": sport_key, "skipped": True, "reason": "no_an_mapping"}

    try:
        events = fetch_public_splits(sport_key)
    except Exception as e:
        print(f"[splits_sync] Action Network fetch failed for {sport_key}: {e}")
        return {"sport_key": sport_key, "error": str(e), "rows": 0}

    inserted = 0
    captured_at = datetime.now(timezone.utc).isoformat()

    for event in events:
        event_id = event.get("event_id") or ""
        home = event.get("home_team", "")
        away = event.get("away_team", "")

        for market_key, split in (event.get("splits") or {}).items():
            ticket = split.get("public_bet_pct")
            money = split.get("public_money_pct")
            if ticket is None and money is None:
                continue
            try:
                db.table("market_splits").insert({
                    "sport_key": sport_key,
                    "event_id": event_id,
                    "home_team": home,
                    "away_team": away,
                    "market": market_key,
                    "public_bet_pct": ticket,
                    "public_money_pct": money,
                    "sharp_indicator": split.get("sharp_indicator"),
                    "source": "action_network",
                    "raw": {
                        "odds": split.get("odds"),
                        "line": split.get("line"),
                        "team": split.get("team"),
                        "core_id": event.get("core_id"),
                        "num_bets": event.get("num_bets"),
                        "captured_at": captured_at,
                    },
                }).execute()
                inserted += 1
            except Exception as e:
                print(f"[splits_sync] Insert failed {sport_key} {event_id} {market_key}: {e}")

    print(f"[splits_sync] Action Network: {inserted} split row(s) for {sport_key}")
    return {"sport_key": sport_key, "events": len(events), "rows": inserted}


def sync_all_active_splits(db, sport_keys: list[str]) -> dict:
    total = 0
    results = []
    for key in sport_keys:
        r = sync_splits_for_sport(db, key)
        total += r.get("rows", 0)
        results.append(r)
    return {"rows": total, "sports": results}


def find_splits_for_matchup(
    db,
    sport_key: str,
    away_team: str,
    home_team: str,
) -> dict:
    """Load latest splits per market for a game matchup."""
    try:
        result = (
            db.table("market_splits")
            .select("*")
            .eq("sport_key", sport_key)
            .order("captured_at", desc=True)
            .limit(100)
            .execute()
        )
    except Exception:
        return {}

    by_market: dict[str, dict] = {}
    for row in result.data or []:
        if not match_event_to_game(
            {"away_team": row.get("away_team"), "home_team": row.get("home_team")},
            away_team,
            home_team,
        ):
            continue
        market = row.get("market") or ""
        if market not in by_market:
            by_market[market] = row
    return by_market
