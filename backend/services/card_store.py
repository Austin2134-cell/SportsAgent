"""
Persist ESM cards and official plays to Supabase (cards + bets tables).

World Cup and MLB/ESM cards are stored separately in raw_card.world_cup and raw_card.esm.
Top-level plays/leans columns reflect the MLB card only (dashboard MLB section).
"""

import os
import re
from typing import Optional

from agent.unit_tracker import AGENT_BET_TAG, ESM_BET_TAG, WC_BET_TAG


def resolve_user_id(db, email: Optional[str] = None) -> Optional[str]:
    """Look up profiles.id by email (case-insensitive)."""
    target = (email or os.getenv("WC_CARD_USER_EMAIL", "austin.noyes21@gmail.com")).strip().lower()
    result = db.table("profiles").select("id, email").execute()
    for row in result.data or []:
        if (row.get("email") or "").strip().lower() == target:
            return row["id"]
    exact = db.table("profiles").select("id").eq("email", target).limit(1).execute()
    if exact.data:
        return exact.data[0]["id"]
    return None


def _normalize_game(game: str) -> str:
    g = re.sub(r"\s*\([^)]+\)\s*$", "", (game or "").strip())
    g = g.replace(" @ ", " vs ").replace(" at ", " vs ").replace(" v ", " vs ")
    return re.sub(r"\s+", " ", g).lower()


def _bet_key(play: dict) -> tuple:
    return (_normalize_game(play.get("game", "")), (play.get("bet") or "").strip().lower())


def _slate_note_from_raw(raw: dict) -> str:
    parts = []
    wc = raw.get("world_cup")
    esm = raw.get("esm")
    if isinstance(wc, dict) and wc.get("slate_grade_note"):
        parts.append(f"[World Cup] {wc.get('slate_grade_note', '').strip()}")
    if isinstance(esm, dict) and esm.get("slate_grade_note"):
        parts.append(f"[MLB/ESM] {esm.get('slate_grade_note', '').strip()}")
    return " | ".join(parts)


def persist_esm_card(db, user_id: str, card: dict, *, source: str = "esm") -> Optional[str]:
    """
    Write card JSON and bets rows. WC and ESM live in separate raw_card keys — not merged.
    Top-level plays/leans/quick_reads reflect MLB/ESM only; WC plays stay in raw_card.world_cup.
    """
    today = card.get("date")
    if not today:
        return None

    official_plays = card.get("official_plays", []) or []
    existing_bets = (
        db.table("bets")
        .select("game, bet")
        .eq("user_id", user_id)
        .eq("date", today)
        .execute()
    )
    seen_bets = {_bet_key(b) for b in (existing_bets.data or [])}

    existing_card = (
        db.table("cards")
        .select("*")
        .eq("user_id", user_id)
        .eq("date", today)
        .execute()
    )

    raw_card = card.copy()
    grade_note = card.get("slate_grade_note", "") or ""
    source_label = "World Cup" if source == "world_cup" else "MLB/ESM"

    if existing_card.data:
        row = existing_card.data[0]
        card_id = row["id"]
        raw = row.get("raw_card") if isinstance(row.get("raw_card"), dict) else {}
        raw = dict(raw)
        raw[source] = raw_card

        update_payload: dict = {
            "raw_card": raw,
            "slate_note": _slate_note_from_raw(raw),
        }

        if source == "esm":
            update_payload.update({
                "slate_grade": card.get("slate_grade") or row.get("slate_grade"),
                "plays": official_plays,
                "leans": card.get("leans", []),
                "quick_reads": card.get("quick_reads", []),
                "pass_notes": card.get("pass_notes", []),
            })
        elif source == "world_cup":
            wc = raw.get("world_cup") or {}
            if not raw.get("esm"):
                update_payload.update({
                    "slate_grade": card.get("slate_grade"),
                    "plays": official_plays,
                    "leans": card.get("leans", []),
                    "quick_reads": card.get("quick_reads", []),
                    "pass_notes": card.get("pass_notes", []),
                })
            else:
                update_payload["slate_grade"] = (
                    (raw.get("esm") or {}).get("slate_grade") or row.get("slate_grade")
                )

        db.table("cards").update(update_payload).eq("id", card_id).execute()
    else:
        insert_payload = {
            "user_id": user_id,
            "date": today,
            "slate_grade": card.get("slate_grade"),
            "slate_note": f"[{source_label}] {grade_note}".strip(),
            "plays": official_plays if source == "esm" or source == "world_cup" else [],
            "leans": card.get("leans", []),
            "quick_reads": card.get("quick_reads", []),
            "pass_notes": card.get("pass_notes", []),
            "raw_card": {source: raw_card},
        }
        card_result = db.table("cards").insert(insert_payload).execute()
        card_id = card_result.data[0]["id"] if card_result.data else None

    if not card_id:
        return None

    inserted = 0
    for play in official_plays:
        key = _bet_key(play)
        if key in seen_bets:
            continue
        prefix = "[WC] " if source == "world_cup" else ""
        bet_tag = WC_BET_TAG if source == "world_cup" else ESM_BET_TAG
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
            "post_slate_tag": bet_tag,
            "notes": f"{prefix}{play.get('edge_summary', '')}".strip(),
        }).execute()
        seen_bets.add(key)
        inserted += 1

    print(f"[card_store] Persisted {inserted} bet(s) for {user_id} on {today} ({source})")
    if inserted:
        from services.sheets_sync import maybe_sync_sheets
        maybe_sync_sheets(db, reason="new-bets")
        if source != "world_cup":
            from agent.unit_tracker import sync_units_at_risk
            sync_units_at_risk(db, user_id, today)
    return card_id
