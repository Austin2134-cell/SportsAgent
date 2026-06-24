"""
World Cup daily card — generate, email, and persist ESM WC plays.

Scheduled on Railway via APScheduler (8:50 AM Mountain Time).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import anthropic

from esm.odds_client import OddsClient
from esm.system_prompt import ESM_SYSTEM_PROMPT
from services.mailer import send_card_email
from services.social import build_twitter_thread, format_thread_for_display

MODEL = "claude-sonnet-4-6"
WC_SPORT_KEY = "soccer_fifa_world_cup"
WC_START_DATE = date(2026, 6, 11)


def today_mt() -> str:
    tz = ZoneInfo(os.getenv("TIMEZONE", "America/Denver"))
    return datetime.now(tz).date().isoformat()


def default_recipient() -> str:
    return os.getenv("WC_CARD_USER_EMAIL", "austin.noyes21@gmail.com").strip()


def _wc_tournament_day(target_date: str) -> int:
    d = datetime.strptime(target_date, "%Y-%m-%d").date()
    return max(1, (d - WC_START_DATE).days + 1)


def _build_wc_market_snapshot(target_date: str, db=None) -> dict:
    """Prefer fresh morning cache; fall back to live TOA fetch (CLI / cache miss)."""
    if db is not None:
        try:
            from esm.snapshot_cache import get_cached_snapshot

            cached = get_cached_snapshot(db, [WC_SPORT_KEY], target_date)
            wc_data = (cached or {}).get("sports", {}).get(WC_SPORT_KEY)
            if wc_data and wc_data.get("games"):
                print(
                    f"[wc_runner] Using cached WC odds: {len(wc_data['games'])} game(s) "
                    f"(source={cached.get('source', 'cache')})"
                )
                return cached
            print("[wc_runner] Morning WC cache empty — fetching live odds...")
        except Exception as e:
            print(f"[wc_runner] Cache read error: {e} — fetching live odds...")

    odds_key = os.getenv("ODDS_API_KEY", "")
    sgo_key = os.getenv("SGO_API_KEY", "")

    if odds_key or sgo_key:
        try:
            client = OddsClient()
            snapshot = client.build_market_snapshot(
                target_date=target_date,
                sport_keys=[WC_SPORT_KEY],
                force_source="toa",
            )
            wc_data = snapshot.get("sports", {}).get(WC_SPORT_KEY)
            if wc_data and wc_data.get("games"):
                print(f"[wc_runner] Live odds loaded: {len(wc_data['games'])} WC game(s)")
                return snapshot
            print("[wc_runner] No live WC odds returned from API.")
        except Exception as e:
            print(f"[wc_runner] Odds API error: {e}")

    print("[wc_runner] No live odds available. Claude will pass per ESM data integrity rules.")
    return {"date": target_date, "sports": {}}


def _summarize_market(snapshot: dict) -> str:
    lines = []
    for sport, sport_data in snapshot.get("sports", {}).items():
        sport_label = sport.replace("_", " ").upper()
        lines.append(f"\n[{sport_label}]")
        for game in sport_data.get("games", []):
            away = game["away_team"]
            home = game["home_team"]
            time_str = game.get("commence_time", "")[:16].replace("T", " ")
            gl = game.get("lines", {})
            lines.append(
                f"  {away} vs {home} | {time_str} UTC"
                f" | ML: {away} {gl.get('away_ml', 'N/A')} / {home} {gl.get('home_ml', 'N/A')}"
                f" | Total: {gl.get('total', 'N/A')} (O{gl.get('over_odds', '')}/U{gl.get('under_odds', '')})"
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
                        f"      {player}: {line_val} | O{over.get('best_odds','')} / U{under.get('best_odds','')}"
                    )
    return "\n".join(lines)


def _build_wc_user_message(
    target_date: str,
    snapshot: dict,
    max_plays: int,
    unit_size: float,
) -> str:
    tournament_day = _wc_tournament_day(target_date)
    live_sports = {k: v for k, v in snapshot.get("sports", {}).items() if v.get("games")}

    parts = [
        f"DATE: {target_date} (Mountain Time)",
        f"UNIT SIZE: ${unit_size:.0f} per unit",
        f"MAX OFFICIAL PLAYS: {max_plays}",
        f"TOURNAMENT: FIFA World Cup 2026 — Group Stage, Day {tournament_day}",
        "\n--- LIVE MARKET DATA ---",
    ]

    if live_sports:
        parts.append(_summarize_market(snapshot))
        parts.append(
            "\nNote: The Odds API h2h market shows straight ML odds. "
            "To estimate Draw No Bet (DNB) pricing, apply 3-way vig-removal math "
            "using home ML / draw / away ML. DNB is almost always better EV — "
            "check it before recommending the straight ML."
        )
    else:
        parts.append(
            "NO LIVE ODDS DATA AVAILABLE.\n"
            "Per ESM data integrity rules: never fabricate odds, lines, or game outcomes. "
            "Return a pass card (slate_grade F, no official plays) with pass_notes "
            "explaining that no verified market data was available for this date. "
            "You may include quick_reads with general WC context if helpful."
        )

    parts.append(
        "\n--- INSTRUCTIONS ---\n"
        "Apply the full ESM framework including the FIFA World Cup section. "
        "For soccer: prioritize Draw No Bet and Under 2.5 per the market hierarchy. "
        "Juice ceiling -130 applies absolutely. "
        "Flag dead rubbers and rotation risk as automatic passes. "
        "Return a single valid JSON object matching the required schema. "
        "Use sport = 'SOCCER' for all soccer plays. "
        "No markdown, no text outside the JSON."
    )

    return "\n".join(parts)


def _call_claude(user_message: str) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    print("[wc_runner] Calling Claude ESM agent...")

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=ESM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"Claude API error: {e}") from e

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON parse error: {e}\nRaw (first 400):\n{raw[:400]}") from e


def _print_card(card: dict) -> None:
    grade = card.get("slate_grade", "?")
    print(f"\n{'='*60}")
    print(f"  ESM WORLD CUP CARD — {card.get('date','')}")
    print(f"  Slate Grade: {grade}  |  {card.get('slate_grade_note','')}")
    print(f"{'='*60}")

    plays = card.get("official_plays", [])
    if not plays:
        print("\n  No official plays.")
    for p in plays:
        odds = p.get("odds", 0)
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        implied = p.get("implied_prob_pct", "?")
        true_p = p.get("true_prob_pct", "?")
        edge = p.get("edge_gap_pct", "?")
        print(f"\n  [{p.get('confidence','')}] {p.get('game','')}")
        print(f"  ▶ {p.get('bet','')}  {odds_str}  {p.get('units',2)}u  ({p.get('book','DK')})")
        print(f"  Implied: {implied}%  |  True: {true_p}%  |  Edge: {edge}%")
        print(f"  {p.get('edge_summary','')}")

    leans = card.get("leans", [])
    if leans:
        print("\n  LEANS:")
        for lean in leans:
            odds = lean.get("odds", 0)
            print(f"    {lean.get('sport','')} — {lean.get('bet','')} ({'+' if odds > 0 else ''}{odds})")

    qr = card.get("quick_reads", [])
    if qr:
        print("\n  QUICK READS:")
        for item in qr:
            print(f"    → {item}")

    passes = card.get("pass_notes", [])
    if passes:
        print("\n  PASSES:")
        for p in passes:
            print(f"    ✗ {p}")

    print(f"\n{'='*60}\n")


def _persist_card(card: dict, email: str, db=None) -> None:
    if db is None:
        try:
            from database import db as _db
            db = _db
        except Exception:
            pass
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("[wc_runner] SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping DB log")
        return
    try:
        if db is None:
            from database import db
        from services.card_store import persist_esm_card, resolve_user_id

        user_id = resolve_user_id(db, email=email)
        if not user_id:
            print(f"[wc_runner] No Supabase profile for {email} — skipping DB log")
            return
        card_id = persist_esm_card(db, user_id, card, source="world_cup")
        if card_id:
            print(f"[wc_runner] Logged to Supabase (card_id={card_id})")
    except Exception as e:
        print(f"[wc_runner] Supabase persist failed: {e}")


def run_world_cup_card(
    *,
    target_date: Optional[str] = None,
    email: Optional[str] = None,
    send_email: bool = True,
    persist: bool = True,
    max_plays: int = 5,
    unit_size: Optional[float] = None,
    print_output: bool = True,
    db=None,
) -> dict:
    """Generate the WC card, optionally email and persist. Returns card JSON."""
    card_date = target_date or today_mt()
    recipient = (email or default_recipient()).strip()

    if unit_size is None and db is not None:
        from services.card_store import resolve_user_id
        from agent.unit_tracker import get_unit_context

        user_id = resolve_user_id(db, email=recipient)
        if user_id:
            unit_size = get_unit_context(db, user_id, card_date)["unit_size"]
    if unit_size is None:
        unit_size = 10.0  # fallback when no bankroll on file ($1k × 1%)

    print(
        f"[wc_runner] Generating World Cup card for {card_date} "
        f"(Tournament Day {_wc_tournament_day(card_date)})..."
    )

    snapshot = _build_wc_market_snapshot(card_date, db=db)
    user_msg = _build_wc_user_message(card_date, snapshot, max_plays, unit_size)
    card = _call_claude(user_msg)
    card["date"] = card_date

    if print_output:
        _print_card(card)
        tweets = build_twitter_thread(card, card_date)
        print(format_thread_for_display(tweets))

    if send_email:
        print(f"[wc_runner] Sending card to {recipient}...")
        success = send_card_email(card, recipient, card_date)
        if not success:
            print(
                f"[wc_runner] Email not sent via transport. "
                f"HTML saved to /tmp/esm_card_{card_date}.html"
            )
        else:
            print(f"[wc_runner] Card delivered to {recipient}")

    if persist:
        _persist_card(card, recipient, db=db)

    return card
