"""
bankroll_backfill.py — replay graded bets to rebuild agent_instances.bankroll_current.
"""

from agent.bankroll import apply_bet_result, compute_unit_size, DEFAULT_UNIT_PCT
from services.units import normalize_units_result


def replay_bankroll_for_user(db, user_id: str) -> dict:
    """
    Replay all graded bets in chronological order from bankroll_starting.
    Updates agent_instances.bankroll_current and preferences.unit_size.
    """
    inst_result = db.table("agent_instances").select("*").eq("user_id", user_id).execute()
    if not inst_result.data:
        return {"user_id": user_id, "skipped": True, "reason": "no agent instance"}

    inst = inst_result.data[0]
    unit_pct = float(inst.get("unit_pct") or DEFAULT_UNIT_PCT)
    bankroll = float(inst["bankroll_starting"])
    starting = bankroll

    bets_result = (
        db.table("bets")
        .select("*")
        .eq("user_id", user_id)
        .neq("result", "pending")
        .order("date")
        .order("created_at")
        .execute()
    )
    bets = bets_result.data or []

    for bet in bets:
        units_result = normalize_units_result(bet)
        unit_size = compute_unit_size(bankroll, unit_pct)
        bankroll = apply_bet_result(bankroll, units_result, unit_size)

    db.table("agent_instances").update({
        "bankroll_current": bankroll,
    }).eq("user_id", user_id).execute()

    from agent.unit_tracker import refresh_stored_unit_size
    refresh_stored_unit_size(db, user_id)

    pnl = round(bankroll - starting, 2)
    return {
        "user_id": user_id,
        "bankroll_starting": starting,
        "bankroll_current": bankroll,
        "pnl": pnl,
        "bets_replayed": len(bets),
    }


def backfill_all_agent_bankrolls(db) -> dict:
    """Replay bankroll for every user with an agent_instances row."""
    agents = db.table("agent_instances").select("user_id").execute()
    results = []
    for row in agents.data or []:
        try:
            results.append(replay_bankroll_for_user(db, row["user_id"]))
        except Exception as e:
            results.append({
                "user_id": row["user_id"],
                "error": str(e),
            })

    updated = [r for r in results if not r.get("skipped") and not r.get("error")]
    return {
        "users_processed": len(results),
        "users_updated": len(updated),
        "results": results,
    }
