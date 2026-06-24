"""Unit tests for soccer bet grading logic."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.grader import (
    _parse_game_teams,
    _parse_dnb_team,
    _parse_ml_team,
    _parse_total,
    _parse_btts,
    _resolve_soccer_outcome,
    _team_matches,
)
from services.units import calculate_win_units


def test_parse_game_teams():
    assert _parse_game_teams("Senegal vs Norway (Group D)") == ("Senegal", "Norway")
    assert _parse_game_teams("Austria @ Argentina") == ("Austria", "Argentina")
    assert _parse_game_teams("France v Iraq (Group A)") == ("France", "Iraq")


def test_dnb_win_loss_push():
    home, away, hs, aws = "Argentina", "Austria", 2, 0
    assert _resolve_soccer_outcome("Draw No Bet — Argentina", "", home, away, hs, aws) == ("W", "")
    assert _resolve_soccer_outcome("Draw No Bet — Austria", "", home, away, hs, aws) == ("L", "")

    hs, aws = 1, 1
    assert _resolve_soccer_outcome("DNB — Argentina", "", home, away, hs, aws) == ("P", "draw push")


def test_ml_three_way():
    home, away = "France", "Iraq"
    assert _resolve_soccer_outcome("Match Result — France ML", "", home, away, 3, 0) == ("W", "")
    assert _resolve_soccer_outcome("Match Result — France ML", "", home, away, 1, 1) == ("L", "")
    assert _resolve_soccer_outcome("Match Result — Iraq ML", "", home, away, 3, 0) == ("L", "")


def test_totals():
    home, away = "Senegal", "Norway"
    assert _resolve_soccer_outcome("Total Goals Under 2.5", "", home, away, 1, 0) == ("W", "")
    assert _resolve_soccer_outcome("Total Goals Over 2.5", "", home, away, 2, 1) == ("W", "")
    assert _resolve_soccer_outcome("Under 2.5", "totals", home, away, 2, 1) == ("L", "")


def test_btts():
    home, away = "Algeria", "Jordan"
    assert _resolve_soccer_outcome("Both Teams to Score No", "", home, away, 2, 0) == ("W", "")
    assert _resolve_soccer_outcome("Both Teams to Score Yes", "", home, away, 2, 1) == ("W", "")
    assert _resolve_soccer_outcome("BTTS No", "btts", home, away, 1, 1) == ("L", "")


def test_parsers():
    assert _parse_dnb_team("Draw No Bet — Senegal", "") == "Senegal"
    assert _parse_ml_team("Match Result — Norway ML", "") == "Norway"
    assert _parse_total("Total Goals Under 2.5", "") == ("Under", 2.5)
    assert _parse_btts("Both Teams to Score No", "") == "No"


def test_team_matches():
    assert _team_matches("Argentina", "Argentina")
    assert _team_matches("Senegal", "Senegal National Team") or _team_matches("Senegal", "Senegal")
    assert not _team_matches("France", "Iraq")


def test_calculate_win_units():
    assert calculate_win_units(2, -110) == 1.82
    assert calculate_win_units(2, 150) == 3.0


def test_game_total_parser():
    from services.grader import _parse_total
    assert _parse_total("Total Over 10.0", "game_total") == ("Over", 10.0)
    assert _parse_total("Total Under 7.5", "game_total") == ("Under", 7.5)
