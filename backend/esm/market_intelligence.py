"""
Market intelligence layer — line movement, steam, and betting-split signals.

Phase 1 (live now): derive signals from stored market_snapshots (opening vs current,
steam moves, cross-book disagreement when multi-book lines are present).

Phase 2 (optional API): public bet %, money %, sharp flags from Action Network /
SportsDataIO / OddsJam — stored in market_splits table when configured.

Edge model order (injected into prompts):
  1. Fundamentals / projection (ESPN, role, matchup)
  2. Market intelligence (movement, steam, splits when available)
  3. Price → implied probability (input only — not the edge itself)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

STEAM_ODDS_THRESHOLD = int(os.getenv("MARKET_STEAM_ODDS_CENTS", "15"))
STEAM_TOTAL_THRESHOLD = float(os.getenv("MARKET_STEAM_TOTAL_POINTS", "0.5"))
LOOKBACK_HOURS = int(os.getenv("MARKET_INTEL_LOOKBACK_HOURS", "48"))


def _parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _american_implied(odds: int) -> float:
    o = int(odds)
    if o > 0:
        return 100 / (o + 100)
    return abs(o) / (abs(o) + 100)


def _odds_improved_for_bettors(open_odds: int, current_odds: int) -> bool:
    """True if current line is a better price for bettors on this side than open."""
    return int(current_odds) > int(open_odds)


def _find_game_history(
    db,
    sport_key: str,
    event_id: str,
    hours_back: int = LOOKBACK_HOURS,
) -> list[dict]:
    """Pull per-game line history from market_snapshots rows in the lookback window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    result = (
        db.table("market_snapshots")
        .select("snapshot, captured_at")
        .eq("sport_key", sport_key)
        .gte("captured_at", cutoff.isoformat())
        .order("captured_at")
        .execute()
    )
    history: list[dict] = []
    for row in result.data or []:
        snap = row.get("snapshot") or {}
        captured = row.get("captured_at")
        for game in snap.get("games", []):
            if game.get("event_id") == event_id:
                history.append({
                    "captured_at": captured,
                    "lines": dict(game.get("lines") or {}),
                })
    return history


def _load_external_splits(db, sport_key: str, event_id: str) -> dict:
    """Latest public/money % from market_splits if Phase 2 API has populated it."""
    try:
        result = (
            db.table("market_splits")
            .select("*")
            .eq("sport_key", sport_key)
            .eq("event_id", event_id)
            .order("captured_at", desc=True)
            .limit(20)
            .execute()
        )
    except Exception:
        return {}
    if not result.data:
        return {}

    by_market: dict[str, dict] = {}
    for row in result.data:
        market = row.get("market") or "h2h_home"
        if market not in by_market:
            by_market[market] = row
    return by_market


def analyze_game_lines(
    history: list[dict],
    home_team: str,
    away_team: str,
    current_lines: dict,
    external_splits: dict | None = None,
) -> dict:
    """Build intelligence flags for one game."""
    intel: dict[str, Any] = {
        "home_team": home_team,
        "away_team": away_team,
        "opening_lines": None,
        "opening_captured_at": None,
        "current_lines": current_lines,
        "flags": [],
        "line_movement_summary": [],
        "steam_side": None,
        "reverse_line_flag": False,
        "big_money_flag": False,
        "sharp_money_flag": False,
        "public_bet_pct_home": None,
        "public_bet_pct_away": None,
        "public_money_pct_home": None,
        "public_money_pct_away": None,
        "splits_source": None,
        "data_quality": "snapshot_only",
    }

    if not history:
        intel["flags"].append("no_opening_history")
        return intel

    open_row = history[0]
    open_lines = open_row["lines"]
    intel["opening_lines"] = open_lines
    intel["opening_captured_at"] = open_row["captured_at"]

    cur = current_lines or {}
    op = open_lines or {}

    # ML movement
    for side, key, team in [("home", "home_ml", home_team), ("away", "away_ml", away_team)]:
        o, c = op.get(key), cur.get(key)
        if o is None or c is None:
            continue
        delta = int(c) - int(o)
        if abs(delta) >= STEAM_ODDS_THRESHOLD:
            intel["flags"].append(f"steam_ml_{side}")
            intel["steam_side"] = team
            intel["line_movement_summary"].append(
                f"{team} ML: {o} → {c} ({delta:+d} cents)"
            )
        elif delta != 0:
            intel["line_movement_summary"].append(
                f"{team} ML: {o} → {c} ({delta:+d})"
            )

    # Total movement
    o_total, c_total = op.get("total"), cur.get("total")
    if o_total is not None and c_total is not None:
        t_delta = float(c_total) - float(o_total)
        if abs(t_delta) >= STEAM_TOTAL_THRESHOLD:
            intel["flags"].append("steam_total")
            intel["line_movement_summary"].append(
                f"Total: {o_total} → {c_total} ({t_delta:+.1f})"
            )
        elif t_delta != 0:
            intel["line_movement_summary"].append(
                f"Total: {o_total} → {c_total} ({t_delta:+.1f})"
            )

    # Under odds movement (juice on total)
    o_u, c_u = op.get("under_odds"), cur.get("under_odds")
    if o_u is not None and c_u is not None and abs(int(c_u) - int(o_u)) >= STEAM_ODDS_THRESHOLD:
        intel["flags"].append("steam_under_juice")

    o_o, c_o = op.get("over_odds"), cur.get("over_odds")
    if o_o is not None and c_o is not None and abs(int(c_o) - int(o_o)) >= STEAM_ODDS_THRESHOLD:
        intel["flags"].append("steam_over_juice")

    # External splits (Phase 2)
    if external_splits:
        intel["data_quality"] = "snapshot_plus_splits"
        h_split = external_splits.get("h2h_home") or external_splits.get("moneyline_home")
        a_split = external_splits.get("h2h_away") or external_splits.get("moneyline_away")
        if h_split:
            intel["public_bet_pct_home"] = h_split.get("public_bet_pct")
            intel["public_money_pct_home"] = h_split.get("public_money_pct")
            intel["splits_source"] = h_split.get("source")
            if h_split.get("sharp_indicator") in ("sharp", "big_money", "steam"):
                intel["sharp_money_flag"] = True
            if h_split.get("sharp_indicator") == "big_money":
                intel["big_money_flag"] = True
        if a_split:
            intel["public_bet_pct_away"] = a_split.get("public_bet_pct")
            intel["public_money_pct_away"] = a_split.get("public_money_pct")

        # Reverse line: public heavy on side but line moved away from that side
        pub_h = intel.get("public_bet_pct_home")
        pub_a = intel.get("public_bet_pct_away")
        h_o, h_c = op.get("home_ml"), cur.get("home_ml")
        a_o, a_c = op.get("away_ml"), cur.get("away_ml")
        if pub_h and pub_h >= 65 and h_o and h_c and _odds_improved_for_bettors(h_o, h_c):
            intel["reverse_line_flag"] = True
            intel["flags"].append("reverse_line_home")
        if pub_a and pub_a >= 65 and a_o and a_c and _odds_improved_for_bettors(a_o, a_c):
            intel["reverse_line_flag"] = True
            intel["flags"].append("reverse_line_away")

    if not intel["line_movement_summary"]:
        intel["line_movement_summary"].append("Lines stable since open")

    return intel


def build_market_intelligence(
    db,
    snapshot: dict,
    sport_keys: list[str] | None = None,
) -> dict:
    """
    Analyze all games in snapshot. Returns {sport_key: {event_id: intel_dict}}.
    """
    sports = snapshot.get("sports") or {}
    keys = sport_keys or list(sports.keys())
    out: dict[str, dict[str, dict]] = {}

    for sport_key in keys:
        sport_data = sports.get(sport_key) or {}
        games = sport_data.get("games") or []
        sport_intel: dict[str, dict] = {}

        for game in games:
            eid = game.get("event_id")
            if not eid:
                continue
            history = _find_game_history(db, sport_key, eid)
            splits = _load_external_splits(db, sport_key, eid)
            intel = analyze_game_lines(
                history,
                game.get("home_team", ""),
                game.get("away_team", ""),
                game.get("lines") or {},
                external_splits=splits,
            )
            sport_intel[eid] = intel

        if sport_intel:
            out[sport_key] = sport_intel

    return out


def format_intelligence_for_prompt(intelligence: dict) -> str:
    """Human-readable block for Claude user message."""
    if not intelligence:
        return "No line history available (first snapshot or DB empty)."

    lines = [
        "MARKET INTELLIGENCE (line movement + splits when available)",
        "Use as secondary confirmation — fundamentals drive true_prob; price drives implied_prob only.",
        "Flags: steam = material move since open; reverse_line = public heavy but line moved away.",
        "",
    ]

    for sport_key, games in intelligence.items():
        label = sport_key.replace("_", " ").upper()
        lines.append(f"[{label}]")
        for eid, intel in games.items():
            away, home = intel.get("away_team"), intel.get("home_team")
            lines.append(f"  {away} vs {home}")
            if intel.get("opening_captured_at"):
                lines.append(f"    Open snapshot: {intel['opening_captured_at']}")
            for mv in intel.get("line_movement_summary") or []:
                lines.append(f"    Movement: {mv}")
            flags = intel.get("flags") or []
            if flags:
                lines.append(f"    Flags: {', '.join(flags)}")
            if intel.get("steam_side"):
                lines.append(f"    Steam toward: {intel['steam_side']}")
            if intel.get("reverse_line_flag"):
                lines.append("    ⚠ Reverse line movement detected (public vs price)")
            pub_h, mon_h = intel.get("public_bet_pct_home"), intel.get("public_money_pct_home")
            pub_a, mon_a = intel.get("public_bet_pct_away"), intel.get("public_money_pct_away")
            if pub_h is not None or pub_a is not None:
                lines.append(
                    f"    Public bets: home {pub_h}% / away {pub_a}%"
                    f" | Money: home {mon_h}% / away {mon_a}%"
                    f" (source: {intel.get('splits_source')})"
                )
            if intel.get("sharp_money_flag"):
                lines.append("    Sharp/big-money signal on recorded side")
            lines.append(f"    Data: {intel.get('data_quality')}")
        lines.append("")

    return "\n".join(lines)


def attach_intelligence_to_snapshot(snapshot: dict, intelligence: dict) -> dict:
    """Embed intel dict on each game for downstream UI / validation."""
    sports = snapshot.get("sports") or {}
    for sport_key, games_intel in intelligence.items():
        sport_data = sports.get(sport_key) or {}
        for game in sport_data.get("games") or []:
            eid = game.get("event_id")
            if eid and eid in games_intel:
                game["market_intelligence"] = games_intel[eid]
    return snapshot


def sharp_action_label(intel: dict) -> str:
    """Short label for dashboard sharp_action field."""
    if not intel:
        return ""
    parts = []
    if intel.get("steam_side"):
        parts.append(f"Steam: {intel['steam_side']}")
    if intel.get("reverse_line_flag"):
        parts.append("Reverse line")
    if intel.get("sharp_money_flag"):
        parts.append("Sharp money")
    if intel.get("big_money_flag"):
        parts.append("Big money")
    flags = intel.get("flags") or []
    if "steam_total" in flags:
        parts.append("Total steam")
    if "steam_under_juice" in flags:
        parts.append("Under juice steamed")
    if "steam_over_juice" in flags:
        parts.append("Over juice steamed")
    return " · ".join(parts) if parts else ""


def line_movement_label(intel: dict) -> str:
    if not intel:
        return ""
    return "; ".join(intel.get("line_movement_summary") or [])


def enrich_card_with_market_signals(card: dict, snapshot: dict) -> dict:
    """Attach line_movement / sharp_action to each play from embedded game intel."""
    sports = snapshot.get("sports") or {}
    intel_by_matchup: dict[tuple[str, str], dict] = {}
    for sport_data in sports.values():
        for game in sport_data.get("games") or []:
            intel = game.get("market_intelligence")
            if intel:
                key = (
                    (intel.get("away_team") or "").lower(),
                    (intel.get("home_team") or "").lower(),
                )
                intel_by_matchup[key] = intel

    from esm.soccer_odds import parse_game_matchup

    for section in ("official_plays", "leans"):
        for play in card.get(section) or []:
            matchup = parse_game_matchup(play.get("game", ""))
            if not matchup:
                continue
            key = (matchup[0].lower(), matchup[1].lower())
            intel = intel_by_matchup.get(key)
            if not intel:
                continue
            play["line_movement"] = line_movement_label(intel)
            play["sharp_action"] = sharp_action_label(intel)
            signals = {
                "flags": intel.get("flags"),
                "steam_side": intel.get("steam_side"),
                "reverse_line": intel.get("reverse_line_flag"),
                "public_bet_pct_home": intel.get("public_bet_pct_home"),
                "public_bet_pct_away": intel.get("public_bet_pct_away"),
                "public_money_pct_home": intel.get("public_money_pct_home"),
                "public_money_pct_away": intel.get("public_money_pct_away"),
                "sharp_money_flag": intel.get("sharp_money_flag"),
                "big_money_flag": intel.get("big_money_flag"),
                "data_quality": intel.get("data_quality"),
            }
            play["market_signals"] = signals

    return card
