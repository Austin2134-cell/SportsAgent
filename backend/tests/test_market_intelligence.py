"""Tests for line movement / market intelligence."""

from esm.market_intelligence import (
    analyze_game_lines,
    format_intelligence_for_prompt,
    sharp_action_label,
)


def test_steam_detection_on_ml_move():
    history = [
        {
            "captured_at": "2026-06-25T08:00:00+00:00",
            "lines": {"home_ml": 150, "away_ml": -130, "total": 2.5, "under_odds": -110},
        },
    ]
    current = {"home_ml": 130, "away_ml": -150, "total": 2.5, "under_odds": -130}
    intel = analyze_game_lines(history, "Ecuador", "Germany", current)
    assert "steam_ml_away" in intel["flags"]
    assert intel["steam_side"] == "Germany"


def test_reverse_line_with_splits():
    history = [
        {
            "captured_at": "2026-06-25T08:00:00+00:00",
            "lines": {"home_ml": -200, "away_ml": 170},
        },
    ]
    # Public heavy on home favorite but line improved for home bettors → sharps on away
    current = {"home_ml": -170, "away_ml": 145}
    splits = {
        "h2h_home": {
            "public_bet_pct": 72,
            "public_money_pct": 45,
            "source": "action_network",
            "sharp_indicator": "sharp",
        },
    }
    intel = analyze_game_lines(history, "USA", "Turkey", current, external_splits=splits)
    assert intel["reverse_line_flag"]
    assert intel["sharp_money_flag"]
    assert intel["public_bet_pct_home"] == 72


def test_format_prompt_includes_movement():
    intelligence = {
        "baseball_mlb": {
            "evt1": {
                "away_team": "A",
                "home_team": "B",
                "opening_captured_at": "2026-06-25T12:00:00Z",
                "line_movement_summary": ["Total: 8.5 → 8.0 (-0.5)"],
                "flags": ["steam_total"],
                "steam_side": None,
                "reverse_line_flag": False,
                "data_quality": "snapshot_only",
            },
        },
    }
    text = format_intelligence_for_prompt(intelligence)
    assert "MARKET INTELLIGENCE" in text
    assert "steam_total" in text


def test_sharp_action_label():
    intel = {
        "steam_side": "Germany",
        "flags": ["steam_under_juice"],
        "reverse_line_flag": True,
    }
    label = sharp_action_label(intel)
    assert "Steam" in label
    assert "Reverse line" in label


def test_splits_applied_without_opening_history():
    """Splits must apply even when no market_snapshots history exists."""
    splits = {
        "total_over": {
            "public_bet_pct": 95,
            "public_money_pct": 95,
            "source": "action_network",
        },
        "total_under": {
            "public_bet_pct": 5,
            "public_money_pct": 5,
            "source": "action_network",
        },
    }
    intel = analyze_game_lines(
        [],
        "Ecuador",
        "Germany",
        {"total": 2.5, "under_odds": 140},
        external_splits=splits,
    )
    assert intel["public_bet_pct_over"] == 95
    assert intel["data_quality"] == "snapshot_plus_splits"
    assert "public_heavy_over" in intel["flags"]
    assert "contrarian_under_setup" in intel["flags"]
