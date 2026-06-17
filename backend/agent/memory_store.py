"""
memory_store.py — CRUD for per-user agent memory (episodes, beliefs, hypotheses).
"""

from datetime import datetime, timedelta, timezone


def get_agent_instance(db, user_id: str) -> dict | None:
    result = db.table("agent_instances").select("*").eq("user_id", user_id).execute()
    return result.data[0] if result.data else None


def log_episode(
    db,
    user_id: str,
    *,
    trigger_type: str = "scheduled_scan",
    trigger_payload: dict | None = None,
    episode_type: str = "observation",
    title: str = "",
    reasoning: str = "",
    action_payload: dict | None = None,
) -> dict | None:
    row = {
        "user_id": user_id,
        "trigger_type": trigger_type,
        "trigger_payload": trigger_payload or {},
        "episode_type": episode_type,
        "title": title,
        "reasoning": reasoning,
        "action_payload": action_payload or {},
    }
    result = db.table("agent_episodes").insert(row).execute()
    return result.data[0] if result.data else None


def get_feed(db, user_id: str, limit: int = 50) -> list:
    result = (
        db.table("agent_episodes")
        .select("*")
        .eq("user_id", user_id)
        .order("timestamp", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_beliefs(db, user_id: str, limit: int = 20) -> list:
    result = (
        db.table("agent_beliefs")
        .select("*")
        .eq("user_id", user_id)
        .order("last_validated", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def upsert_belief(db, user_id: str, category: str, belief: str, confidence: float = 0.5) -> None:
    existing = (
        db.table("agent_beliefs")
        .select("id, evidence_count")
        .eq("user_id", user_id)
        .eq("belief", belief)
        .execute()
    )
    if existing.data:
        rec = existing.data[0]
        db.table("agent_beliefs").update({
            "confidence": confidence,
            "evidence_count": rec["evidence_count"] + 1,
            "last_validated": datetime.now(timezone.utc).isoformat(),
        }).eq("id", rec["id"]).execute()
    else:
        db.table("agent_beliefs").insert({
            "user_id": user_id,
            "category": category,
            "belief": belief,
            "confidence": confidence,
        }).execute()


def get_hypotheses(db, user_id: str, status: str = "watching") -> list:
    result = (
        db.table("agent_hypotheses")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", status)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def create_hypothesis(db, user_id: str, data: dict) -> dict | None:
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    row = {
        "user_id": user_id,
        "sport": data.get("sport", ""),
        "game": data.get("game", ""),
        "market": data.get("market", ""),
        "player": data.get("player", ""),
        "thesis": data.get("thesis", ""),
        "status": "watching",
        "expires_at": expires.isoformat(),
    }
    result = db.table("agent_hypotheses").insert(row).execute()
    return result.data[0] if result.data else None


def format_beliefs_for_prompt(beliefs: list) -> str:
    if not beliefs:
        return "No learned beliefs yet — building from scratch."
    lines = ["Your learned beliefs:"]
    for b in beliefs[:10]:
        conf = int(float(b.get("confidence", 0.5)) * 100)
        lines.append(f"  • [{b.get('category', 'general')}] {b['belief']} (confidence: {conf}%)")
    return "\n".join(lines)
