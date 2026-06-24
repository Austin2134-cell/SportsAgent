"""Tests for agent learning loop helpers."""

from agent.bankroll import apply_bet_result, compute_unit_size
from agent.memory_store import (
    _find_position_episode,
    _grade_lesson,
    format_hypotheses_for_prompt,
    format_recent_episodes_for_prompt,
)


class FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def select(self, *_cols):
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def is_(self, field, value):
        self._filters.append(("is", field, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        rows = self._rows
        for op, field, value in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "is" and value == "null":
                rows = [r for r in rows if r.get(field) is None]
        return type("Result", (), {"data": rows})()


class FakeDB:
    def __init__(self, episodes):
        self.episodes = episodes

    def table(self, name):
        assert name == "agent_episodes"
        return FakeTable(self.episodes)


def test_apply_bet_result_updates_bankroll():
    bankroll = 1000.0
    unit_size = compute_unit_size(bankroll, 0.03)
    win_units = 1.82  # typical -110 win on 2u bet expressed as unit return... use simple 2u win
    new_bankroll = apply_bet_result(bankroll, 2.0, unit_size)
    assert new_bankroll == round(bankroll + 2.0 * unit_size, 2)

    loss_bankroll = apply_bet_result(bankroll, -2.0, unit_size)
    assert loss_bankroll == round(bankroll - 2.0 * unit_size, 2)


def test_grade_lesson_win_loss_push():
    assert "Win" in _grade_lesson("W", 1.8, "")
    assert "model miss" in _grade_lesson("L", -2.0, "model miss")
    assert "Push" in _grade_lesson("P", 0.0, "")


def test_find_position_episode_by_bet_id():
    db = FakeDB([
        {
            "id": "ep-1",
            "user_id": "user-1",
            "episode_type": "position",
            "title": "Position: Juan Soto Over 1.5 Hits",
            "action_payload": {"bet_id": "bet-99", "bet": "Juan Soto Over 1.5 Hits"},
            "outcome": None,
        },
    ])
    bet = {"id": "bet-99", "bet": "Juan Soto Over 1.5 Hits"}
    assert _find_position_episode(db, "user-1", bet) == "ep-1"


def test_find_position_episode_fallback_bet_text():
    db = FakeDB([
        {
            "id": "ep-2",
            "user_id": "user-1",
            "episode_type": "position",
            "title": "Position: Shohei Ohtani Over 7.5 K",
            "action_payload": {"bet": "Shohei Ohtani Over 7.5 K"},
            "outcome": None,
        },
    ])
    bet = {"bet": "Shohei Ohtani Over 7.5 K"}
    assert _find_position_episode(db, "user-1", bet) == "ep-2"


def test_find_position_episode_skips_graded():
    db = FakeDB([
        {
            "id": "ep-3",
            "user_id": "user-1",
            "episode_type": "position",
            "title": "Position: Test Bet",
            "action_payload": {"bet_id": "bet-1", "bet": "Test Bet"},
            "outcome": "W",
        },
    ])
    bet = {"id": "bet-1", "bet": "Test Bet"}
    assert _find_position_episode(db, "user-1", bet) is None


def test_format_hypotheses_for_prompt_empty():
    assert format_hypotheses_for_prompt([]) == ""


def test_format_hypotheses_for_prompt_includes_thesis():
    text = format_hypotheses_for_prompt([
        {
            "sport": "MLB",
            "game": "NYY @ BOS",
            "market": "player_points",
            "player": "Aaron Judge",
            "thesis": "Line soft vs LHP",
        },
    ])
    assert "ACTIVE HYPOTHESES" in text
    assert "Aaron Judge" in text
    assert "Line soft vs LHP" in text


def test_format_recent_episodes_includes_outcome_and_lesson():
    text = format_recent_episodes_for_prompt([
        {
            "episode_type": "position",
            "title": "Position: Test Bet",
            "reasoning": "Strong edge on usage.",
            "outcome": "L",
            "lesson": "Loss (-2.0u). model miss.",
        },
        {
            "episode_type": "system",
            "title": "Agent online",
            "reasoning": "ignored",
        },
    ])
    assert "RECENT AGENT ACTIVITY" in text
    assert "→ L" in text
    assert "Lesson:" in text
    assert "Agent online" not in text
