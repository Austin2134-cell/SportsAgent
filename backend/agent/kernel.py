"""
kernel.py — per-user agent scan loop.
Observes markets, writes episodes, tracks hypotheses, recommends positions.
"""

import json
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import anthropic

from agent.unit_tracker import AGENT_BET_TAG, get_unit_context, major_league_sport_keys, sync_units_at_risk
from agent.memory_store import (
    create_hypothesis, get_agent_instance, get_beliefs, log_episode,
    upsert_belief, format_beliefs_for_prompt, expire_stale_hypotheses,
    get_hypotheses, get_feed, format_hypotheses_for_prompt, format_recent_episodes_for_prompt,
)
from agent.prompt import build_agent_system_prompt
from agent.sports import resolve_user_sports, sport_key_to_display
from esm.odds_client import OddsClient
from esm.stats_client import StatsClient
from learning.memory import get_defensive_settings, get_performance_context
from esm.play_validation import apply_position_guards
from services.card_store import bet_key

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")
MODEL = "claude-sonnet-4-6"


def run_agent_scan(db, user_id: str, trigger_type: str = "scheduled_scan") -> dict:
    """Run one agent scan cycle for a user."""
    agent = get_agent_instance(db, user_id)
    if not agent or agent.get("status") != "active":
        return {"skipped": True, "reason": "agent not active"}

    prefs_result = db.table("preferences").select("*").eq("user_id", user_id).execute()
    prefs = prefs_result.data[0] if prefs_result.data else {}
    profile_result = db.table("profiles").select("full_name, email").eq("id", user_id).execute()
    profile = profile_result.data[0] if profile_result.data else {}
    user_name = profile.get("full_name") or profile.get("email", "User")

    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    user_sports = prefs.get("sports", ["MLB", "WC"])
    sport_keys = major_league_sport_keys(resolve_user_sports(user_sports))

    if not sport_keys:
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="observation",
            title="No major-league sports configured",
            reasoning="World Cup is handled by the separate daily WC card. Add MLB/NBA/NHL/NFL in preferences.",
        )
        return {"skipped": True, "reason": "no major-league sports selected"}

    expire_stale_hypotheses(db, user_id)

    sync_units_at_risk(db, user_id, today)
    bankroll = get_unit_context(db, user_id, today)
    unit_size = bankroll["unit_size"]
    max_units = bankroll["max_daily_units"]

    # Fetch filtered market data for user's sports only
    market_snapshot = _build_filtered_snapshot(db, today, sport_keys)
    espn_context = _build_espn_context(market_snapshot, today)
    beliefs = get_beliefs(db, user_id)
    perf_context = get_performance_context(db, user_id)
    defensive = get_defensive_settings(db, user_id, pipeline="agent")
    max_plays_pref = int(prefs.get("max_plays", 5))
    if defensive["defensive"]:
        cap = defensive["max_plays"] or max_plays_pref
        max_plays_pref = min(max_plays_pref, cap)
        print(
            f"[agent] Defensive mode: max {max_plays_pref} positions "
            f"({'; '.join(defensive['reasons'])})"
        )
    watching = get_hypotheses(db, user_id, status="watching")
    recent_episodes = get_feed(db, user_id, limit=15)

    system_prompt = build_agent_system_prompt(
        user_name=user_name,
        bankroll_current=bankroll["bankroll_current"],
        bankroll_starting=bankroll["bankroll_starting"],
        unit_size=unit_size,
        max_daily_units=max_units,
        units_at_risk=bankroll["units_at_risk"],
        risk_level=prefs.get("risk_level", "MEDIUM"),
        sports=user_sports,
        bet_types=prefs.get("bet_types", []),
        include_parlays=prefs.get("include_parlays", False),
        mode=agent.get("mode", "scanning"),
        beliefs_text=format_beliefs_for_prompt(beliefs),
        performance_text=perf_context or "No graded bet history yet.",
    )

    user_message = _build_scan_message(
        today, market_snapshot, espn_context,
        max_plays=max_plays_pref,
        units_remaining=bankroll["units_remaining_today"],
        hypotheses_text=format_hypotheses_for_prompt(watching),
        recent_activity_text=format_recent_episodes_for_prompt(recent_episodes),
        defensive_note=(
            f"DEFENSIVE MODE: cap {max_plays_pref} positions, -0.5u sizing. "
            f"Reasons: {'; '.join(defensive['reasons'])}."
            if defensive["defensive"] else ""
        ),
    )

    scan_result = _call_agent(system_prompt, user_message)
    if not scan_result:
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="error",
            title="Scan failed",
            reasoning="Agent could not complete analysis. Will retry on next cycle.",
        )
        return {"error": "claude_failed"}

    now = datetime.now(timezone.utc).isoformat()
    new_mode = scan_result.get("mode", agent.get("mode", "scanning"))

    db.table("agent_instances").update({
        "mode": new_mode,
        "last_active_at": now,
        "last_scan_at": now,
    }).eq("user_id", user_id).execute()

    # Log mode change
    if scan_result.get("mode_reason"):
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="mode",
            title=f"Mode: {new_mode.upper()}",
            reasoning=scan_result["mode_reason"],
        )

    # Observations → feed
    for obs in scan_result.get("observations", []):
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="observation",
            title=obs.get("title", "Market observation"),
            reasoning=obs.get("reasoning", ""),
        )

    # Hypotheses → tracking
    for hyp in scan_result.get("hypotheses", []):
        create_hypothesis(db, user_id, hyp)
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="hypothesis",
            title=f"Watching: {hyp.get('game', '')} — {hyp.get('market', '')}",
            reasoning=hyp.get("thesis", ""),
            action_payload=hyp,
        )

    # Pass notes → feed
    for note in scan_result.get("pass_notes", []):
        log_episode(
            db, user_id, trigger_type=trigger_type, episode_type="pass",
            title="Passed",
            reasoning=note if isinstance(note, str) else str(note),
        )

    # Belief updates
    for belief in scan_result.get("belief_updates", []):
        upsert_belief(
            db, user_id,
            belief.get("category", "general"),
            belief.get("belief", ""),
            float(belief.get("confidence", 0.5)),
        )

    # Positions → bets + card (backward compatible with existing UI)
    positions = scan_result.get("positions", [])
    if positions:
        positions = apply_position_guards(
            positions,
            blocked_markets=defensive["blocked_markets"],
            unit_reduction=defensive["unit_reduction"],
            max_plays=max_plays_pref if defensive["defensive"] else None,
        )
    units_used = 0.0
    if positions:
        units_used = _persist_positions(
            db, user_id, today, positions,
            max_plays=max_plays_pref,
            units_remaining=bankroll["units_remaining_today"],
        )

    if units_used > 0:
        synced = sync_units_at_risk(db, user_id, today)
        db.table("agent_instances").update({
            "units_at_risk": synced["units_at_risk"],
            "mode": "acting",
        }).eq("user_id", user_id).execute()

    return {
        "user_id": user_id,
        "mode": new_mode,
        "observations": len(scan_result.get("observations", [])),
        "hypotheses": len(scan_result.get("hypotheses", [])),
        "positions": len(positions),
        "passes": len(scan_result.get("pass_notes", [])),
    }


def _build_filtered_snapshot(db, today: str, sport_keys: list[str]) -> dict:
    """Read from shared cache first; live API only as fallback."""
    from esm.snapshot_cache import get_cached_snapshot

    cached = get_cached_snapshot(db, sport_keys, today)
    if cached and cached.get("sports"):
        print(f"[agent] Using cached snapshot ({len(cached['sports'])} sports)")
        return cached

    print("[agent] Cache miss — fetching live odds (fallback)")
    client = OddsClient()
    full = client.build_market_snapshot(target_date=today, sport_keys=sport_keys)
    filtered_sports = {
        k: v for k, v in full.get("sports", {}).items() if k in sport_keys
    }
    return {"date": today, "sports": filtered_sports, "source": full.get("source", "live")}


def _build_espn_context(market_snapshot: dict, today: str) -> dict:
    client = StatsClient()
    context = {}
    date_str = today.replace("-", "")
    for sport_key in market_snapshot.get("sports", {}).keys():
        try:
            ctx = client.build_context_package(sport_key, date_str)
            if ctx.get("scoreboard") or ctx.get("injuries"):
                context[sport_key] = ctx
        except Exception as e:
            print(f"[agent] ESPN error for {sport_key}: {e}")
    return context


def _build_scan_message(
    today: str, market_snapshot: dict, espn_context: dict,
    max_plays: int, units_remaining: float,
    hypotheses_text: str = "",
    recent_activity_text: str = "",
    defensive_note: str = "",
) -> str:
    parts = [
        f"SCAN DATE: {today}",
        f"MAX NEW POSITIONS THIS SCAN: {max_plays}",
        f"UNITS REMAINING TODAY: {units_remaining:.1f}",
    ]
    if defensive_note:
        parts.append(defensive_note)
    if hypotheses_text:
        parts.append(hypotheses_text)
    if recent_activity_text:
        parts.append(recent_activity_text)
    parts.append("\n--- LIVE MARKET DATA (user's sports only) ---")
    sports = market_snapshot.get("sports", {})
    if sports:
        parts.append(_summarize_market(market_snapshot))
    else:
        parts.append("No games with odds data for user's selected sports today.")

    parts.append("\n--- INJURY / TEAM CONTEXT ---")
    if espn_context:
        parts.append(_summarize_espn(espn_context))
    else:
        parts.append("No ESPN context available.")

    parts.append(
        "\nRun your agent scan. Review active hypotheses and recent activity above. "
        "Observe the slate, track hypotheses, recommend positions only where edge is clear "
        "and within exposure limits. Return ONLY valid JSON matching the agent scan output schema."
    )
    return "\n".join(parts)


def _summarize_market(snapshot: dict) -> str:
    lines = []
    for sport, sport_data in snapshot.get("sports", {}).items():
        label = sport_key_to_display(sport)
        lines.append(f"\n[{label}]")
        for game in sport_data.get("games", []):
            away = game["away_team"]
            home = game["home_team"]
            time = game.get("commence_time", "")[:16].replace("T", " ")
            gl = game.get("lines", {})
            lines.append(
                f"  {away} @ {home} | {time} UTC"
                f" | ML: {away} {gl.get('away_ml', 'N/A')} / {home} {gl.get('home_ml', 'N/A')}"
                f" | Spread: {home} {gl.get('home_spread', 'N/A')}"
                f" | Total: {gl.get('total', 'N/A')}"
            )
            props = game.get("props", {})
            for market, players in props.items():
                market_label = market.replace("player_", "").replace("_", " ").title()
                lines.append(f"    {market_label}:")
                for i, (player, directions) in enumerate(players.items()):
                    if i >= 6:
                        break
                    over = directions.get("Over", {})
                    under = directions.get("Under", {})
                    line_val = over.get("line") or under.get("line", "?")
                    lines.append(
                        f"      {player}: {line_val} | O{over.get('best_odds', '')} / U{under.get('best_odds', '')}"
                    )
    return "\n".join(lines)


def _summarize_espn(espn_context: dict) -> str:
    lines = []
    for sport, data in espn_context.items():
        label = sport_key_to_display(sport)
        injuries = data.get("injuries", [])
        if injuries:
            lines.append(f"\n{label} INJURIES:")
            for inj in injuries[:15]:
                lines.append(f"  {inj['team']} — {inj['player']} ({inj['status']}): {inj['detail']}")
    return "\n".join(lines) if lines else "No context available."


def _call_agent(system_prompt: str, user_message: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[agent] No ANTHROPIC_API_KEY")
        return {}
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as e:
        print(f"[agent] Claude API error: {e}")
        return {}

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"[agent] JSON parse failed. First 300 chars:\n{raw[:300]}")
        return {}


def _persist_positions(
    db, user_id: str, today: str, positions: list,
    max_plays: int, units_remaining: float,
) -> float:
    """Write positions to bets table and today's card. Returns units used."""
    existing = (
        db.table("bets")
        .select("game, bet")
        .eq("user_id", user_id)
        .eq("date", today)
        .execute()
    )
    seen_bets = {bet_key(b) for b in (existing.data or [])}

    units_used = 0.0
    accepted = []

    for pos in positions[:max_plays]:
        key = bet_key(pos)
        if key in seen_bets:
            print(f"[agent] Skipping duplicate position: {pos.get('bet', '')}")
            continue
        units = float(pos.get("units", 1))
        if units_used + units > units_remaining:
            continue
        accepted.append(pos)
        seen_bets.add(key)
        units_used += units

    if not accepted:
        return 0.0

    # Upsert today's card for backward-compatible dashboard
    existing = db.table("cards").select("id, plays").eq("user_id", user_id).eq("date", today).execute()
    if existing.data:
        card_id = existing.data[0]["id"]
        merged_plays = (existing.data[0].get("plays") or []) + accepted
        db.table("cards").update({"plays": merged_plays}).eq("id", card_id).execute()
    else:
        card_result = db.table("cards").insert({
            "user_id": user_id,
            "date": today,
            "slate_grade": "B",
            "slate_note": "Agent scan",
            "plays": accepted,
            "leans": [],
            "quick_reads": [],
            "pass_notes": [],
        }).execute()
        card_id = card_result.data[0]["id"] if card_result.data else None

    for pos in accepted:
        bet_result = db.table("bets").insert({
            "user_id": user_id,
            "card_id": card_id,
            "date": today,
            "sport": pos.get("sport", ""),
            "game": pos.get("game", ""),
            "bet": pos.get("bet", ""),
            "market": pos.get("market", ""),
            "odds": int(pos.get("odds", -110)),
            "book": pos.get("book", "DraftKings"),
            "units": float(pos.get("units", 1)),
            "confidence": pos.get("confidence", "MEDIUM"),
            "result": "pending",
            "units_result": 0,
            "post_slate_tag": AGENT_BET_TAG,
            "notes": pos.get("edge_summary", ""),
        }).execute()
        bet_id = bet_result.data[0]["id"] if bet_result.data else None
        payload = {**pos, "bet_id": bet_id} if bet_id else pos

        log_episode(
            db, user_id, trigger_type="position", episode_type="position",
            title=f"Position: {pos.get('bet', '')}",
            reasoning=pos.get("edge_summary", ""),
            action_payload=payload,
        )

    sync_units_at_risk(db, user_id, today)
    from services.sheets_sync import maybe_sync_sheets
    maybe_sync_sheets(db, reason="agent-scan")

    return units_used
