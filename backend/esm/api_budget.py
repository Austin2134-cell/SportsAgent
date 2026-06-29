"""
api_budget.py — Odds API usage thresholds and burn-rate math for AgentEdge.

The Odds API (TOA): credits per request (monthly quota, resets on billing cycle)
  - GET /sports                          → FREE
  - GET /sports/{sport}/odds (3 mkts)    → 3 credits (h2h + spreads + totals × 1 region)
  - GET /sports/{sport}/events/{id}/odds → 1 credit per unique market returned × regions

SportsGameOdds (SGO): objects per event + requests per minute (monthly object quota)
  - GET /events (all markets included)   → 1 HTTP request, N objects (1 per event returned)
  - Amateur free: 2,500 objects/mo, 10 req/min, ~10 min data freshness
  - GET /account/usage                   → check remaining quota

Strategy:
  - SGO PRIMARY for continuous polling (1 req → all markets for all games)
  - TOA FALLBACK for mainlines when SGO unavailable; props only when budget allows
  - Shared snapshot cache — poll once, all user agents read cache (never per-user API calls)
"""

import os
from dataclasses import dataclass, field
from typing import Optional

# ── The Odds API ──────────────────────────────────────────────────────────────

TOA_MONTHLY_QUOTA = int(os.getenv("TOA_MONTHLY_QUOTA", "20000"))
TOA_RESERVE = int(os.getenv("TOA_RESERVE", "500"))
TOA_MAINLINES_MIN = int(os.getenv("TOA_MAINLINES_MIN", "100"))
TOA_PROPS_MIN = int(os.getenv("TOA_PROPS_MIN", "1000"))
TOA_PROPS_PER_GAME_RESERVE = int(os.getenv("TOA_PROPS_RESERVE", "10"))  # per-game guard (existing)
TOA_MAINLINE_MARKETS = 3   # h2h + spreads + totals × 1 US region
TOA_PROP_BATCH_SIZE = 4

# ── SportsGameOdds ────────────────────────────────────────────────────────────

SGO_MONTHLY_OBJECTS = int(os.getenv("SGO_MONTHLY_OBJECTS", "2500"))  # Amateur free
SGO_RESERVE = int(os.getenv("SGO_RESERVE", "200"))                    # stop polling below this
SGO_RATE_LIMIT_PER_MIN = int(os.getenv("SGO_RATE_LIMIT_PER_MIN", "10"))
SGO_MIN_REQUEST_INTERVAL_SEC = 60 / SGO_RATE_LIMIT_PER_MIN  # 6 sec between calls

# ── Polling schedule (must align with quotas) ─────────────────────────────────

# SGO free tier refreshes ~every 10 min — but polling that often burns 2,500 objects/mo in ~1 day
# with a typical 18-game slate. Default 60 min; set higher on free tier (see api_budget.py).
POLL_INTERVAL_MINUTES = int(os.getenv("ODDS_POLL_INTERVAL_MINUTES", "360"))
AGENT_SCAN_INTERVAL_MINUTES = int(os.getenv("AGENT_SCAN_INTERVAL_MINUTES", "180"))  # 8 scans/day (24h ÷ 8)
SNAPSHOT_MAX_AGE_MINUTES = int(os.getenv("SNAPSHOT_MAX_AGE_MINUTES", "360"))

# Preferred source: "sgo" (default, cost-efficient) or "toa"
ODDS_PRIMARY_SOURCE = os.getenv("ODDS_PRIMARY_SOURCE", "sgo").lower()

# Max TOA credits to spend on a single full snapshot (safety cap)
TOA_MAX_CREDITS_PER_SNAPSHOT = int(os.getenv("TOA_MAX_CREDITS_PER_SNAPSHOT", "150"))


@dataclass
class ApiUsageState:
    """Runtime usage tracked from API response headers."""
    toa_remaining: Optional[int] = None
    toa_used: Optional[int] = None
    toa_last_cost: Optional[int] = None
    sgo_objects_remaining: Optional[int] = None
    sgo_objects_used: Optional[int] = None
    sgo_requests_remaining_min: Optional[int] = None
    last_source: Optional[str] = None
    last_snapshot_credits: int = 0
    warnings: list[str] = field(default_factory=list)


def estimate_toa_snapshot_cost(num_sports: int, games_by_sport: dict[str, int], prop_markets: dict[str, list]) -> int:
    """
    Estimate TOA credits for one full snapshot with props.
    games_by_sport: {sport_key: game_count_today}
    """
    cost = 0
    for sport, game_count in games_by_sport.items():
        cost += TOA_MAINLINE_MARKETS  # mainlines per sport
        markets = prop_markets.get(sport, [])
        batches = max(1, (len(markets) + TOA_PROP_BATCH_SIZE - 1) // TOA_PROP_BATCH_SIZE) if markets else 0
        cost += game_count * batches
    return cost


def estimate_sgo_snapshot_cost(games_by_sport: dict[str, int]) -> int:
    """SGO objects = total events returned (all markets included per event)."""
    return sum(games_by_sport.values())


def estimate_daily_burn(
    num_users: int = 1,
    games_by_sport: dict[str, int] | None = None,
    poll_interval_min: int = POLL_INTERVAL_MINUTES,
    agent_scan_interval_min: int = AGENT_SCAN_INTERVAL_MINUTES,
    use_cache: bool = True,
) -> dict:
    """
    Estimate daily API consumption under current architecture.
    With shared cache (use_cache=True), agent scans do NOT hit the odds API.
    """
    games = games_by_sport or {"baseball_mlb": 15, "soccer_fifa_world_cup": 3}
    polls_per_day = (24 * 60) // poll_interval_min

    toa_per_poll = estimate_toa_snapshot_cost(len(games), games, _default_prop_markets())
    sgo_per_poll = estimate_sgo_snapshot_cost(games)

    # Without cache: each user scan also fetches odds (bad)
    scans_per_day = (24 * 60) // agent_scan_interval_min
    multiplier = 1 if use_cache else (1 + num_users * scans_per_day / polls_per_day)

    return {
        "polls_per_day": polls_per_day,
        "scans_per_day": scans_per_day,
        "shared_cache": use_cache,
        "toa_credits_per_poll": toa_per_poll,
        "toa_credits_per_day": int(toa_per_poll * polls_per_day * multiplier),
        "toa_days_until_exhausted_free_tier": round(TOA_MONTHLY_QUOTA / max(1, toa_per_poll * polls_per_day * multiplier), 1),
        "sgo_objects_per_poll": sgo_per_poll,
        "sgo_objects_per_day": int(sgo_per_poll * polls_per_day * multiplier),
        "sgo_days_until_exhausted_free_tier": round(SGO_MONTHLY_OBJECTS / max(1, sgo_per_poll * polls_per_day * multiplier), 1),
        "recommended_poll_interval_min": _recommend_poll_interval(sgo_per_poll),
    }


def _default_prop_markets() -> dict[str, list]:
    from esm.config import PROP_MARKETS
    return PROP_MARKETS


def _recommend_poll_interval(sgo_objects_per_poll: int) -> int:
    """Poll interval that keeps SGO free tier under ~80% monthly utilization."""
    if sgo_objects_per_poll <= 0:
        return POLL_INTERVAL_MINUTES
    # objects per day at 80% budget spread across 30 days
    max_polls_per_day = (SGO_MONTHLY_OBJECTS * 0.8) / sgo_objects_per_poll / 30
    if max_polls_per_day < 1:
        return 360  # ~4 polls/day max on free tier with heavy slates
    interval = (24 * 60) / max_polls_per_day
    return max(10, min(int(interval), 360))


def should_use_toa(usage: ApiUsageState, credits_needed: int = TOA_MAINLINE_MARKETS) -> bool:
    if usage.toa_remaining is None:
        return True  # unknown — try once
    return usage.toa_remaining - credits_needed >= TOA_RESERVE


def should_fetch_toa_props(usage: ApiUsageState) -> bool:
    if usage.toa_remaining is None:
        return True
    return usage.toa_remaining >= max(TOA_PROPS_MIN, TOA_PROPS_PER_GAME_RESERVE)


def should_use_sgo(usage: ApiUsageState, objects_needed: int = 20) -> bool:
    if usage.sgo_objects_remaining is None:
        return True
    return usage.sgo_objects_remaining - objects_needed >= SGO_RESERVE


def budget_summary(usage: ApiUsageState) -> dict:
    """Human-readable budget status for admin dashboard."""
    toa_pct = None
    if usage.toa_remaining is not None:
        toa_pct = round((usage.toa_remaining / TOA_MONTHLY_QUOTA) * 100, 1)

    sgo_pct = None
    if usage.sgo_objects_remaining is not None:
        sgo_pct = round((usage.sgo_objects_remaining / SGO_MONTHLY_OBJECTS) * 100, 1)

    return {
        "primary_source": ODDS_PRIMARY_SOURCE,
        "poll_interval_minutes": POLL_INTERVAL_MINUTES,
        "snapshot_max_age_minutes": SNAPSHOT_MAX_AGE_MINUTES,
        "the_odds_api": {
            "monthly_quota": TOA_MONTHLY_QUOTA,
            "remaining": usage.toa_remaining,
            "used": usage.toa_used,
            "last_call_cost": usage.toa_last_cost,
            "remaining_pct": toa_pct,
            "reserve_threshold": TOA_RESERVE,
            "props_min_threshold": TOA_PROPS_MIN,
            "status": _status_label(usage.toa_remaining, TOA_RESERVE, TOA_MONTHLY_QUOTA),
        },
        "sportsgameodds": {
            "monthly_objects": SGO_MONTHLY_OBJECTS,
            "objects_remaining": usage.sgo_objects_remaining,
            "objects_used": usage.sgo_objects_used,
            "requests_remaining_per_min": usage.sgo_requests_remaining_min,
            "remaining_pct": sgo_pct,
            "reserve_threshold": SGO_RESERVE,
            "rate_limit_per_min": SGO_RATE_LIMIT_PER_MIN,
            "status": _status_label(usage.sgo_objects_remaining, SGO_RESERVE, SGO_MONTHLY_OBJECTS),
        },
        "last_source": usage.last_source,
        "last_snapshot_credits": usage.last_snapshot_credits,
        "warnings": usage.warnings,
        "projected_daily_burn": estimate_daily_burn(),
    }


def _status_label(remaining: Optional[int], reserve: int, total: int) -> str:
    if remaining is None:
        return "unknown"
    if remaining <= reserve:
        return "critical"
    if remaining <= total * 0.2:
        return "low"
    return "ok"
