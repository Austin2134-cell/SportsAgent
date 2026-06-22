"""Tests for Google Sheets sync helpers (no API calls)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.sheets_sync import _calc_record, _build_summary_rows, BETS_HEADERS


def test_calc_record():
    bets = [
        {"result": "W", "units": 2, "units_result": 1.82},
        {"result": "L", "units": 2, "units_result": -2},
        {"result": "P", "units": 2, "units_result": 0},
    ]
    rec = _calc_record(bets)
    assert rec["record_str"] == "1-1-1"
    assert rec["net_units"] == -0.18


def test_build_summary_rows():
    bets = [
        {"date": "2026-06-22", "sport": "SOCCER", "result": "pending", "units": 2, "units_result": 0},
        {"date": "2026-06-21", "sport": "MLB", "result": "W", "units": 2, "units_result": 1.8},
    ]
    rows = _build_summary_rows(bets, "2026-06-22 12:00 UTC")
    assert rows[0] == ["Meta", "Last Synced", "2026-06-22 12:00 UTC"]
    assert rows[3][2] == "1"
    assert any(r[0] == "By Date" and r[1] == "2026-06-22" for r in rows)


def test_bets_headers_count():
    assert len(BETS_HEADERS) == 15
