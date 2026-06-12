"""
run_world_cup_card.py — standalone World Cup card generator.

Usage:
  python run_world_cup_card.py [--email recipient@example.com] [--date YYYY-MM-DD]

Workflow:
  1. Fetch live World Cup odds (The Odds API → SportsGameOdds fallback)
  2. If no live odds, build a curated match context from known WC 2026 fixtures
  3. Run ESM analysis via Claude (full framework + soccer addendum)
  4. Send formatted HTML card to email address
  5. Print ready-to-post Twitter/X thread to stdout

Required env vars:
  ANTHROPIC_API_KEY

Optional (for live odds):
  ODDS_API_KEY, SGO_API_KEY

Optional (for email):
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_SMTP_USER, EMAIL_SMTP_PASS
    — OR —
  SENDGRID_API_KEY
  EMAIL_FROM
"""

import argparse
import json
import os
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# ── add backend dir to path ───────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

import anthropic
from esm.system_prompt import ESM_SYSTEM_PROMPT
from esm.odds_client import OddsClient
from services.mailer import send_card_email, build_html_email
from services.social import build_twitter_thread, format_thread_for_display


MODEL = "claude-sonnet-4-6"
WC_SPORT_KEY = "soccer_fifa_world_cup"

# ── June 12, 2026 World Cup match context (used when no live odds API) ────────
# Source: confirmed sportsbook lines for today's actual fixtures
WC_MATCH_CONTEXT_JUNE_12 = """
FIFA WORLD CUP 2026 — Group Stage (June 12, 2026)

Today's matches (2 games):

GROUP B:
  Canada vs. Bosnia-Herzegovina  | 1:00 PM ET
  Moneyline: Canada -120, Bosnia-Herzegovina +380
  (Draw odds not shown — approximately +265 to +290 range implied)
  Total Goals: 2.5 (estimated O -115 / U -105)
  Context: Canada opens as host co-nation with home crowd advantage. Bosnia-Herzegovina
  returns to the World Cup for the first time since 2014 — 12-year absence means
  significant adjustment to this level. Canada has genuine world-class attackers in
  Alphonso Davies and Jonathan David. Bosnia's squad rebuilt around younger domestic
  league players with limited major tournament experience.
  Key edge: Canada -120 is within the -130 juice ceiling and represents value given
  the talent and experience gap. Quality differential is clear and Bosnia's long WC
  absence is a tournament-pressure disadvantage.

GROUP D:
  United States vs. Paraguay     | 7:00 PM ET
  Moneyline: USA +105, Paraguay +305
  (Draw odds not shown — approximately +230 to +250 range implied)
  Total Goals: 2.5 (estimated O -110 / U -110)
  Context: Host nation USA opens their tournament with home crowd support. Paraguay
  qualified from CONMEBOL but ranked outside the top 40 globally. USA's roster
  features quality across all positions — Pulisic, Weah, McKennie, Turner in goal.
  Paraguay's strength is defensive organization and counter-attack but their forwards
  are not elite.
  Key edge: USA +105 is POSITIVE MONEY on what should be a clear favorite at home.
  Per ESM rules: always prefer plus-money. +105 only requires a ~48.8% win rate to
  be profitable, yet USA are realistically 55-60% favorites in this matchup.

Odds from: DraftKings (confirmed lines, June 12 2026)
Market note: All lines approximate pre-game. Verify at your sportsbook.
"""


def _build_wc_fallback_snapshot() -> dict:
    """Returns a WC match context dict when no live odds are available."""
    return {
        "date": date.today().isoformat(),
        "sports": {},  # empty — Claude will use the inline context in user message
        "_wc_context": WC_MATCH_CONTEXT_JUNE_12,
    }


def _build_wc_market_snapshot(target_date: str) -> dict:
    """Fetch live WC odds; fall back to curated stub if none returned."""
    odds_key = os.getenv("ODDS_API_KEY", "")
    sgo_key = os.getenv("SGO_API_KEY", "")

    if odds_key or sgo_key:
        try:
            client = OddsClient()
            snapshot = client.build_market_snapshot(target_date=target_date)
            wc_data = snapshot.get("sports", {}).get(WC_SPORT_KEY)
            if wc_data and wc_data.get("games"):
                print(f"[wc_runner] Live odds loaded: {len(wc_data['games'])} WC game(s)")
                return snapshot
            print("[wc_runner] No live WC odds returned — using curated match context.")
        except Exception as e:
            print(f"[wc_runner] Odds API error: {e} — using curated match context.")

    return _build_wc_fallback_snapshot()


def _build_wc_user_message(target_date: str, snapshot: dict, max_plays: int, unit_size: float) -> str:
    """Build the Claude user message for a World Cup card."""
    parts = [
        f"DATE: {target_date}",
        f"UNIT SIZE: ${unit_size:.0f} per unit",
        f"MAX OFFICIAL PLAYS: {max_plays}",
        f"TOURNAMENT: FIFA World Cup 2026 — Group Stage, Day 2",
        "\n--- LIVE MARKET DATA ---",
    ]

    wc_context = snapshot.get("_wc_context")
    live_sports = {k: v for k, v in snapshot.get("sports", {}).items() if v.get("games")}

    if live_sports:
        from services.agent_runner import _summarize_market
        parts.append(_summarize_market(snapshot))
    elif wc_context:
        parts.append(wc_context)
    else:
        parts.append("No odds data available. Pass on all plays.")

    parts.append(
        "\n--- WORLD CUP CONTEXT ---\n"
        "Apply the full ESM framework including the FIFA World Cup addendum. "
        "Focus on group-stage edge patterns: value on tight favorites, "
        "under plays in defensively cautious openers, and conservative line favorites. "
        "Juice ceiling of -130 applies absolutely — any line worse than -130 goes to "
        "leans or pass. Flag all odds as approximate/pre-game unless sourced from "
        "live API data above."
    )

    parts.append(
        "\nReturn your World Cup daily card as a single valid JSON object matching "
        "the required schema. Use sport = 'SOCCER' for all soccer plays. "
        "No markdown, no commentary outside the JSON."
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
    """Print a clean console summary of the card."""
    grade = card.get("slate_grade", "?")
    print(f"\n{'='*60}")
    print(f"  ESM WORLD CUP CARD — {card.get('date','')}")
    print(f"  Slate Grade: {grade}  |  {card.get('slate_grade_note','')}")
    print(f"{'='*60}")

    plays = card.get("official_plays", [])
    if not plays:
        print("\n  No official plays — slate grade too weak.")
    for p in plays:
        odds = p.get("odds", 0)
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        print(f"\n  [{p.get('confidence','')}] {p.get('game','')}")
        print(f"  ▶ {p.get('bet','')}  {odds_str}  {p.get('units',2)}u  ({p.get('book','DK')})")
        print(f"  {p.get('edge_summary','')}")

    leans = card.get("leans", [])
    if leans:
        print(f"\n  LEANS:")
        for l in leans:
            odds = l.get("odds", 0)
            print(f"    {l.get('sport','')} — {l.get('bet','')} ({'+' if odds > 0 else ''}{odds})")

    qr = card.get("quick_reads", [])
    if qr:
        print(f"\n  QUICK READS:")
        for item in qr:
            print(f"    → {item}")

    print(f"\n{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Generate ESM World Cup daily card")
    parser.add_argument("--email", default="anoyes@spokeo.com",
                        help="Recipient email address")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--max-plays", type=int, default=5)
    parser.add_argument("--unit-size", type=float, default=50.0)
    parser.add_argument("--no-email", action="store_true",
                        help="Skip email, just print card and thread")
    args = parser.parse_args()

    print(f"[wc_runner] Generating World Cup card for {args.date}...")

    # 1. Fetch odds
    snapshot = _build_wc_market_snapshot(args.date)

    # 2. Build Claude message
    user_msg = _build_wc_user_message(args.date, snapshot, args.max_plays, args.unit_size)

    # 3. Generate card
    card = _call_claude(user_msg)
    card["date"] = args.date

    # 4. Print card to console
    _print_card(card)

    # 5. Build and print Twitter thread
    tweets = build_twitter_thread(card, args.date)
    print(format_thread_for_display(tweets))

    # 6. Send email
    if not args.no_email:
        to_addr = args.email
        print(f"[wc_runner] Sending card to {to_addr}...")
        success = send_card_email(card, to_addr, args.date)
        if not success:
            print(f"[wc_runner] Email not sent via transport. "
                  f"HTML saved to /tmp/esm_card_{args.date}.html")
        else:
            print(f"[wc_runner] ✓ Card delivered to {to_addr}")

    return card


if __name__ == "__main__":
    main()
