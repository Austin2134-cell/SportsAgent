"""Tests for shared play validation and defensive mode."""

from datetime import date, timedelta

from esm.play_validation import (
    apply_play_guards,
    apply_position_guards,
    max_units_for_edge,
)
from learning.memory import (
    _compute_losing_streak,
    _defensive_settings_from_stats,
)


def test_max_units_for_edge_tiers():
    assert max_units_for_edge(12) == 3.0
    assert max_units_for_edge(7) == 2.0
    assert max_units_for_edge(3) == 1.5
    assert max_units_for_edge(2.5) == 1.5
    assert max_units_for_edge(1) == 0.0


def test_apply_play_guards_rejects_thin_edge():
    card = {
        "official_plays": [
            {
                "bet": "Player Points Over 24.5",
                "market": "player_points",
                "odds": -110,
                "edge_gap_pct": 1.5,
                "units": 2,
            }
        ],
        "pass_notes": [],
    }
    out = apply_play_guards(card, require_edge=True)
    assert out["official_plays"] == []
    assert any("below minimum" in n for n in out["pass_notes"])


def test_apply_play_guards_caps_units_to_edge_tier():
    card = {
        "official_plays": [
            {
                "bet": "Player Points Over 24.5",
                "market": "player_points",
                "odds": -110,
                "edge_gap_pct": 6.0,
                "units": 3,
            }
        ],
        "pass_notes": [],
    }
    out = apply_play_guards(card, require_edge=True)
    assert len(out["official_plays"]) == 1
    assert out["official_plays"][0]["units"] == 2.0


def test_apply_play_guards_blocks_weak_market():
    card = {
        "official_plays": [
            {
                "bet": "Batter Hits Over 1.5",
                "market": "batter_hits",
                "odds": -120,
                "edge_gap_pct": 5.0,
                "units": 1,
            }
        ],
        "pass_notes": [],
    }
    out = apply_play_guards(
        card,
        blocked_markets={"batter_hits"},
        require_edge=True,
    )
    assert out["official_plays"] == []


def test_apply_play_guards_defensive_max_plays():
    card = {
        "official_plays": [
            {"bet": f"Play {i}", "market": "totals", "odds": -110, "edge_gap_pct": 5, "units": 1}
            for i in range(4)
        ],
        "pass_notes": [],
    }
    out = apply_play_guards(card, max_plays=2, require_edge=True)
    assert len(out["official_plays"]) == 2


def test_compute_losing_streak():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    bets = [
        {"date": today, "result": "L"},
        {"date": yesterday, "result": "L"},
        {"date": yesterday, "result": "W"},
    ]
    assert _compute_losing_streak(bets) == 2


def test_defensive_settings_on_7_day_loss():
    stats = {
        "last_7_days": {"net_units": -3.5, "wins": 1, "losses": 4},
        "losing_streak": 1,
        "by_pipeline": {},
        "by_market": {},
    }
    settings = _defensive_settings_from_stats(stats, "esm")
    assert settings["defensive"] is True
    assert settings["max_plays"] == 2
    assert settings["unit_reduction"] == 0.5


def test_defensive_settings_blocks_negative_roi_market():
    stats = {
        "last_7_days": {"net_units": 2.0},
        "losing_streak": 0,
        "by_pipeline": {
            "agent": {
                "by_market": {
                    "pitcher_strikeouts": {"W": 1, "L": 4, "P": 0, "net": -5.0},
                },
            },
        },
        "by_market": {},
    }
    settings = _defensive_settings_from_stats(stats, "agent")
    assert settings["defensive"] is False
    assert "pitcher_strikeouts" in settings["blocked_markets"]


def test_apply_position_guards_deduplicates_logic():
    positions = [
        {"bet": "MLB Over 8.5", "market": "totals", "odds": -105, "units": 1},
        {"bet": "Blocked market", "market": "batter_hits", "odds": -110, "units": 1},
    ]
    kept = apply_position_guards(
        positions,
        blocked_markets={"batter_hits"},
        unit_reduction=0.5,
    )
    assert len(kept) == 1
    assert kept[0]["units"] == 0.5
