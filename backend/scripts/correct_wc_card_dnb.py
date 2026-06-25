"""
Correct today's WC card: remove invalid DNB plays, sync totals to API, update DB, resend email.

Usage:
  cd backend && python scripts/correct_wc_card_dnb.py --date 2026-06-25
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Correct WC card DNB plays against posted API lines")
    parser.add_argument("--date", default=None, help="Card date YYYY-MM-DD (default: today MT)")
    parser.add_argument("--no-email", action="store_true")
    args = parser.parse_args()

    from database import db
    from esm.odds_client import OddsClient
    from esm.soccer_odds import validate_wc_official_plays
    from services.card_store import resolve_user_id
    from services.mailer import send_card_email
    from services.sheets_sync import maybe_sync_sheets
    from services.world_cup_card import default_recipient, today_mt, WC_SPORT_KEY

    card_date = args.date or today_mt()
    email = default_recipient()
    user_id = resolve_user_id(db, email=email)
    if not user_id:
        print(f"No profile for {email}")
        return 1

    row = (
        db.table("cards")
        .select("*")
        .eq("user_id", user_id)
        .eq("date", card_date)
        .limit(1)
        .execute()
    )
    if not row.data:
        print(f"No card for {card_date}")
        return 1

    card_row = row.data[0]
    raw = card_row.get("raw_card") or {}
    wc = raw.get("world_cup") if isinstance(raw, dict) else None
    if not isinstance(wc, dict):
        print("No world_cup section in raw_card")
        return 1

    # Fresh snapshot with posted DNB
    print(f"[correct_dnb] Fetching live WC odds for {card_date}...")
    client = OddsClient()
    snapshot = client.build_market_snapshot(
        target_date=card_date,
        sport_keys=[WC_SPORT_KEY],
        force_source="toa",
    )
    from esm.snapshot_cache import store_snapshot

    wc_data = snapshot.get("sports", {}).get(WC_SPORT_KEY)
    if wc_data:
        store_snapshot(db, WC_SPORT_KEY, wc_data)

    corrected = validate_wc_official_plays(dict(wc), snapshot)
    corrected["date"] = card_date
    kept_plays = corrected.get("official_plays", [])

    # Remove draw_no_bet bets for this date
    dnb_bets = (
        db.table("bets")
        .select("id, bet, game")
        .eq("user_id", user_id)
        .eq("date", card_date)
        .eq("market", "draw_no_bet")
        .execute()
    )
    for b in dnb_bets.data or []:
        print(f"[correct_dnb] Deleting invalid DNB bet: {b['game']} — {b['bet']}")
        db.table("bets").delete().eq("id", b["id"]).execute()

    # Update totals bet odds to match API where possible
    for play in kept_plays:
        if "total" not in (play.get("bet") or "").lower():
            continue
        existing = (
            db.table("bets")
            .select("id")
            .eq("user_id", user_id)
            .eq("date", card_date)
            .eq("game", play.get("game", ""))
            .ilike("bet", f"%{play.get('bet', '')[:20]}%")
            .execute()
        )
        for row in existing.data or []:
            db.table("bets").update({
                "odds": int(play.get("odds", -110)),
                "book": play.get("book", "DraftKings"),
            }).eq("id", row["id"]).execute()

    raw["world_cup"] = corrected
    note = (
        f"[World Cup] Corrected: removed invalid DNB plays (posted lines only, -130 ceiling). "
        f"{len(corrected.get('official_plays', []))} official play(s) remain."
    )
    db.table("cards").update({
        "plays": kept_plays,
        "slate_note": note,
        "pass_notes": corrected.get("pass_notes", card_row.get("pass_notes")),
        "raw_card": raw,
    }).eq("id", card_row["id"]).execute()

    print(f"[correct_dnb] Card updated: {len(kept_plays)} play(s) on card")
    for p in kept_plays:
        print(f"  • {p.get('game')}: {p.get('bet')} @ {p.get('odds')}")

    maybe_sync_sheets(db, reason="wc_dnb_correction")

    if not args.no_email:
        print(f"[correct_dnb] Sending corrected card to {email}...")
        corrected["official_plays"] = kept_plays
        ok = send_card_email(corrected, email, card_date)
        print(f"[correct_dnb] Email sent: {ok}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
