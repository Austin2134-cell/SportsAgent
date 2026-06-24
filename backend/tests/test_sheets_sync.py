"""Tests for Google Sheets sync helpers (no API calls)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.sheets_sync import (
    _calc_record,
    _build_overall_record_rows,
    _build_by_sport_rows,
    BETS_HEADERS,
    BY_SPORT_HEADERS,
)


def test_calc_record():
    bets = [
        {"result": "W", "units": 2, "units_result": 1.82},
        {"result": "L", "units": 2, "units_result": -2},
        {"result": "P", "units": 2, "units_result": 0},
    ]
    rec = _calc_record(bets)
    assert rec["record_str"] == "1-1-1"
    assert rec["net_units"] == -0.18


def test_build_overall_record_rows():
    bets = [
        {"date": "2026-06-22", "sport": "SOCCER", "result": "pending", "units": 2},
        {"date": "2026-06-21", "sport": "MLB", "result": "W", "units": 2, "units_result": 1.8},
    ]
    rows = _build_overall_record_rows(bets, "2026-06-22 12:00 UTC")
    assert rows[0] == ["Last Synced", "2026-06-22 12:00 UTC"]
    assert rows[1] == ["Total Plays", "2"]
    assert rows[2] == ["Pending", "1"]


def test_build_by_sport_rows():
    bets = [
        {"sport": "SOCCER", "result": "pending", "units": 2, "units_result": 0},
        {"sport": "SOCCER", "result": "pending", "units": 2, "units_result": 0},
        {"sport": "MLB", "result": "W", "units": 2, "odds": -110, "units_result": 1.82},
    ]
    rows = _build_by_sport_rows(bets)
    assert len(rows) == 2
    soccer = next(r for r in rows if r[0] == "SOCCER")
    assert soccer[4] == 2  # pending
    assert soccer[11] == 2  # total plays


def test_headers():
    assert len(BETS_HEADERS) == 19
    assert "Units Risked" in BETS_HEADERS
    assert "Units Won" in BETS_HEADERS
    assert "Units Lost" in BETS_HEADERS
    assert "Net Units" in BETS_HEADERS
    assert BY_SPORT_HEADERS[0] == "Sport"
