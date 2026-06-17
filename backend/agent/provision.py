"""
provision.py — create and configure a user's AgentEdge instance.
"""

from datetime import datetime, timezone

from agent.bankroll import compute_bankroll_summary, compute_unit_size, compute_max_daily_units
from agent.memory_store import log_episode, upsert_belief


def provision_agent(db, user_id: str, setup: dict) -> dict:
    """Create or update agent instance from onboarding setup."""
    bankroll = float(setup.get("bankroll_starting", 1000))
    unit_pct = float(setup.get("unit_pct", 0.02))
    max_daily_pct = float(setup.get("max_daily_pct", 0.06))
    sports = setup.get("sports", ["MLB", "WC"])
    bet_types = setup.get("bet_types", ["player_props", "straight"])
    risk_level = setup.get("risk_level", "MEDIUM")
    max_plays = int(setup.get("max_plays", 5))
    include_parlays = bool(setup.get("include_parlays", False))
    notification_email = setup.get("notification_email") or None

    summary = compute_bankroll_summary(bankroll, bankroll, unit_pct, max_daily_pct)
    unit_size = summary["unit_size"]
    max_units = summary["max_daily_units"]

    now = datetime.now(timezone.utc).isoformat()

    agent_row = {
        "user_id": user_id,
        "status": "active",
        "mode": "scanning",
        "bankroll_starting": bankroll,
        "bankroll_current": bankroll,
        "unit_pct": unit_pct,
        "max_daily_pct": max_daily_pct,
        "units_at_risk": 0,
        "subscription_tier": "beta",
        "last_active_at": now,
        "setup_completed_at": now,
    }
    db.table("agent_instances").upsert(agent_row, on_conflict="user_id").execute()

    prefs_row = {
        "user_id": user_id,
        "sports": sports,
        "bet_types": bet_types,
        "risk_level": risk_level,
        "max_plays": max_plays,
        "unit_size": unit_size,
        "include_parlays": include_parlays,
        "notification_email": notification_email,
        "bankroll_starting": bankroll,
        "unit_pct": unit_pct,
        "max_daily_pct": max_daily_pct,
        "updated_at": now,
    }
    db.table("preferences").upsert(prefs_row, on_conflict="user_id").execute()

    # Seed initial beliefs from setup
    upsert_belief(
        db, user_id, "profile",
        f"Risk profile: {risk_level}. Max {max_plays} official plays per day.",
        confidence=1.0,
    )
    upsert_belief(
        db, user_id, "bankroll",
        f"Bankroll ${bankroll:.0f}. 1 unit = ${unit_size:.0f} ({unit_pct*100:.0f}% of bankroll). "
        f"Max daily exposure: {max_units} units ({max_daily_pct*100:.0f}% of bankroll).",
        confidence=1.0,
    )
    sport_str = ", ".join(sports)
    upsert_belief(
        db, user_id, "sport",
        f"User tracks: {sport_str}. Only analyze and recommend within these sports.",
        confidence=1.0,
    )
    bet_str = ", ".join(bet_types)
    upsert_belief(
        db, user_id, "market",
        f"Allowed bet types: {bet_str}. "
        f"{'Parlays enabled.' if include_parlays else 'No parlays — singles only.'}",
        confidence=1.0,
    )

    log_episode(
        db, user_id,
        trigger_type="agent_provisioned",
        episode_type="system",
        title="Agent online",
        reasoning=(
            f"Your AgentEdge instance is active. Bankroll: ${bankroll:.0f}. "
            f"Unit size: ${unit_size:.0f}. Scanning {sport_str}."
        ),
    )

    return {
        "provisioned": True,
        "agent": agent_row,
        "bankroll": summary,
    }


def get_agent_status(db, user_id: str, prefs: dict | None = None) -> dict:
    agent = db.table("agent_instances").select("*").eq("user_id", user_id).execute()
    if not agent.data:
        return {"provisioned": False, "status": "pending_setup"}

    inst = agent.data[0]
    if not prefs:
        prefs_result = db.table("preferences").select("*").eq("user_id", user_id).execute()
        prefs = prefs_result.data[0] if prefs_result.data else {}

    bankroll = compute_bankroll_summary(
        float(inst["bankroll_current"]),
        float(inst["bankroll_starting"]),
        float(inst.get("unit_pct", 0.02)),
        float(inst.get("max_daily_pct", 0.06)),
        float(inst.get("units_at_risk", 0)),
    )

    return {
        "provisioned": inst.get("setup_completed_at") is not None,
        "status": inst["status"],
        "mode": inst["mode"],
        "bankroll": bankroll,
        "last_active_at": inst.get("last_active_at"),
        "last_scan_at": inst.get("last_scan_at"),
        "subscription_tier": inst.get("subscription_tier", "beta"),
        "preferences": {
            "sports": prefs.get("sports", []),
            "bet_types": prefs.get("bet_types", []),
            "risk_level": prefs.get("risk_level", "MEDIUM"),
            "max_plays": prefs.get("max_plays", 5),
        },
    }
