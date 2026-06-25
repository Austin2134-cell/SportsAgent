"""Tests for posted DNB line validation."""

from esm.soccer_odds import (
    within_juice_ceiling,
    validate_wc_official_plays,
    posted_dnb_odds,
    parse_dnb_team,
)


def _snapshot():
    return {
        "sports": {
            "soccer_fifa_world_cup": {
                "games": [
                    {
                        "away_team": "Germany",
                        "home_team": "Ecuador",
                        "lines": {
                            "away_dnb": -370,
                            "home_dnb": 275,
                            "dnb_book": "draftkings",
                            "under_odds": 138,
                            "total": 2.5,
                        },
                    },
                    {
                        "away_team": "USA",
                        "home_team": "Turkey",
                        "lines": {
                            "away_dnb": -240,
                            "home_dnb": 185,
                            "dnb_book": "draftkings",
                            "away_ml": -115,
                        },
                    },
                ],
            },
        },
    }


def test_within_juice_ceiling():
    assert within_juice_ceiling(-118)
    assert within_juice_ceiling(-150)
    assert not within_juice_ceiling(-151)
    assert not within_juice_ceiling(-240)
    assert not within_juice_ceiling(-370)


def test_parse_dnb_team():
    assert parse_dnb_team("Draw No Bet — Germany") == "Germany"


def test_posted_dnb_odds():
    game = _snapshot()["sports"]["soccer_fifa_world_cup"]["games"][0]
    assert posted_dnb_odds(game, "Germany") == -370
    assert posted_dnb_odds(game, "Ecuador") == 275


def test_validate_removes_juicy_dnb_and_keeps_totals():
    card = {
        "official_plays": [
            {
                "game": "Germany vs Ecuador",
                "bet": "Draw No Bet — Germany",
                "odds": -118,
                "book": "DraftKings",
                "market": "draw_no_bet",
            },
            {
                "game": "Germany vs Ecuador",
                "bet": "Total Goals Under 2.5",
                "odds": 138,
                "book": "DraftKings",
                "market": "total_goals",
            },
            {
                "game": "USA vs Turkey",
                "bet": "Draw No Bet — USA",
                "odds": -115,
                "book": "DraftKings",
                "market": "draw_no_bet",
            },
        ],
        "pass_notes": [],
    }
    out = validate_wc_official_plays(card, _snapshot())
    assert len(out["official_plays"]) == 1
    assert out["official_plays"][0]["bet"] == "Total Goals Under 2.5"
    assert any("exceeds -150" in n for n in out["pass_notes"])


def test_validate_fixes_dnb_when_within_ceiling():
    snapshot = {
        "sports": {
            "soccer_fifa_world_cup": {
                "games": [
                    {
                        "away_team": "France",
                        "home_team": "Canada",
                        "lines": {
                            "away_dnb": -118,
                            "home_dnb": 102,
                            "dnb_book": "draftkings",
                        },
                    },
                ],
            },
        },
    }
    card = {
        "official_plays": [
            {
                "game": "France vs Canada",
                "bet": "Draw No Bet — France",
                "odds": -105,
                "book": "DraftKings",
            },
        ],
        "pass_notes": [],
    }
    out = validate_wc_official_plays(card, snapshot)
    assert len(out["official_plays"]) == 1
    assert out["official_plays"][0]["odds"] == -118
