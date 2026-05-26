"""
agent_runner.py — per-user ESM card generation for the EdgeBet platform.
Called by main.py's APScheduler job and the /api/admin/run-card endpoint.
"""

import json
import os
from datetime import date
from zoneinfo import ZoneInfo

import anthropic

from esm.odds_client import OddsClient
from esm.stats_client import StatsClient
from esm.system_prompt import ESM_SYSTEM_PROMPT

TIMEZONE = os.getenv("TIMEZONE", "America/Denver")
MDT = ZoneInfo(TIMEZONE)
MODEL = "claude-sonnet-4-6"


def run_card_for_user(user_id: str, prefs: dict, target_date: str = None) -> dict:
    """Generate a daily card for one user and persist to Supabase."""
    from database import db

    today = target_date or date.today().isoformat()

    existing = db.table("cards").select("id").eq("user_id", user_id).eq("date", today).execute()
    if existing.data:
        print(f"[agent_runner] Card already exists for {user_id} on {today}")
        return {}

    max_plays = int(prefs.get("max_plays", 5))
    unit_size = float(prefs.get("unit_size", 50))

    print(f"[agent_runner] Fetching odds — {today}")
    market_snapshot = _build_market_snapshot(today)

    print("[agent_runner] Fetching ESPN context...")
    espn_context = _build_espn_context(market_snapshot, today)

    user_message = _build_user_message(today, market_snapshot, espn_context, max_plays, unit_size)

    print("[agent_runner] Running ESM analysis...")
    card = _call_claude(user_message)
    if not card:
        print(f"[agent_runner] No card returned for {user_id}")
        return {}

    official_plays = card.get("official_plays", [])
    if len(official_plays) > max_plays:
        official_plays = official_plays[:max_plays]
        card["official_plays"] = official_plays

    card_result = db.table("cards").insert({
        "user_id": user_id,
        "date": today,
        "slate_grade": card.get("slate_grade"),
        "slate_note": card.get("slate_grade_note", ""),
        "plays": card.get("official_plays", []),
        "leans": card.get("leans", []),
        "quick_reads": card.get("quick_reads", []),
        "pass_notes": card.get("pass_notes", []),
        "raw_card": card,
    }).execute()

    card_id = card_result.data[0]["id"] if card_result.data else None

    for play in official_plays:
        db.table("bets").insert({
            "user_id": user_id,
            "card_id": card_id,
            "date": today,
            "sport": play.get("sport", ""),
            "game": play.get("game", ""),
            "bet": play.get("bet", ""),
            "market": play.get("market", ""),
            "odds": int(play.get("odds", -110)),
            "book": play.get("book", "DraftKings"),
            "units": float(play.get("units", 2)),
            "confidence": play.get("confidence", "MEDIUM"),
            "result": "pending",
            "units_result": 0,
            "notes": play.get("edge_summary", ""),
        }).execute()

    print(f"[agent_runner] Card + {len(official_plays)} bets written for {user_id}")
    return card


def _build_market_snapshot(today: str) -> dict:
    odds_key = os.getenv("ODDS_API_KEY", "")
    if not odds_key:
        print("[agent_runner] WARNING: No ODDS_API_KEY set.")
        return {"date": today, "sports": {}}
    client = OddsClient()
    snapshot = client.build_market_snapshot(target_date=today)
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
    today: str, market_snapshot: dict, espn_context: dict, max_plays: int, unit_size: float
) -> str:
    parts = [
        f"DATE: {today}",
        f"UNIT SIZE: ${unit_size:.0f} per unit",
        f"MAX OFFICIAL PLAYS: {max_plays}",
        "\n--- LIVE MARKET DATA ---",
    ]
    if market_snapshot.get("sports"):
        parts.append(_summarize_market(market_snapshot))
    else:
        parts.append("No odds data available for today's slate.")

    parts.append("\n--- INJURY / TEAM CONTEXT ---")
    if espn_context:
        parts.append(_summarize_espn(espn_context))
    else:
        parts.append("No ESPN context available.")

    parts.append(
        "\nApply the full ESM framework to this data. "
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
            max_tokens=16000,
            system=ESM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
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
