"""
Daily unit tracker — 1 unit = unit_pct of bankroll (default 3%).

World Cup bets (post_slate_tag=world_cup) are tracked separately and do not
count toward the agent / major-league daily exposure cap.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from agent.bankroll import compute_bankroll_summary, compute_unit_size

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")
DEFAULT_UNIT_PCT = float(os.getenv("UNIT_PCT", "0.03"))
DEFAULT_MAX_DAILY_PCT = float(os.getenv("MAX_DAILY_PCT", "0.06"))

WC_BET_TAG = "world_cup"
ESM_BET_TAG = "esm"
AGENT_BET_TAG = "agent"
WC_SPORT_KEY = "soccer_fifa_world_cup"


def today_mt() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()


def is_wc_bet(bet: dict) -> bool:
    tag = (bet.get("post_slate_tag") or "").strip().lower()
    if tag == WC_BET_TAG:
        return True
    return (bet.get("notes") or "").strip().startswith("[WC]")


def sum_pending_units(
    db,
    user_id: str,
    bet_date: str,
    *,
    exclude_wc: bool = True,
) -> float:
    result = (
        db.table("bets")
        .select("units, result, post_slate_tag, notes")
        .eq("user_id", user_id)
        .eq("date", bet_date)
        .eq("result", "pending")
        .execute()
    )
    total = 0.0
    for bet in result.data or []:
        if exclude_wc and is_wc_bet(bet):
            continue
        total += float(bet.get("units") or 0)
    return round(total, 2)


def sum_wc_pending_units(db, user_id: str, bet_date: str) -> float:
    result = (
        db.table("bets")
        .select("units, result, post_slate_tag, notes")
        .eq("user_id", user_id)
        .eq("date", bet_date)
        .eq("result", "pending")
        .execute()
    )
    total = 0.0
    for bet in result.data or []:
        if is_wc_bet(bet):
            total += float(bet.get("units") or 0)
    return round(total, 2)


def sync_units_at_risk(db, user_id: str, bet_date: Optional[str] = None) -> dict:
    """
    Recalculate agent units_at_risk from today's pending major-league bets.
    WC plays are excluded from the running daily cap.
    """
    bet_date = bet_date or today_mt()
    units = sum_pending_units(db, user_id, bet_date, exclude_wc=True)
    agent = db.table("agent_instances").select("user_id").eq("user_id", user_id).execute()
    if agent.data:
        db.table("agent_instances").update({"units_at_risk": units}).eq("user_id", user_id).execute()
    return {
        "date": bet_date,
        "units_at_risk": units,
        "wc_units_at_risk": sum_wc_pending_units(db, user_id, bet_date),
    }


def get_unit_context(db, user_id: str, bet_date: Optional[str] = None) -> dict:
    """Bankroll summary with live unit size (3% default) and synced exposure."""
    bet_date = bet_date or today_mt()
    synced = sync_units_at_risk(db, user_id, bet_date)

    inst_result = db.table("agent_instances").select("*").eq("user_id", user_id).execute()
    if inst_result.data:
        inst = inst_result.data[0]
        unit_pct = float(inst.get("unit_pct") or DEFAULT_UNIT_PCT)
        max_daily_pct = float(inst.get("max_daily_pct") or DEFAULT_MAX_DAILY_PCT)
        bankroll_current = float(inst["bankroll_current"])
        bankroll_starting = float(inst["bankroll_starting"])
        units_at_risk = float(synced["units_at_risk"])
    else:
        prefs = db.table("preferences").select("*").eq("user_id", user_id).execute()
        p = prefs.data[0] if prefs.data else {}
        unit_pct = float(p.get("unit_pct") or DEFAULT_UNIT_PCT)
        max_daily_pct = float(p.get("max_daily_pct") or DEFAULT_MAX_DAILY_PCT)
        bankroll_current = float(p.get("bankroll_starting") or 1000)
        bankroll_starting = bankroll_current
        units_at_risk = float(synced["units_at_risk"])

    summary = compute_bankroll_summary(
        bankroll_current,
        bankroll_starting,
        unit_pct,
        max_daily_pct,
        units_at_risk,
    )
    summary["wc_units_at_risk"] = synced["wc_units_at_risk"]
    summary["unit_pct"] = unit_pct
    return summary


def refresh_stored_unit_size(db, user_id: str) -> float:
    """Update preferences.unit_size from current bankroll × unit_pct."""
    ctx = get_unit_context(db, user_id)
    unit_size = ctx["unit_size"]
    db.table("preferences").update({
        "unit_size": unit_size,
        "updated_at": datetime.now(ZoneInfo("UTC")).isoformat(),
    }).eq("user_id", user_id).execute()
    return unit_size


def major_league_sport_keys(sport_keys: list[str]) -> list[str]:
    """Exclude World Cup from major-league ESM / agent pipelines."""
    return [k for k in sport_keys if k != WC_SPORT_KEY]
