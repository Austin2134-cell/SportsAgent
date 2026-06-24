"""
Bankroll math — auto-calculated unit sizing from bankroll percentage.
Default: 1 unit = 3% of bankroll, max daily exposure = 6% of bankroll (~2 units).
"""

DEFAULT_UNIT_PCT = 0.03
DEFAULT_MAX_DAILY_PCT = 0.06


def compute_unit_size(bankroll: float, unit_pct: float = DEFAULT_UNIT_PCT) -> float:
    """Dollar value of one unit."""
    return round(max(bankroll * unit_pct, 1.0), 2)


def compute_max_daily_units(
    bankroll: float,
    unit_pct: float = DEFAULT_UNIT_PCT,
    max_daily_pct: float = DEFAULT_MAX_DAILY_PCT,
) -> int:
    """Max units the agent can recommend in one day."""
    unit_size = compute_unit_size(bankroll, unit_pct)
    max_dollars = bankroll * max_daily_pct
    return max(1, int(max_dollars / unit_size))


def compute_bankroll_summary(
    bankroll_current: float,
    bankroll_starting: float,
    unit_pct: float = DEFAULT_UNIT_PCT,
    max_daily_pct: float = DEFAULT_MAX_DAILY_PCT,
    units_at_risk: float = 0,
) -> dict:
    unit_size = compute_unit_size(bankroll_current, unit_pct)
    max_units = compute_max_daily_units(bankroll_current, unit_pct, max_daily_pct)
    units_remaining = max(0, max_units - units_at_risk)
    pnl = bankroll_current - bankroll_starting
    pnl_pct = round((pnl / bankroll_starting) * 100, 1) if bankroll_starting > 0 else 0.0

    return {
        "bankroll_current": round(bankroll_current, 2),
        "bankroll_starting": round(bankroll_starting, 2),
        "unit_size": unit_size,
        "unit_pct": unit_pct,
        "max_daily_pct": max_daily_pct,
        "max_daily_units": max_units,
        "units_at_risk": round(units_at_risk, 2),
        "units_remaining_today": round(units_remaining, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": pnl_pct,
    }


def apply_bet_result(bankroll_current: float, units_result: float, unit_size: float) -> float:
    """Update bankroll after a graded bet. units_result is in units (+/-)."""
    dollar_result = units_result * unit_size
    return round(max(bankroll_current + dollar_result, 0), 2)
