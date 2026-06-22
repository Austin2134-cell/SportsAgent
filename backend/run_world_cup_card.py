"""
run_world_cup_card.py — standalone World Cup card generator.

Usage:
  python run_world_cup_card.py [--email recipient@example.com] [--date YYYY-MM-DD] [--no-email]

Workflow:
  1. Fetch live World Cup odds (The Odds API → SportsGameOdds fallback)
  2. Pass market data + situational context to Claude via full ESM framework
  3. Print card to console
  4. Print ready-to-post Twitter/X thread to stdout
  5. Optionally send HTML card via email

Required env vars:
  ANTHROPIC_API_KEY

Optional (for live odds — strongly recommended):
  ODDS_API_KEY     — The Odds API key
  SGO_API_KEY      — SportsGameOdds fallback key

Optional (for email delivery):
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_SMTP_USER, EMAIL_SMTP_PASS
    — OR —
  SENDGRID_API_KEY
  EMAIL_FROM (default: cards@edgebet.com)

Optional (for Supabase bet logging — same cards/bets tables as main ESM):
  SUPABASE_URL, SUPABASE_SERVICE_KEY
  WC_CARD_USER_EMAIL (default: recipient --email address)

NOTE: Without live odds (ODDS_API_KEY or SGO_API_KEY), Claude will receive no
market data and will return a pass card per ESM data integrity rules. This is
correct behavior — never fabricate lines.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

import anthropic
from esm.system_prompt import ESM_SYSTEM_PROMPT
from esm.odds_client import OddsClient
from services.mailer import send_card_email
from services.social import build_twitter_thread, format_thread_for_display

MODEL = "claude-sonnet-4-6"
WC_SPORT_KEY = "soccer_fifa_world_cup"
WC_START_DATE = date(2026, 6, 11)


def _wc_tournament_day(target_date: str) -> int:
    """Return which day of the WC tournament a given date is (Day 1 = June 11)."""
    d = datetime.strptime(target_date, "%Y-%m-%d").date()
    return max(1, (d - WC_START_DATE).days + 1)


def _build_wc_market_snapshot(target_date: str) -> dict:
    """Fetch live WC odds from API. Returns empty sports dict if no keys configured."""
    odds_key = os.getenv("ODDS_API_KEY", "")
    sgo_key = os.getenv("SGO_API_KEY", "")

    if odds_key or sgo_key:
        try:
            client = OddsClient()
            # World Cup is not on SGO free tier — always fetch from The Odds API.
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
    """Format the odds snapshot into a readable string for Claude."""
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
            # Note: DNB/Asian Handicap not always available from The Odds API h2h market
            # Claude should look for draw-no-bet pricing in the spread/Asian handicap market
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
    """Build the Claude user message for a World Cup card."""
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
        print("[wc_runner] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

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
        print(f"[wc_runner] Claude API error: {e}")
        sys.exit(1)

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[wc_runner] JSON parse error: {e}\nRaw (first 400):\n{raw[:400]}")
        sys.exit(1)


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


def main():
    parser = argparse.ArgumentParser(description="Generate ESM World Cup daily card")
    parser.add_argument("--email", default="Austin.noyes21@gmail.com",
                        help="Recipient email address (default: Austin.noyes21@gmail.com)")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Target date YYYY-MM-DD (default: today in MT)")
    parser.add_argument("--max-plays", type=int, default=5)
    parser.add_argument("--unit-size", type=float, default=50.0)
    parser.add_argument("--no-email", action="store_true",
                        help="Skip email delivery, just print to console")
    parser.add_argument("--no-persist", action="store_true",
                        help="Skip writing card and bets to Supabase")
    args = parser.parse_args()

    print(f"[wc_runner] Generating World Cup card for {args.date} "
          f"(Tournament Day {_wc_tournament_day(args.date)})...")

    snapshot = _build_wc_market_snapshot(args.date)
    user_msg = _build_wc_user_message(args.date, snapshot, args.max_plays, args.unit_size)
    card = _call_claude(user_msg)
    card["date"] = args.date

    _print_card(card)

    tweets = build_twitter_thread(card, args.date)
    print(format_thread_for_display(tweets))

    if not args.no_email:
        print(f"[wc_runner] Sending card to {args.email}...")
        success = send_card_email(card, args.email, args.date)
        if not success:
            print(f"[wc_runner] Email not sent via transport. "
                  f"HTML saved to /tmp/esm_card_{args.date}.html")
        else:
            print(f"[wc_runner] Card delivered to {args.email}")

    if not args.no_persist:
        _persist_card(card, args.email)

    return card


def _persist_card(card: dict, email: str) -> None:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("[wc_runner] SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping DB log")
        return
    try:
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


if __name__ == "__main__":
    main()
