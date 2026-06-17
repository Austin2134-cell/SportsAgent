"""
snapshot_cache.py — shared market snapshot cache backed by Supabase market_snapshots.
All user agent scans read from cache; only the poller writes live API data.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from esm.api_budget import SNAPSHOT_MAX_AGE_MINUTES

TIMEZONE = "America/Denver"


def get_cached_snapshot(db, sport_keys: list[str], target_date: str | None = None) -> dict | None:
    """
    Build a market snapshot from the latest cached sport snapshots.
    Returns None if cache is stale or empty.
    """
    if not sport_keys:
        return None

    today = target_date or datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=SNAPSHOT_MAX_AGE_MINUTES)
    sports_data = {}
    oldest_capture = None

    for sport_key in sport_keys:
        result = (
            db.table("market_snapshots")
            .select("snapshot, captured_at")
            .eq("sport_key", sport_key)
            .order("captured_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            continue
        row = result.data[0]
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        if captured < cutoff:
            continue
        sports_data[sport_key] = row["snapshot"]
        if oldest_capture is None or captured < oldest_capture:
            oldest_capture = captured

    if not sports_data:
        return None

    return {
        "date": today,
        "sports": sports_data,
        "source": "cache",
        "cached_at": oldest_capture.isoformat() if oldest_capture else None,
    }


def store_snapshot(db, sport_key: str, sport_data: dict) -> None:
    db.table("market_snapshots").insert({
        "sport_key": sport_key,
        "snapshot": sport_data,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def cache_age_minutes(db, sport_key: str) -> float | None:
    result = (
        db.table("market_snapshots")
        .select("captured_at")
        .eq("sport_key", sport_key)
        .order("captured_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    captured = datetime.fromisoformat(result.data[0]["captured_at"].replace("Z", "+00:00"))
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - captured).total_seconds() / 60
