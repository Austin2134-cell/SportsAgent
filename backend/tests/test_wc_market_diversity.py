"""Tests for WC card market-diversity guardrails."""

from esm.market_intelligence import _format_flags_for_prompt
from services.world_cup_card import _is_all_unders_card, _is_total_under_bet


def test_is_total_under_bet():
    assert _is_total_under_bet("Total Goals Under 2.5")
    assert _is_total_under_bet("Under 2.5")
    assert not _is_total_under_bet("Total Goals Over 2.5")
    assert not _is_total_under_bet("Draw No Bet — France")


def test_is_all_unders_card():
    assert not _is_all_unders_card({"official_plays": []})
    assert not _is_all_unders_card({
        "official_plays": [{"bet": "Total Goals Under 2.5"}],
    })
    assert _is_all_unders_card({
        "official_plays": [
            {"bet": "Total Goals Under 2.5"},
            {"bet": "Total Goals Under 2.5"},
        ],
    })
    assert not _is_all_unders_card({
        "official_plays": [
            {"bet": "Total Goals Under 2.5"},
            {"bet": "Draw No Bet — Spain"},
        ],
    })


def test_format_flags_for_prompt_neutralizes_contrarian_labels():
    text = _format_flags_for_prompt(["contrarian_under_setup", "steam_total"])
    assert "contrarian_under_setup" not in text
    assert "context only" in text
    assert "steam_total" in text
