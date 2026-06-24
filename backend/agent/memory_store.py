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


def expire_stale_hypotheses(db, user_id: str | None = None) -> int:
    """Mark watching hypotheses past expires_at as expired. Returns count updated."""
    now = datetime.now(timezone.utc).isoformat()
    query = (
        db.table("agent_hypotheses")
        .select("id")
        .eq("status", "watching")
        .lt("expires_at", now)
    )
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.execute()
    rows = result.data or []
    if not rows:
        return 0

    ids = [row["id"] for row in rows]
    db.table("agent_hypotheses").update({
        "status": "expired",
        "updated_at": now,
    }).in_("id", ids).execute()
    return len(ids)


def link_position_episode_outcome(
    db,
    bet: dict,
    result: str,
    units_result: float,
    *,
    tag: str = "",
) -> bool:
    """Attach W/L/P outcome to the agent_episodes row for this position bet."""
    user_id = bet.get("user_id")
    if not user_id:
        return False

    episode_id = _find_position_episode(db, user_id, bet)
    if not episode_id:
        return False

    db.table("agent_episodes").update({
        "outcome": result,
        "lesson": _grade_lesson(result, float(units_result), tag),
    }).eq("id", episode_id).execute()
    return True


def _find_position_episode(db, user_id: str, bet: dict) -> str | None:
    bet_id = bet.get("id")
    bet_text = (bet.get("bet") or "").strip()

    eps_result = (
        db.table("agent_episodes")
        .select("id, title, action_payload")
        .eq("user_id", user_id)
        .eq("episode_type", "position")
        .is_("outcome", "null")
        .order("timestamp", desc=True)
        .limit(25)
        .execute()
    )

    for ep in eps_result.data or []:
        payload = ep.get("action_payload") or {}
        payload_bet_id = payload.get("bet_id")
        if bet_id and payload_bet_id and str(payload_bet_id) == str(bet_id):
            return ep["id"]
        payload_bet = (payload.get("bet") or "").strip()
        if bet_text and payload_bet == bet_text:
            return ep["id"]
        title = ep.get("title") or ""
        if bet_text and title == f"Position: {bet_text}":
            return ep["id"]

    return None


def _grade_lesson(result: str, units_result: float, tag: str) -> str:
    tag = (tag or "").strip()
    if result == "W":
        base = f"Win ({units_result:+.1f}u)."
        return f"{base} {tag}." if tag else base
    if result == "L":
        base = f"Loss ({units_result:.1f}u)."
        return f"{base} {tag}." if tag else f"{base} Review thesis and market selection."
    return "Push — stake returned."


def format_hypotheses_for_prompt(hypotheses: list) -> str:
    if not hypotheses:
        return ""
    lines = ["\n--- ACTIVE HYPOTHESES (update, act, or let expire if stale) ---"]
    for hyp in hypotheses[:8]:
        lines.append(f"  • [{hyp.get('sport', '')}] {hyp.get('game', '')} — {hyp.get('market', '')}")
        if hyp.get("player"):
            lines.append(f"    Player: {hyp['player']}")
        lines.append(f"    Thesis: {hyp.get('thesis', '')}")
    return "\n".join(lines)


def format_recent_episodes_for_prompt(episodes: list) -> str:
    useful_types = {"observation", "hypothesis", "pass", "position", "mode"}
    filtered = [ep for ep in episodes if ep.get("episode_type") in useful_types][:12]
    if not filtered:
        return ""

    lines = ["\n--- RECENT AGENT ACTIVITY (continuity from prior scans) ---"]
    for ep in filtered:
        etype = ep.get("episode_type", "")
        title = ep.get("title", "")
        outcome = ep.get("outcome")
        suffix = f" → {outcome}" if outcome else ""
        lines.append(f"  • [{etype}] {title}{suffix}")
        reasoning = (ep.get("reasoning") or "").strip()
        if reasoning:
            snippet = reasoning if len(reasoning) <= 200 else reasoning[:197] + "..."
            lines.append(f"    {snippet}")
        lesson = (ep.get("lesson") or "").strip()
        if lesson and outcome:
            lines.append(f"    Lesson: {lesson}")
    return "\n".join(lines)
