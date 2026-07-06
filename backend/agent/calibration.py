"""
calibration.py — hard gates from performance memory + post-grade reflection.

Gates enforce what the prompt suggests: avoid markets with proven negative ROI.
"""

from __future__ import annotations

from learning.memory import PLATFORM_MEMORY_KEY

PIPELINE = "agent"

# User-specific gates (primary brain)
BLOCK_MIN_BETS = 5
BLOCK_NET_UNITS = -3.0
CAP_MIN_BETS = 3
CAP_NET_UNITS = -1.5
CAP_MAX_UNITS = 1.0

# Platform-only signal when user sample is thin
PLATFORM_WEAK_MIN_BETS = 5
USER_THIN_SAMPLE = 3
PLATFORM_CAP_MAX_UNITS = 1.0


def _pipeline_block(stats: dict | None, pipeline: str) -> dict:
    if not stats:
        return {}
    by_pipeline = stats.get("by_pipeline") or {}
    if pipeline in by_pipeline:
        return by_pipeline[pipeline]
    return stats


def _market_total(rec: dict) -> int:
    return rec.get("W", 0) + rec.get("L", 0) + rec.get("P", 0)


def build_calibration_gates(
    user_stats: dict | None,
    platform_stats: dict | None,
    *,
    pipeline: str = PIPELINE,
) -> dict:
    """Derive hard gates from user memory (primary) and platform brain (secondary)."""
    gates: dict[str, dict] = {}
    user_block = _pipeline_block(user_stats, pipeline)
    platform_block = _pipeline_block(platform_stats, pipeline)
    user_markets = user_block.get("by_market") or {}
    platform_weak = {
        row["market"]: row
        for row in (platform_block.get("weak_markets") or [])
    }

    for market, rec in user_markets.items():
        total = _market_total(rec)
        net = rec.get("net", 0.0)
        record = f"{rec.get('W', 0)}-{rec.get('L', 0)}"
        if total >= BLOCK_MIN_BETS and net <= BLOCK_NET_UNITS:
            gates[market] = {
                "action": "block",
                "reason": f"Your {pipeline} record in {market} is {record} ({net:+.1f}u over {total} bets).",
                "record": record,
                "net_units": net,
                "sample": total,
                "source": "user",
            }
        elif total >= CAP_MIN_BETS and net <= CAP_NET_UNITS:
            gates[market] = {
                "action": "cap",
                "max_units": CAP_MAX_UNITS,
                "reason": f"Underperforming market — capped at {CAP_MAX_UNITS}u ({record}, {net:+.1f}u).",
                "record": record,
                "net_units": net,
                "sample": total,
                "source": "user",
            }

    for market, weak in platform_weak.items():
        if market in gates:
            continue
        user_rec = user_markets.get(market)
        user_total = _market_total(user_rec) if user_rec else 0
        if user_total >= USER_THIN_SAMPLE:
            continue
        gates[market] = {
            "action": "cap",
            "max_units": PLATFORM_CAP_MAX_UNITS,
            "reason": (
                f"Platform weak market ({weak.get('record', '?')} collective) — "
                f"thin user sample ({user_total} bets), capped at {PLATFORM_CAP_MAX_UNITS}u."
            ),
            "record": weak.get("record", ""),
            "net_units": weak.get("net_units", 0),
            "sample": user_total,
            "source": "platform",
        }

    summary = []
    for market, gate in sorted(gates.items(), key=lambda x: x[1].get("net_units", 0)):
        if gate["action"] == "block":
            summary.append(f"BLOCK {market}: {gate['reason']}")
        else:
            summary.append(f"CAP {market} ≤{gate['max_units']}u: {gate['reason']}")

    return {"markets": gates, "summary": summary}


def format_gates_for_prompt(gates: dict) -> str:
    summary = gates.get("summary") or []
    if not summary:
        return ""
    lines = [
        "\n--- HARD CALIBRATION GATES (enforced in code — do not recommend blocked markets) ---",
    ]
    lines.extend(f"  • {line}" for line in summary)
    return "\n".join(lines)


def evaluate_position(position: dict, gates: dict) -> tuple[bool, float | None, str]:
    """Return (allowed, max_units, reason). max_units None means no cap."""
    market = (position.get("market") or "unknown").strip()
    gate = (gates.get("markets") or {}).get(market)
    if not gate:
        return True, None, ""

    if gate["action"] == "block":
        return False, None, gate["reason"]

    max_units = float(gate.get("max_units", CAP_MAX_UNITS))
    return True, max_units, gate["reason"]


def apply_calibration_to_positions(
    positions: list[dict],
    gates: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Filter/cap positions against gates.
    Returns (accepted_positions, blocked_log).
    """
    accepted: list[dict] = []
    blocked: list[dict] = []

    for pos in positions:
        allowed, max_units, reason = evaluate_position(pos, gates)
        if not allowed:
            blocked.append({
                "bet": pos.get("bet", ""),
                "market": pos.get("market", ""),
                "reason": reason,
                "action": "block",
            })
            continue

        adjusted = dict(pos)
        if max_units is not None:
            units = float(adjusted.get("units", 1))
            if units > max_units:
                adjusted["units"] = max_units
                adjusted["calibration_note"] = reason
        accepted.append(adjusted)

    return accepted, blocked


def load_memory_context(db, user_id: str) -> dict:
    """Load user + platform stats and derived gates for API / scan."""
    user_result = db.table("agent_memory").select("stats, updated_at").eq("user_id", user_id).execute()
    user_row = user_result.data[0] if user_result.data else {}
    user_stats = user_row.get("stats") or {}

    platform_result = (
        db.table("platform_memory")
        .select("stats, updated_at")
        .eq("key", PLATFORM_MEMORY_KEY)
        .execute()
    )
    platform_row = platform_result.data[0] if platform_result.data else {}
    platform_stats = platform_row.get("stats") or {}

    gates = build_calibration_gates(user_stats, platform_stats, pipeline=PIPELINE)
    return {
        "user_stats": user_stats,
        "platform_stats": platform_stats,
        "gates": gates,
        "user_updated_at": user_row.get("updated_at"),
        "platform_updated_at": platform_row.get("updated_at"),
    }


def get_memory_panel(db, user_id: str, beliefs: list | None = None) -> dict:
    """Structured payload for /agent memory panel UI."""
    from agent.memory_store import get_beliefs

    ctx = load_memory_context(db, user_id)
    user_stats = ctx["user_stats"]
    platform_stats = ctx["platform_stats"]
    user_block = _pipeline_block(user_stats, PIPELINE)
    platform_block = _pipeline_block(platform_stats, PIPELINE)

    def _rows(bucket: dict, min_bets: int) -> list[dict]:
        out = []
        for key, rec in (bucket or {}).items():
            total = _market_total(rec)
            if total < min_bets:
                continue
            out.append({
                "key": key,
                "record": f"{rec.get('W', 0)}-{rec.get('L', 0)}",
                "net_units": rec.get("net", 0),
                "sample": total,
            })
        out.sort(key=lambda r: r["net_units"])
        return out

    belief_list = beliefs if beliefs is not None else get_beliefs(db, user_id)

    return {
        "lookback_days": user_stats.get("lookback_days") or platform_stats.get("lookback_days") or 90,
        "user": {
            "summary": _summary_block(user_block),
            "by_market": _rows(user_block.get("by_market"), 2),
            "by_sport": _rows(user_block.get("by_sport"), 2),
            "recent_losses": (user_block.get("recent_losses") or [])[-5:],
            "updated_at": ctx.get("user_updated_at"),
        },
        "platform": {
            "summary": _summary_block(platform_block),
            "active_users": platform_stats.get("active_users", 0),
            "by_market": _rows(platform_block.get("by_market"), 5)[:8],
            "weak_markets": platform_block.get("weak_markets") or [],
            "updated_at": ctx.get("platform_updated_at"),
        },
        "gates": ctx["gates"],
        "beliefs": belief_list,
    }


def _summary_block(block: dict) -> dict | None:
    if not block or not block.get("total_bets"):
        return None
    return {
        "record": f"{block.get('wins', 0)}-{block.get('losses', 0)}-{block.get('pushes', 0)}",
        "net_units": block.get("net_units", 0),
        "roi_pct": block.get("roi_pct", 0),
        "total_bets": block.get("total_bets", 0),
    }


def reflect_on_grade(db, bet: dict, result: str, units_result: float, *, tag: str = "") -> None:
    """
    Post-grade reflection: log feed episode + update beliefs on clear patterns.
    Rule-based (no extra Claude call) — durable insight from outcomes.
    """
    from agent.memory_store import log_episode, upsert_belief

    if result not in ("W", "L", "P"):
        return

    user_id = bet.get("user_id")
    if not user_id:
        return

    market = (bet.get("market") or "unknown").strip()
    sport = bet.get("sport") or ""
    bet_text = bet.get("bet") or ""

    ctx = load_memory_context(db, user_id)
    gates = ctx["gates"]
    gate = (gates.get("markets") or {}).get(market)

    if result == "L":
        title = f"Reflection: loss on {market}"
        parts = [f"Lost {abs(units_result):.1f}u on {bet_text}."]
        if tag:
            parts.append(f"Grade note: {tag}.")
        if gate:
            parts.append(gate["reason"])
        else:
            parts.append("Review thesis and whether market selection matched edge.")
        reasoning = " ".join(parts)

        log_episode(
            db, user_id,
            trigger_type="post_grade",
            episode_type="reflection",
            title=title,
            reasoning=reasoning,
            action_payload={"bet_id": bet.get("id"), "market": market, "result": result},
        )

        if gate and gate["action"] == "block":
            upsert_belief(
                db, user_id,
                category="market",
                belief=f"Avoid {market} until performance recovers ({gate.get('record', '?')} record).",
                confidence=0.85,
            )
        elif gate and gate["action"] == "cap":
            upsert_belief(
                db, user_id,
                category="market",
                belief=f"Size down {market} plays — recent underperformance ({gate.get('record', '?')}).",
                confidence=0.7,
            )

    elif result == "W" and gate and gate["action"] == "block":
        log_episode(
            db, user_id,
            trigger_type="post_grade",
            episode_type="reflection",
            title=f"Reflection: win despite gate on {market}",
            reasoning=(
                f"Won {units_result:+.1f}u on {bet_text}, but {market} remains gated "
                f"({gate.get('record', '?')}, {gate.get('net_units', 0):+.1f}u sample)."
            ),
            action_payload={"bet_id": bet.get("id"), "market": market, "result": result},
        )
