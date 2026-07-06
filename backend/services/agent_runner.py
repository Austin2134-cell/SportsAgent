"""
agent_runner.py — per-user ESM card generation for the EdgeBet platform.
Called by main.py's APScheduler job and the /api/admin/run-card endpoint.
"""

import json
import os
from datetime import date
from zoneinfo import ZoneInfo

import anthropic

from esm.claude_config import CARD_MAX_TOKENS, MODEL, log_claude_usage
from esm.odds_client import OddsClient
from esm.stats_client import StatsClient
from esm.system_prompt import ESM_SYSTEM_PROMPT
from learning.memory import get_performance_context

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")
MDT = ZoneInfo(TIMEZONE)


def run_card_for_user(
    user_id: str,
    prefs: dict,
    target_date: str = None,
    *,
    force: bool = False,
    market_snapshot: dict | None = None,
) -> dict:
    """Generate a daily major-league ESM card (MLB/NBA/NHL/NFL — not World Cup)."""
    from database import db
    from agent.unit_tracker import get_unit_context, major_league_sport_keys, sync_units_at_risk
    from agent.sports import resolve_user_sports

    today = target_date or date.today().isoformat()
    sync_units_at_risk(db, user_id, today)
    unit_ctx = get_unit_context(db, user_id, today)
    unit_size = unit_ctx["unit_size"]

    existing = db.table("cards").select("id, raw_card").eq("user_id", user_id).eq("date", today).execute()
    if existing.data and not force:
        raw = existing.data[0].get("raw_card") or {}
        esm = raw.get("esm") if isinstance(raw, dict) else None
        if isinstance(esm, dict) and esm.get("official_plays"):
            print(f"[agent_runner] ESM card already exists for {user_id} on {today}")
            return esm
        if isinstance(raw, dict) and raw.get("esm"):
            print(f"[agent_runner] Merging ESM plays into existing card for {today}")
        elif existing.data:
            print(f"[agent_runner] Merging ESM plays into existing card for {today}")

    max_plays = int(prefs.get("max_plays", 5))
    sport_keys = major_league_sport_keys(resolve_user_sports(prefs.get("sports", ["MLB"])))
    if not sport_keys:
        print(f"[agent_runner] No major-league sports configured for {user_id} — skipping ESM card")
        return {}

    from learning.memory import get_defensive_settings
    from esm.play_validation import DEFENSIVE_MIN_EDGE_GAP_PCT, MIN_EDGE_GAP_PCT, apply_play_guards

    defensive = get_defensive_settings(db, user_id, pipeline="esm")
    if defensive["defensive"]:
        cap = defensive["max_plays"] or max_plays
        max_plays = min(max_plays, cap)
        print(
            f"[agent_runner] Defensive mode: max {max_plays} plays "
            f"({'; '.join(defensive['reasons'])})"
        )

    if market_snapshot is None:
        print(f"[agent_runner] Fetching odds — {today} (1 unit = ${unit_size:.0f})")
        market_snapshot = _build_market_snapshot(today, sport_keys=sport_keys)
    else:
        games = sum(len(v.get("games", [])) for v in market_snapshot.get("sports", {}).values())
        print(f"[agent_runner] Using supplied snapshot — {today} (1 unit = ${unit_size:.0f}, {games} games)")

    print("[agent_runner] Fetching ESPN context...")
    espn_context = _build_espn_context(market_snapshot, today)

    perf_context = get_performance_context(db, user_id, pipeline="esm")
    defensive_note = ""
    if defensive["defensive"]:
        defensive_note = (
            "\nDEFENSIVE MODE (code-enforced): Recent losses detected. "
            f"Cap at {max_plays} official plays, reduce units 0.5u, require 5%+ edge. "
            f"Reasons: {'; '.join(defensive['reasons'])}."
        )
    intelligence = None
    if db is not None:
        from esm.market_intelligence import (
            attach_intelligence_to_snapshot,
            build_market_intelligence,
        )

        sport_keys = list(market_snapshot.get("sports", {}).keys())
        intelligence = build_market_intelligence(db, market_snapshot, sport_keys)
        market_snapshot = attach_intelligence_to_snapshot(market_snapshot, intelligence)

    user_message = _build_user_message(
        today, market_snapshot, espn_context, max_plays, unit_size, perf_context,
        intelligence=intelligence, defensive_note=defensive_note,
    )

    print("[agent_runner] Running ESM analysis...")
    card = _call_claude(user_message)
    if not card:
        print(f"[agent_runner] No card returned for {user_id}")
        return {}

    from esm.market_intelligence import enrich_card_with_market_signals

    card = enrich_card_with_market_signals(card, market_snapshot)

    min_edge = (
        DEFENSIVE_MIN_EDGE_GAP_PCT if defensive["defensive"] else MIN_EDGE_GAP_PCT
    )
    card = apply_play_guards(
        card,
        blocked_markets=defensive["blocked_markets"],
        unit_reduction=defensive["unit_reduction"],
        max_plays=defensive["max_plays"],
        min_edge_gap=min_edge,
        log_prefix="[agent_runner]",
    )

    official_plays = card.get("official_plays", [])
    if len(official_plays) > max_plays:
        official_plays = official_plays[:max_plays]
        card["official_plays"] = official_plays

    card["date"] = today

    from services.card_store import persist_esm_card
    card_id = persist_esm_card(db, user_id, card, source="esm")
    if not card_id:
        print(f"[agent_runner] Failed to persist card for {user_id}")
        return {}

    print(f"[agent_runner] Card + {len(official_plays)} bets written for {user_id}")
    return card


def _build_market_snapshot(today: str, sport_keys: list[str] | None = None) -> dict:
    odds_key = os.getenv("ODDS_API_KEY", "")
    if not odds_key:
        print("[agent_runner] WARNING: No ODDS_API_KEY set.")
        return {"date": today, "sports": {}}
    client = OddsClient()
    snapshot = client.build_market_snapshot(target_date=today, sport_keys=sport_keys)
    sports_with_games = [k for k, v in snapshot.get("sports", {}).items() if v.get("games")]
    total_games = sum(len(v["games"]) for v in snapshot.get("sports", {}).values())
    print(f"[agent_runner] {total_games} game(s) across {sports_with_games}")
    return snapshot


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
            print(f"[agent_runner] ESPN error for {sport_key}: {e}")
    return context


def _build_user_message(
    today: str, market_snapshot: dict, espn_context: dict,
    max_plays: int, unit_size: float, perf_context: str = "",
    intelligence: dict | None = None,
    defensive_note: str = "",
) -> str:
    from esm.split_guidance import SPLIT_INTERPRETATION_GUIDANCE
    from esm.market_intelligence import format_intelligence_for_prompt

    parts = [
        f"DATE: {today}",
        f"UNIT SIZE: ${unit_size:.0f} per unit",
        f"MAX OFFICIAL PLAYS: {max_plays}",
    ]

    if perf_context:
        parts.append(perf_context)
    if defensive_note:
        parts.append(defensive_note)

    parts.append("\n--- LIVE MARKET DATA ---")
    if market_snapshot.get("sports"):
        parts.append(_summarize_market(market_snapshot))
    else:
        parts.append("No odds data available for today's slate.")

    if intelligence:
        parts.append("\n--- MARKET INTELLIGENCE (line movement / splits) ---")
        parts.append(format_intelligence_for_prompt(intelligence))
        parts.append(SPLIT_INTERPRETATION_GUIDANCE)

    parts.append("\n--- INJURY / TEAM CONTEXT ---")
    if espn_context:
        parts.append(_summarize_espn(espn_context))
    else:
        parts.append("No ESPN context available.")

    parts.append(
        "\nApply the full ESM framework to this data. "
        "Decision order: (1) fundamentals/projection → true_prob_pct, "
        "(2) market intelligence (steam, reverse line, splits) as confirmation or fade signal, "
        "(3) posted price → implied_prob_pct only. Never treat juice alone as edge. "
        "Populate market_signals, line_movement, and sharp_action on each play when data exists. "
        "Return your daily card as a single valid JSON object matching the required schema. "
        "No markdown, no commentary outside the JSON."
    )
    return "\n".join(parts)


def _summarize_market(snapshot: dict) -> str:
    lines = []
    for sport, sport_data in snapshot.get("sports", {}).items():
        sport_label = sport.replace("_", " ").upper()
        lines.append(f"\n[{sport_label}]")
        for game in sport_data.get("games", []):
            away = game["away_team"]
            home = game["home_team"]
            time = game.get("commence_time", "")[:16].replace("T", " ")
            gl = game.get("lines", {})
            lines.append(
                f"  {away} @ {home} | {time} UTC"
                f" | ML: {away} {gl.get('away_ml', 'N/A')} / {home} {gl.get('home_ml', 'N/A')}"
                f" | Spread: {home} {gl.get('home_spread', 'N/A')}"
                f" | Total: {gl.get('total', 'N/A')} (O{gl.get('over_odds', '')}/U{gl.get('under_odds', '')})"
            )
            props = game.get("props", {})
            for market, players in props.items():
                market_label = market.replace("player_", "").replace("_", " ").title()
                lines.append(f"    {market_label}:")
                for i, (player, directions) in enumerate(players.items()):
                    if i >= 8:
                        break
                    over = directions.get("Over", {})
                    under = directions.get("Under", {})
                    line_val = over.get("line") or under.get("line", "?")
                    lines.append(
                        f"      {player}: {line_val} | O{over.get('best_odds', '')} / U{under.get('best_odds', '')} "
                        f"({over.get('best_book') or under.get('best_book', '')})"
                    )
    return "\n".join(lines)


def _summarize_espn(espn_context: dict) -> str:
    lines = []
    for sport, data in espn_context.items():
        injuries = data.get("injuries", [])
        if injuries:
            lines.append(f"\n{sport.upper()} INJURIES:")
            for inj in injuries[:20]:
                lines.append(
                    f"  {inj['team']} — {inj['player']} ({inj['status']}): {inj['detail']}"
                )
        sb = data.get("scoreboard", [])
        if sb:
            lines.append(f"\n{sport.upper()} TEAMS/RECORDS:")
            for g in sb[:10]:
                lines.append(
                    f"  {g.get('away_team', '?')} ({g.get('away_record', '?')}) @ "
                    f"{g.get('home_team', '?')} ({g.get('home_record', '?')})"
                )
    return "\n".join(lines) if lines else "No context available."


def _call_claude(user_message: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=CARD_MAX_TOKENS,
            system=[{"type": "text", "text": ESM_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )
        log_claude_usage("esm_card", response.usage)
    except anthropic.APIError as e:
        print(f"[agent_runner] Claude API error: {e}")
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
        salvaged = _repair_json(raw)
        if salvaged:
            print("[agent_runner] JSON truncated — salvaged partial card.")
            return salvaged
        print(f"[agent_runner] Failed to parse Claude response. First 300 chars:\n{raw[:300]}")
        return {}


def _repair_json(raw: str) -> dict:
    try:
        last_close = raw.rfind("},\n    {")
        if last_close == -1:
            last_close = raw.rfind("}\n  ]")
        if last_close == -1:
            return {}
        trimmed = (
            raw[:last_close + 1]
            + '\n  ],\n  "leans": [],\n  "quick_reads": ["Card was truncated."],\n'
            + '  "pass_notes": [],\n  "running_record": {"provided": false, "summary": ""}\n}'
        )
        return json.loads(trimmed)
    except Exception:
        return {}
