"""
Shared programmatic guards for official plays and agent positions.

Enforces edge thresholds, juice ceilings, unit sizing, weak-market blocks,
and defensive-mode caps that the ESM prompt describes but cannot guarantee alone.
"""

from __future__ import annotations

MIN_EDGE_GAP_PCT = 3.0
DEFENSIVE_MIN_EDGE_GAP_PCT = 5.0
DEFENSIVE_MAX_PLAYS = 2
DEFENSIVE_UNIT_REDUCTION = 0.5
LOSS_STREAK_THRESHOLD = 3
MLB_ESM_JUICE_CEILING = -200
WC_JUICE_CEILING = -150

# (min edge gap %, max units) — mirrors fractional Kelly tiers in system_prompt.py
EDGE_UNIT_CAPS: tuple[tuple[float, float], ...] = (
    (10.0, 3.0),
    (5.0, 2.0),
    (2.0, 1.5),
    (MIN_EDGE_GAP_PCT, 1.0),
)


def within_juice_ceiling(american_odds: int, ceiling: int) -> bool:
    """True if American odds are at or better than ceiling (e.g. -150, +120)."""
    return int(american_odds) >= ceiling


def max_units_for_edge(edge_gap_pct: float) -> float:
    """Max allowed units for a stated edge gap."""
    for threshold, cap in EDGE_UNIT_CAPS:
        if edge_gap_pct >= threshold:
            return cap
    return 0.0


def _parse_edge(play: dict) -> float | None:
    raw = play.get("edge_gap_pct")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _append_pass_notes(card: dict, notes: list[str], log_prefix: str) -> None:
    if not notes:
        return
    pass_notes = list(card.get("pass_notes") or [])
    for note in notes:
        print(f"{log_prefix} {note}")
        pass_notes.append(note)
    card["pass_notes"] = pass_notes


def apply_play_guards(
    card: dict,
    *,
    juice_ceiling: int = MLB_ESM_JUICE_CEILING,
    min_edge_gap: float = MIN_EDGE_GAP_PCT,
    blocked_markets: set[str] | None = None,
    unit_reduction: float = 0.0,
    max_plays: int | None = None,
    require_edge: bool = True,
    log_prefix: str = "[validation]",
) -> dict:
    """
    Filter official_plays: juice ceiling, minimum edge, weak markets, unit caps,
    defensive play count, and unit reduction.
    """
    plays = list(card.get("official_plays") or [])
    kept: list[dict] = []
    removed_notes: list[str] = []
    blocked = {m.lower() for m in (blocked_markets or set())}

    for play in plays:
        bet_label = play.get("bet", "")
        market = (play.get("market") or "").strip().lower()
        if market and market in blocked:
            removed_notes.append(
                f"Removed {bet_label}: market '{market}' blocked (negative ROI history)"
            )
            continue

        odds = int(play.get("odds", -110))
        if not within_juice_ceiling(odds, juice_ceiling):
            removed_notes.append(
                f"Removed {bet_label}: odds {odds} exceed juice ceiling {juice_ceiling}"
            )
            continue

        edge = _parse_edge(play)
        if require_edge and edge is None:
            removed_notes.append(
                f"Removed {bet_label}: missing edge_gap_pct (required for official plays)"
            )
            continue

        if edge is not None:
            if edge < min_edge_gap:
                removed_notes.append(
                    f"Removed {bet_label}: edge {edge}% below minimum {min_edge_gap}%"
                )
                continue
            cap = max_units_for_edge(edge)
            if cap <= 0:
                removed_notes.append(
                    f"Removed {bet_label}: edge {edge}% too thin for official play"
                )
                continue
            units = float(play.get("units", 1))
            adjusted = min(units, cap)
            if unit_reduction:
                adjusted = max(0.5, round(adjusted - unit_reduction, 1))
            play["units"] = adjusted
        elif unit_reduction:
            play["units"] = max(
                0.5, round(float(play.get("units", 1)) - unit_reduction, 1)
            )

        kept.append(play)

    if max_plays is not None and len(kept) > max_plays:
        for dropped in kept[max_plays:]:
            removed_notes.append(
                f"Removed {dropped.get('bet', '')}: defensive cap at {max_plays} plays"
            )
        kept = kept[:max_plays]

    _append_pass_notes(card, removed_notes, log_prefix)
    card["official_plays"] = kept
    return card


def apply_position_guards(
    positions: list[dict],
    *,
    juice_ceiling: int = MLB_ESM_JUICE_CEILING,
    blocked_markets: set[str] | None = None,
    unit_reduction: float = 0.0,
    max_plays: int | None = None,
) -> list[dict]:
    """Filter agent scan positions (edge_gap_pct optional)."""
    kept: list[dict] = []
    blocked = {m.lower() for m in (blocked_markets or set())}

    for pos in positions:
        market = (pos.get("market") or "").strip().lower()
        if market and market in blocked:
            continue
        odds = int(pos.get("odds", -110))
        if not within_juice_ceiling(odds, juice_ceiling):
            continue
        if unit_reduction:
            pos = dict(pos)
            pos["units"] = max(
                0.5, round(float(pos.get("units", 1)) - unit_reduction, 1)
            )
        kept.append(pos)

    if max_plays is not None:
        kept = kept[:max_plays]
    return kept
