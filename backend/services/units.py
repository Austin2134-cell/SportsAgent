"""
Unit math — single source of truth for risk and P/L.

Rules:
  - Units Risked  = stake size (`units` on each bet)
  - Win           = profit units from odds (not including returned stake)
  - Loss          = lose full units risked (-units)
  - Push          = 0
"""

from __future__ import annotations


def calculate_win_units(units_risked: float, odds: int) -> float:
    """Profit units on a win at American odds."""
    units = float(units_risked)
    if odds >= 0:
        return round(units * (odds / 100), 2)
    return round(units * (100 / abs(odds)), 2)


def calculate_units_result(result: str, units_risked: float, odds: int) -> float:
    """Net unit P/L for a graded bet."""
    r = (result or "").strip().upper()
    units = float(units_risked)
    if r == "W":
        return calculate_win_units(units, int(odds))
    if r == "L":
        return round(-abs(units), 2)
    return 0.0


def normalize_units_result(bet: dict) -> float:
    """Recompute units_result from result, units risked, and odds."""
    return calculate_units_result(
        bet.get("result", ""),
        float(bet.get("units") or 0),
        int(bet.get("odds") or -110),
    )


def units_won(bet: dict) -> float | None:
    """Profit units on a win; None if not a win."""
    if (bet.get("result") or "").upper() != "W":
        return None
    return calculate_win_units(float(bet.get("units") or 0), int(bet.get("odds") or -110))


def units_lost(bet: dict) -> float | None:
    """Units lost on a loss (positive magnitude); None if not a loss."""
    if (bet.get("result") or "").upper() != "L":
        return None
    return round(abs(float(bet.get("units") or 0)), 2)


def net_units(bet: dict) -> float | None:
    """Net P/L for a graded bet; None if still pending."""
    result = (bet.get("result") or "").upper()
    if result in ("", "PENDING"):
        return None
    stored = bet.get("units_result")
    if stored is not None and result in ("W", "L", "P"):
        return round(float(stored), 2)
    return normalize_units_result(bet)


def format_net_units(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:+.2f}"


def format_units_won(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def format_units_lost(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def aggregate_record(bets: list[dict]) -> dict:
    """Summarize graded bets using units risked + net P/L rules."""
    wins = losses = pushes = 0
    net = 0.0
    units_risked_total = 0.0
    units_won_total = 0.0
    units_lost_total = 0.0

    for bet in bets:
        result = (bet.get("result") or "").upper()
        if result in ("", "PENDING"):
            continue
        risk = float(bet.get("units") or 0)
        units_risked_total += risk
        pl = net_units(bet) or 0.0
        net += pl
        if result == "W":
            wins += 1
            units_won_total += pl
        elif result == "L":
            losses += 1
            units_lost_total += abs(risk)
        elif result == "P":
            pushes += 1

    roi = (net / units_risked_total * 100) if units_risked_total > 0 else 0.0
    sign = "+" if net >= 0 else ""
    return {
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "record_str": f"{wins}-{losses}-{pushes}",
        "net_units": round(net, 2),
        "units_risked": round(units_risked_total, 2),
        "units_won": round(units_won_total, 2),
        "units_lost": round(units_lost_total, 2),
        "roi_pct": round(roi, 1),
        "units_str": f"{sign}{net:.1f}u",
    }
