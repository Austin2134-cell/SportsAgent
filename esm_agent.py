"""
ESM Betting Agent — main orchestration.

Flow:
  1. Build market snapshot (odds + ESPN context)
  2. Send to Claude with full ESM system prompt
  3. Parse JSON response → official plays (max 5)
  4. Log plays to tracker CSV
  5. Write formatted card to output/
  6. Print ESM-styled card to terminal
  7. Generate social content (tweet, text-message card, short card)
"""

import json
import os
import re
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

import anthropic

from config import (
    ANTHROPIC_API_KEY,
    ODDS_API_KEY,
    MAX_WAGERS_PER_DAY,
    UNIT_SIZE_DOLLARS,
    TIMEZONE,
    OUTPUT_DIR,
)
from system_prompt import ESM_SYSTEM_PROMPT
from odds_client import OddsClient
from stats_client import StatsClient
from grader import run_grader
from notifier import send_daily_card
from social_content import generate_social_content
from tracker import (
    log_plays,
    get_daily_record,
    get_all_time_record,
    format_record_string,
    format_dollar_summary,
    wagers_placed_today,
)

MDT = ZoneInfo(TIMEZONE)
MODEL = "claude-sonnet-4-6"


def run_daily_card(target_date: str = None, dry_run: bool = False) -> dict:
    """
    Main entry point for a daily agent run.
    dry_run=True: fetch data and print the card, but do NOT log plays to CSV.
    Returns the parsed card dict.
    """
    today = target_date or date.today().isoformat()
    now_mdt = datetime.now(MDT).strftime("%I:%M %p MDT")

    print(f"\n{'━'*60}")
    print(f"  ESM BETTING AGENT  |  {today}  |  {now_mdt}")
    print(f"{'━'*60}\n")

    # --- Step 0: Grade yesterday's pending bets ---
    print("[ESM] Checking for pending bets to grade...")
    run_grader(verbose=True)

    # --- Guard: daily wager cap ---
    if not dry_run:
        already_placed = wagers_placed_today(today)
        if already_placed >= MAX_WAGERS_PER_DAY:
            print(f"[ESM] Daily cap reached ({already_placed}/{MAX_WAGERS_PER_DAY}). No new plays.")
            return {}

    # --- Step 1: Gather market data ---
    print("[ESM] Fetching market data...")
    market_snapshot = _build_market_snapshot(today)

    print("[ESM] Fetching ESPN context...")
    espn_context = _build_espn_context(market_snapshot, today)

    # --- Step 2: Assemble user message ---
    user_message = _build_user_message(today, market_snapshot, espn_context)

    # --- Step 3: Call Claude ---
    print("[ESM] Running analysis...\n")
    card = _call_claude(user_message)

    if not card:
        print("[ESM] Agent returned no card. Exiting.")
        return {}

    # --- Step 4: Enforce wager cap + sport diversity ---
    official_plays = card.get("official_plays", [])
    official_plays = _enforce_sport_diversity(official_plays, market_snapshot, MAX_WAGERS_PER_DAY)
    if len(official_plays) > MAX_WAGERS_PER_DAY:
        official_plays = official_plays[:MAX_WAGERS_PER_DAY]
    card["official_plays"] = official_plays

    # --- Step 5: Log plays ---
    if not dry_run and official_plays:
        log_plays(official_plays, run_date=today)
        print(f"[ESM] {len(official_plays)} play(s) logged to tracker.\n")

    # --- Step 6: Render and save card ---
    card_text = _render_card(card, today)
    _save_card(card_text, today)
    print(card_text)

    # --- Step 7: Print record summary ---
    _print_record_summary(today)

    # --- Step 8: Generate social content ---
    print("[ESM] Generating social content...\n")
    social = generate_social_content(card, today)

    # --- Step 9: Send to mobile ---
    send_daily_card(card, social or {}, today)

    # --- Step 10: Sync to Google Sheets (if configured) ---
    _sync_sheets_if_configured()

    return card


def _sync_sheets_if_configured():
    """Push latest bets.csv to Google Sheet if service account is present."""
    from pathlib import Path
    sa_file = Path(__file__).parent / "google_service_account.json"
    if not sa_file.exists():
        return  # not configured yet, skip silently
    try:
        from sync_to_sheets import sync
        print("[ESM] Syncing to Google Sheets...")
        url = sync()
        print(f"[ESM] Sheet updated: {url}")
    except Exception as e:
        print(f"[ESM] Google Sheets sync failed (non-fatal): {e}")


def _build_market_snapshot(today: str) -> dict:
    if not ODDS_API_KEY:
        print("[ESM] WARNING: No ODDS_API_KEY set. Running with empty market data.")
        return {"date": today, "sports": {}}

    client = OddsClient()
    snapshot = client.build_market_snapshot(target_date=today)

    sports_with_games = [k for k, v in snapshot.get("sports", {}).items() if v.get("games")]
    total_games = sum(len(v["games"]) for v in snapshot.get("sports", {}).values())
    remaining = snapshot.get("requests_remaining_after", "?")

    print(f"[ESM] Found {total_games} game(s) across {sports_with_games}")
    print(f"[ESM] Odds API requests remaining: {remaining}\n")

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
            print(f"[ESM] ESPN fetch failed for {sport_key}: {e}")

    return context


def _build_user_message(today: str, market_snapshot: dict, espn_context: dict) -> str:
    all_time = get_all_time_record()
    record_str = format_record_string(all_time) if all_time["total_settled"] > 0 else "No prior record."
    dollar_str = format_dollar_summary(all_time) if all_time["total_settled"] > 0 else ""

    parts = [
        f"DATE: {today}",
        f"UNIT SIZE: ${UNIT_SIZE_DOLLARS:.0f} per unit",
        f"MAX OFFICIAL PLAYS: {MAX_WAGERS_PER_DAY}",
        f"RUNNING RECORD: {record_str}",
    ]
    if dollar_str:
        parts.append(f"DOLLAR P&L: {dollar_str}")

    # --- Performance intelligence (adaptive learning) ---
    try:
        from performance_tracker import get_performance_report
        perf_report = get_performance_report()
        parts.append(perf_report)
    except Exception as e:
        print(f"[ESM] Performance tracker error (non-fatal): {e}")

    # --- Sport distribution mandate ---
    parts.append(_build_sport_mandate(market_snapshot))

    parts.append("\n--- LIVE MARKET DATA ---")
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
        "\nApply the full ESM framework to this data, incorporating the performance intelligence above. "
        "Honor all AUTO-SKIP rules, BOOST SIGNAL markets, and the SPORT DISTRIBUTION MANDATE above. "
        "Return your daily card as a single valid JSON object matching the required schema. "
        "No markdown, no commentary outside the JSON."
    )

    return "\n".join(parts)


def _summarize_market(snapshot: dict) -> str:
    """Compress market snapshot to a tight human-readable format to stay under token limits."""
    lines = []
    for sport, sport_data in snapshot.get("sports", {}).items():
        sport_label = sport.replace("_", " ").upper()
        lines.append(f"\n[{sport_label}]")
        for game in sport_data.get("games", []):
            away = game["away_team"]
            home = game["home_team"]
            time = game.get("commence_time", "")[:16].replace("T", " ")
            gl = game.get("lines", {})
            aml = gl.get("away_ml", "N/A")
            hml = gl.get("home_ml", "N/A")
            spread = gl.get("home_spread", "N/A")
            total = gl.get("total", "N/A")
            over_odds = gl.get("over_odds", "")
            under_odds = gl.get("under_odds", "")

            lines.append(
                f"  {away} @ {home} | {time} UTC"
                f" | ML: {away} {aml} / {home} {hml}"
                f" | Spread: {home} {spread}"
                f" | Total: {total} (O{over_odds}/U{under_odds})"
            )

            # Props — show best Over and Under per player, max 8 players per market
            props = game.get("props", {})
            for market, players in props.items():
                market_label = market.replace("player_", "").replace("_", " ").title()
                lines.append(f"    {market_label}:")
                count = 0
                for player, directions in players.items():
                    if count >= 8:
                        break
                    over = directions.get("Over", {})
                    under = directions.get("Under", {})
                    line_val = over.get("line") or under.get("line", "?")
                    o_odds = over.get("best_odds", "")
                    u_odds = under.get("best_odds", "")
                    book = over.get("best_book") or under.get("best_book", "")
                    lines.append(
                        f"      {player}: {line_val} | O{o_odds} / U{u_odds} ({book})"
                    )
                    count += 1

    return "\n".join(lines)


def _summarize_espn(espn_context: dict) -> str:
    """Compress ESPN context to brief injury and team lines."""
    lines = []
    for sport, data in espn_context.items():
        injuries = data.get("injuries", [])
        if injuries:
            lines.append(f"\n{sport.upper()} INJURIES:")
            for inj in injuries[:20]:  # cap at 20 to save tokens
                lines.append(
                    f"  {inj['team']} — {inj['player']} ({inj['status']}): {inj['detail']}"
                )
        sb = data.get("scoreboard", [])
        if sb:
            lines.append(f"\n{sport.upper()} TEAMS/RECORDS:")
            for g in sb[:10]:
                lines.append(
                    f"  {g.get('away_team','?')} ({g.get('away_record','?')}) @ "
                    f"{g.get('home_team','?')} ({g.get('home_record','?')})"
                )
    return "\n".join(lines) if lines else "No context available."


def _call_claude(user_message: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=ESM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as e:
        print(f"[ESM] Claude API error: {e}")
        return {}

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to salvage a truncated response by closing open structures
        salvaged = _repair_json(raw)
        if salvaged:
            print("[ESM] JSON was truncated — salvaged partial card.")
            return salvaged
        print(f"[ESM] Failed to parse Claude response as JSON.")
        print(f"[ESM] Raw response (first 500 chars):\n{raw[:500]}")
        return {}


def _repair_json(raw: str) -> dict:
    """Try to parse a truncated JSON response by trimming to the last complete play."""
    # Find the last complete object boundary inside official_plays
    try:
        # Trim to last } that closes a play object, then close the outer structure
        last_close = raw.rfind("},\n    {")
        if last_close == -1:
            last_close = raw.rfind("}\n  ]")
        if last_close == -1:
            return {}
        trimmed = raw[:last_close + 1] + "\n  ],\n  \"leans\": [],\n  \"quick_reads\": [\"Card was truncated — see official plays above.\"],\n  \"pass_notes\": [],\n  \"running_record\": {\"provided\": false, \"summary\": \"\"}\n}"
        return json.loads(trimmed)
    except Exception:
        return {}


def _render_card(card: dict, today: str) -> str:
    plays = card.get("official_plays", [])
    leans = card.get("leans", [])
    quick_reads = card.get("quick_reads", [])
    pass_notes = card.get("pass_notes", [])
    slate_grade = card.get("slate_grade", "?")
    slate_note = card.get("slate_grade_note", "")

    lines = [
        f"{'━'*60}",
        f"  ESM DAILY CARD  |  {today}  |  SLATE: {slate_grade}",
        f"  {slate_note}",
        f"{'━'*60}",
    ]

    # --- Official Plays ---
    if plays:
        lines.append(f"\n  OFFICIAL PLAYS  ({len(plays)}/{MAX_WAGERS_PER_DAY} max)")
        lines.append("  " + "─"*56)
        for i, play in enumerate(plays, 1):
            conf = play.get("confidence", "")
            conf_icon = {"HIGH": "▲", "MEDIUM": "●", "LEAN": "▽", "FLYER": "◆"}.get(conf, "●")
            odds = play.get("odds", "")
            odds_str = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
            last_play = play.get("last_playable_number", "")
            last_str = f"+{last_play}" if isinstance(last_play, int) and last_play > 0 else str(last_play)

            lines.append(f"\n  {i}. [{play.get('sport','')}] {play.get('game','')}")
            lines.append(f"     {play.get('game_time_mdt','')}")
            lines.append(f"     BET:    {play.get('bet','')}")
            lines.append(f"     ODDS:   {odds_str}  ({play.get('book','DraftKings')})")
            lines.append(f"     UNITS:  {play.get('units', 2)}u  |  CONFIDENCE: {conf_icon} {conf}")
            lines.append(f"     EDGE:   {play.get('edge_summary','')}")

            factors = play.get("key_factors", [])
            if factors:
                lines.append(f"     WHY:    " + " | ".join(factors))

            lines.append(f"     RISK:   {play.get('main_risk','')}")
            if last_play:
                lines.append(f"     LAST PLAYABLE: {last_str}")

            corr = play.get("correlation_note", "none")
            if corr and corr.lower() != "none":
                lines.append(f"     ⚠ CORR: {corr}")
    else:
        lines.append("\n  No official plays today.")

    # --- Leans ---
    if leans:
        lines.append(f"\n{'─'*60}")
        lines.append("  LEANS  (model tracking — not official card exposure)")
        lines.append("  " + "─"*56)
        for lean in leans:
            odds = lean.get("odds", "")
            odds_str = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
            lines.append(
                f"  • [{lean.get('sport','')}] {lean.get('bet','')}  "
                f"{odds_str}  {lean.get('units',1)}u  —  {lean.get('note','')}"
            )

    # --- Quick Reads ---
    if quick_reads:
        lines.append(f"\n{'─'*60}")
        lines.append("  QUICK READS")
        lines.append("  " + "─"*56)
        for qr in quick_reads:
            lines.append(f"  • {qr}")

    # --- Pass Notes ---
    if pass_notes:
        lines.append(f"\n{'─'*60}")
        lines.append("  PASSES")
        for pn in pass_notes:
            lines.append(f"  ✗ {pn}")

    lines.append(f"\n{'━'*60}\n")
    return "\n".join(lines)


def _save_card(card_text: str, today: str) -> None:
    path = os.path.join(OUTPUT_DIR, f"{today}_card.txt")
    with open(path, "w") as f:
        f.write(card_text)
    print(f"[ESM] Card saved → {path}")


def _print_record_summary(today: str) -> None:
    daily = get_daily_record(today)
    all_time = get_all_time_record()

    print(f"\n{'─'*60}")
    print(f"  TODAY  | {format_record_string(daily)}")
    print(f"  ALL-TIME | {format_record_string(all_time)}")
    print(f"  {format_dollar_summary(all_time)}")
    print(f"{'─'*60}\n")


SPORT_DISPLAY = {
    "basketball_nba":       "NBA",
    "baseball_mlb":         "MLB",
    "icehockey_nhl":        "NHL",
    "americanfootball_nfl": "NFL",
}

# Sports that qualify for the mandate (must have games + props today)
MANDATE_SPORTS = {"basketball_nba", "baseball_mlb", "icehockey_nhl"}


def _active_sports_with_props(market_snapshot: dict) -> list[str]:
    """Return sport keys that have at least 1 game with prop data today."""
    active = []
    for sport, sport_data in market_snapshot.get("sports", {}).items():
        if sport not in MANDATE_SPORTS:
            continue
        for game in sport_data.get("games", []):
            if game.get("props"):
                active.append(sport)
                break
    return active


def _build_sport_mandate(market_snapshot: dict) -> str:
    """Build the sport distribution mandate injected into the user message."""
    active = _active_sports_with_props(market_snapshot)
    if not active:
        return ""

    labels = [SPORT_DISPLAY.get(s, s) for s in active]
    multi = len(active) > 1

    lines = ["\n--- SPORT DISTRIBUTION MANDATE ---"]
    lines.append(f"Sports with prop markets available today: {', '.join(labels)}")

    if multi:
        lines.append(f"REQUIRED: Include at least 1 official play from EACH of: {', '.join(labels)}")
        lines.append("Hard cap: maximum 3 plays from any single sport.")
        lines.append("Do NOT fill the card with only MLB plays if NBA or NHL props are available.")
        if "basketball_nba" in active:
            lines.append("NBA PLAYOFF NOTE: Role certainty is highest of any sport — prioritize NBA when quality plays exist.")
        if "icehockey_nhl" in active:
            lines.append("NHL PLAYOFF NOTE: Shot-on-goal props are the most consistent repeatable prop in sports — prioritize SOG for top-line forwards.")
    else:
        lines.append(f"Only {labels[0]} has prop markets today — single-sport card is acceptable.")

    return "\n".join(lines)


def _enforce_sport_diversity(
    plays: list[dict],
    market_snapshot: dict,
    max_plays: int
) -> list[dict]:
    """
    Post-generation enforcement: if all plays are from one sport and other
    sports have props available, flag a warning. Returns plays as-is
    (Claude already had the mandate — this is for logging/visibility only).
    """
    if not plays:
        return plays

    active_sports = _active_sports_with_props(market_snapshot)
    if len(active_sports) <= 1:
        return plays

    sport_counts = {}
    for play in plays:
        sport = play.get("sport", "unknown")
        sport_counts[sport] = sport_counts.get(sport, 0) + 1

    total_sports_represented = len(sport_counts)
    dominant_sport = max(sport_counts, key=sport_counts.get)
    dominant_count = sport_counts[dominant_sport]

    if total_sports_represented == 1 and len(active_sports) > 1:
        print(f"[ESM] ⚠️  Diversity warning: all {len(plays)} plays are {dominant_sport}. "
              f"Sports available today: {active_sports}. "
              f"Check system prompt — mandate may not have been honored.")
    else:
        sport_summary = ", ".join(f"{v} {k}" for k, v in sport_counts.items())
        print(f"[ESM] Sport distribution: {sport_summary}")

    # Hard cap: trim if any sport exceeds 3
    MAX_PER_SPORT = 3
    trimmed = []
    per_sport = {}
    for play in plays:
        sport = play.get("sport", "unknown")
        if per_sport.get(sport, 0) < MAX_PER_SPORT:
            trimmed.append(play)
            per_sport[sport] = per_sport.get(sport, 0) + 1

    if len(trimmed) < len(plays):
        print(f"[ESM] Trimmed {len(plays) - len(trimmed)} play(s) to enforce 3-per-sport cap.")

    return trimmed[:max_plays]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ESM Betting Agent")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Analyze but do not log plays")
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("[ESM] ERROR: ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    run_daily_card(target_date=args.date, dry_run=args.dry_run)
