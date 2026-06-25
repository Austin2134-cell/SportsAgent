"""
Daily MLB / major-league ESM card — separate pipeline from World Cup.

World Cup: services/world_cup_card.py @ 8:50 AM MT
MLB/ESM:   this module @ 9:35 AM MT (email + Supabase + sheet)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from services.mailer import send_card_email
from services.world_cup_card import email_transport_configured


def today_mt() -> str:
    tz = ZoneInfo(os.getenv("TIMEZONE", "America/Denver"))
    return datetime.now(tz).date().isoformat()


def default_recipient() -> str:
    return os.getenv(
        "ESM_CARD_USER_EMAIL",
        os.getenv("WC_CARD_USER_EMAIL", "austin.noyes21@gmail.com"),
    ).strip()


def esm_card_enabled() -> bool:
    return os.getenv("ESM_CARD_ENABLED", "true").lower() not in ("0", "false", "no")


def _esm_already_persisted(db, email: str, card_date: str) -> bool:
    from services.card_store import resolve_user_id

    user_id = resolve_user_id(db, email=email)
    if not user_id:
        return False
    row = (
        db.table("cards")
        .select("raw_card")
        .eq("user_id", user_id)
        .eq("date", card_date)
        .limit(1)
        .execute()
    )
    if not row.data:
        return False
    raw = row.data[0].get("raw_card") or {}
    esm = raw.get("esm") if isinstance(raw, dict) else None
    return isinstance(esm, dict) and bool(esm.get("official_plays"))


def run_daily_esm_card(
    *,
    target_date: Optional[str] = None,
    email: Optional[str] = None,
    send_email: bool = True,
    force: bool = False,
    print_output: bool = True,
    db=None,
) -> dict:
    """Generate MLB/major-league ESM card, email, and persist (separate from WC card)."""
    if db is None:
        from database import db as _db
        db = _db

    card_date = target_date or today_mt()
    recipient = (email or default_recipient()).strip()

    if not esm_card_enabled():
        print("[esm_runner] ESM/MLB card disabled (ESM_CARD_ENABLED=false)")
        return {"date": card_date, "skipped": True, "reason": "disabled"}

    if not force and _esm_already_persisted(db, recipient, card_date):
        print(f"[esm_runner] MLB/ESM card already exists for {card_date} ({recipient}) — skipping")
        return {"date": card_date, "skipped": True}

    from workers.market_poller import run_splits_sync

    splits_result = run_splits_sync(db)
    print(f"[esm_runner] Action Network splits: {splits_result}")

    from services.card_store import resolve_user_id

    user_id = resolve_user_id(db, email=recipient)
    if not user_id:
        print(f"[esm_runner] No profile for {recipient} — cannot generate MLB card")
        return {"date": card_date, "error": "no_profile"}

    prefs_result = db.table("preferences").select("*").eq("user_id", user_id).execute()
    prefs = prefs_result.data[0] if prefs_result.data else {"sports": ["MLB"], "max_plays": 5}

    from services.agent_runner import run_card_for_user

    print(f"[esm_runner] Generating MLB/ESM card for {card_date} ({recipient})...")
    card = run_card_for_user(
        user_id,
        prefs,
        target_date=card_date,
        force=force,
    )
    if not card:
        print("[esm_runner] No MLB/ESM card returned")
        return {"date": card_date, "error": "empty_card"}

    if print_output:
        _print_card(card)

    if send_email:
        if not email_transport_configured():
            print("[esm_runner] WARNING: No email transport — MLB card not emailed")
        else:
            print(f"[esm_runner] Sending MLB card to {recipient}...")
            ok = send_card_email(
                card,
                recipient,
                card_date,
                subject_label="MLB Daily Card",
                header_label="MLB DAILY CARD",
            )
            if ok:
                print(f"[esm_runner] MLB card delivered to {recipient}")
            else:
                print(f"[esm_runner] MLB card email failed — see /tmp/esm_card_{card_date}.html")

    from services.sheets_sync import maybe_sync_sheets

    maybe_sync_sheets(db, reason="daily_esm_card")

    return card


def _print_card(card: dict) -> None:
    grade = card.get("slate_grade", "?")
    print(f"\n{'='*60}")
    print(f"  ESM MLB CARD — {card.get('date', '')}")
    print(f"  Slate Grade: {grade}  |  {card.get('slate_grade_note', '')}")
    print(f"{'='*60}")
    for play in card.get("official_plays") or []:
        odds = play.get("odds", 0)
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        print(
            f"\n  [{play.get('confidence', '?')}] {play.get('game', '')}\n"
            f"  ▶ {play.get('bet', '')}  {odds_str}  {play.get('units', 2)}u  ({play.get('book', '')})"
        )
        if play.get("edge_summary"):
            print(f"  {play.get('edge_summary')}")
    if card.get("leans"):
        print("\n  LEANS:")
        for lean in card.get("leans") or []:
            print(f"    {lean.get('sport', '')} — {lean.get('bet', '')}")
    print(f"\n{'='*60}\n")
