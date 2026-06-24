"""
post_grade.py — side effects after a bet is graded: bankroll update, episode outcomes.
"""

from agent.bankroll import apply_bet_result, compute_unit_size, DEFAULT_UNIT_PCT
from agent.memory_store import expire_stale_hypotheses, link_position_episode_outcome


def update_bankroll_after_grade(db, bet: dict, units_result: float) -> bool:
    """Apply graded P&L to agent_instances.bankroll_current. Returns True if updated."""
    user_id = bet.get("user_id")
    if not user_id:
        return False

    inst_result = db.table("agent_instances").select("*").eq("user_id", user_id).execute()
    if not inst_result.data:
        return False

    inst = inst_result.data[0]
    unit_pct = float(inst.get("unit_pct") or DEFAULT_UNIT_PCT)
    bankroll_current = float(inst["bankroll_current"])
    unit_size = compute_unit_size(bankroll_current, unit_pct)
    new_bankroll = apply_bet_result(bankroll_current, float(units_result), unit_size)

    db.table("agent_instances").update({
        "bankroll_current": new_bankroll,
    }).eq("user_id", user_id).execute()

    from agent.unit_tracker import refresh_stored_unit_size
    refresh_stored_unit_size(db, user_id)
    return True


def apply_post_grade_effects(
    db,
    bet: dict,
    result: str,
    units_result: float,
    *,
    tag: str = "",
) -> None:
    """Run all per-bet post-grade hooks for agent learning loop."""
    update_bankroll_after_grade(db, bet, units_result)
    link_position_episode_outcome(db, bet, result, units_result, tag=tag)


def finalize_grade_batch(db, affected_user_ids: set[str]) -> None:
    """Batch cleanup after grading: expire stale hypotheses per affected user."""
    for uid in affected_user_ids:
        expire_stale_hypotheses(db, uid)
