"""Unit risk / P/L math."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.units import (
    aggregate_record,
    calculate_units_result,
    calculate_win_units,
    normalize_units_result,
    units_lost,
    units_won,
)


def test_win_profit_from_odds():
    assert calculate_win_units(2, -110) == 1.82
    assert calculate_win_units(2, 150) == 3.0
    assert calculate_win_units(2.5, 140) == 3.5


def test_loss_is_full_risk():
    assert calculate_units_result("L", 1.5, -114) == -1.5
    assert calculate_units_result("L", 2, -110) == -2.0


def test_push_is_zero():
    assert calculate_units_result("P", 2, -110) == 0.0


def test_units_won_and_lost_helpers():
    win_bet = {"result": "W", "units": 2, "odds": 150, "units_result": 3.0}
    loss_bet = {"result": "L", "units": 1.5, "odds": -114, "units_result": -1.5}
    assert units_won(win_bet) == 3.0
    assert units_won(loss_bet) is None
    assert units_lost(loss_bet) == 1.5
    assert units_lost(win_bet) is None


def test_normalize_recorrects_stored_value():
    bet = {"result": "W", "units": 2, "odds": -110, "units_result": 99}
    assert normalize_units_result(bet) == 1.82


def test_aggregate_record():
    rec = aggregate_record([
        {"result": "W", "units": 2, "odds": -110, "units_result": 1.82},
        {"result": "L", "units": 2, "odds": -110, "units_result": -2},
        {"result": "P", "units": 2, "odds": -110, "units_result": 0},
    ])
    assert rec["record_str"] == "1-1-1"
    assert rec["net_units"] == -0.18
    assert rec["units_risked"] == 6.0
    assert rec["units_won"] == 1.82
    assert rec["units_lost"] == 2.0
