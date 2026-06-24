"""Unit tracker — 1% bankroll sizing and WC separation."""

from agent.bankroll import compute_bankroll_summary, compute_unit_size, compute_max_daily_units
from agent.unit_tracker import (
    DEFAULT_UNIT_PCT,
    is_wc_bet,
    major_league_sport_keys,
)


def test_one_percent_unit_size():
    assert compute_unit_size(1000, DEFAULT_UNIT_PCT) == 10.0
    assert compute_unit_size(2500, 0.01) == 25.0


def test_max_daily_units_at_one_percent():
    # 6% daily cap / 1% per unit = 6 units on $1000 bankroll
    assert compute_max_daily_units(1000, 0.01, 0.06) == 6


def test_wc_bets_excluded_from_major_league_exposure():
    summary = compute_bankroll_summary(
        bankroll_current=1000,
        bankroll_starting=1000,
        unit_pct=0.01,
        max_daily_pct=0.06,
        units_at_risk=3.0,
    )
    assert summary["unit_size"] == 10.0
    assert summary["max_daily_units"] == 6
    assert summary["units_remaining_today"] == 3.0


def test_is_wc_bet_by_tag_or_notes():
    assert is_wc_bet({"post_slate_tag": "world_cup"})
    assert is_wc_bet({"notes": "[WC] Under 2.5 edge"})
    assert not is_wc_bet({"post_slate_tag": "esm", "notes": "MLB play"})


def test_major_league_filter_excludes_wc():
    keys = major_league_sport_keys(["baseball_mlb", "soccer_fifa_world_cup", "basketball_nba"])
    assert keys == ["baseball_mlb", "basketball_nba"]
