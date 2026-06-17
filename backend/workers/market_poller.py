"""
market_poller.py — shared market perception layer.
Polls odds once for all active sports, stores snapshots.
User agent scans read from cache — never hit the API directly.
"""

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from agent.kernel import run_agent_scan
from agent.sports import get_active_sports_for_polling
from esm.api_budget import budget_summary, should_use_sgo, should_use_toa
from esm.odds_client import OddsClient
from esm.snapshot_cache import store_snapshot

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")


def _store_snapshot_results(db, snapshot: dict, sport_keys: list[str], client: OddsClient) -> dict:
    stored = 0
    for sport_key in sport_keys:
        sport_data = snapshot.get("sports", {}).get(sport_key)
        if not sport_data:
            continue
        try:
            store_snapshot(db, sport_key, sport_data)
            stored += 1
        except Exception as e:
            print(f"[poller] Failed to store {sport_key}: {e}")

    game_count = sum(
        len(snapshot.get("sports", {}).get(k, {}).get("games", []))
        for k in sport_keys
    )
    source = snapshot.get("source", client._source)
    return {
        "polled": stored,
        "sports": sport_keys,
        "games": game_count,
        "source": source,
        "credits_spent": snapshot.get("credits_spent") or snapshot.get("objects_consumed"),
        "budget": budget_summary(OddsClient.get_usage()),
    }


def poll_markets(db, force_source: Optional[str] = None) -> dict:
    """Fetch and store market snapshots for all in-season sports."""
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    sport_keys = get_active_sports_for_polling()
    if not sport_keys:
        return {"polled": 0, "sports": []}

    odds_key = os.getenv("ODDS_API_KEY", "")
    sgo_key = os.getenv("SGO_API_KEY", "")
    if force_source == "toa" and not odds_key:
        return {"polled": 0, "error": "no_odds_api_key"}
    if force_source != "toa" and not odds_key and not sgo_key:
        print("[poller] No ODDS_API_KEY or SGO_API_KEY — skipping market poll")
        return {"polled": 0, "error": "no_api_keys"}

    usage = OddsClient.get_usage()
    if force_source != "toa":
        if not should_use_sgo(usage) and not should_use_toa(usage):
            print("[poller] Both API quotas below reserve — skipping poll")
            return {"polled": 0, "error": "quota_critical", "budget": budget_summary(usage)}

    client = OddsClient()
    snapshot = client.build_market_snapshot(
        target_date=today, sport_keys=sport_keys, force_source=force_source,
    )
    result = _store_snapshot_results(db, snapshot, sport_keys, client)
    print(f"[poller] {result['source']} — stored {result['polled']} snapshots, {result['games']} games")
    return result


def poll_morning_toa_snapshot(db) -> dict:
    """
    Daily 9:25 AM MT — one deliberate TOA snapshot with full props.
    Uses ~39 credits/day (~1,170/month on 20K plan). Saves SGO objects for background polling.
    """
    enabled = os.getenv("TOA_MORNING_SNAPSHOT", "true").lower() in ("1", "true", "yes")
    if not enabled:
        return {"skipped": True, "reason": "TOA_MORNING_SNAPSHOT disabled"}

    print("[poller] Running morning TOA snapshot (forced The Odds API)...")
    result = poll_markets(db, force_source="toa")
    result["job"] = "morning_toa_snapshot"
    return result


def run_all_agent_scans(db) -> dict:
    """Run agent scan for every active, provisioned user (reads from cache)."""
    agents = (
        db.table("agent_instances")
        .select("user_id")
        .eq("status", "active")
        .not_.is_("setup_completed_at", "null")
        .execute()
    )
    users = agents.data or []
    results = {"scanned": 0, "errors": 0, "details": []}

    for row in users:
        uid = row["user_id"]
        try:
            result = run_agent_scan(db, uid, trigger_type="scheduled_scan")
            results["scanned"] += 1
            results["details"].append({"user_id": uid, **result})
        except Exception as e:
            results["errors"] += 1
            print(f"[poller] Agent scan failed for {uid}: {e}")

    print(f"[poller] Agent scans complete: {results['scanned']} users, {results['errors']} errors")
    return results
