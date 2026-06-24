"""Tests for Tier 1 learning: pipeline-split memory and bankroll backfill."""

from agent.bankroll import apply_bet_result, compute_unit_size
from agent.bankroll_backfill import replay_bankroll_for_user
from learning.memory import _aggregate_bets, _format_for_prompt, _pipeline_key, _compute_stats


def test_pipeline_key_normalizes_tags():
    assert _pipeline_key({"post_slate_tag": "agent"}) == "agent"
    assert _pipeline_key({"post_slate_tag": "WORLD_CUP"}) == "world_cup"
    assert _pipeline_key({"post_slate_tag": ""}) == "other"
    assert _pipeline_key({}) == "other"


def test_aggregate_bets_basic():
    bets = [
        {
            "result": "W",
            "units": 2,
            "odds": -110,
            "units_result": 1.82,
            "market": "player_points",
            "sport": "NBA",
            "confidence": "HIGH",
            "post_slate_tag": "agent",
        },
        {
            "result": "L",
            "units": 2,
            "odds": -110,
            "units_result": -2,
            "market": "batter_hits",
            "sport": "MLB",
            "confidence": "MEDIUM",
            "post_slate_tag": "world_cup",
            "date": "2026-06-01",
            "bet": "Test loss",
        },
    ]
    stats = _aggregate_bets(bets)
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["net_units"] == -0.18
    assert stats["by_market"]["player_points"]["W"] == 1
    assert len(stats["recent_losses"]) == 1
    assert stats["recent_losses"][0]["pipeline"] == "world_cup"


def test_format_for_prompt_prioritizes_agent_pipeline():
    stats = {
        "lookback_days": 90,
        "wins": 3,
        "losses": 2,
        "pushes": 0,
        "net_units": 1.0,
        "roi_pct": 5.0,
        "total_bets": 5,
        "by_market": {},
        "by_sport": {},
        "by_confidence": {},
        "by_odds_bucket": {},
        "recent_losses": [],
        "by_pipeline": {
            "agent": {
                "wins": 2,
                "losses": 0,
                "pushes": 0,
                "net_units": 3.5,
                "roi_pct": 20.0,
                "total_bets": 2,
                "by_market": {},
                "by_sport": {},
                "by_confidence": {},
                "by_odds_bucket": {},
                "recent_losses": [],
            },
            "world_cup": {
                "wins": 1,
                "losses": 2,
                "pushes": 0,
                "net_units": -2.5,
                "roi_pct": -15.0,
                "total_bets": 3,
                "by_market": {},
                "by_sport": {},
                "by_confidence": {},
                "by_odds_bucket": {},
                "recent_losses": [],
            },
        },
    }
    text = _format_for_prompt(stats, pipeline="agent")
    assert "AGENT pipeline" in text
    assert "Overall (all pipelines)" in text
    assert "world_cup:" in text


class FakeQuery:
    def __init__(self, table_name, store):
        self.table_name = table_name
        self.store = store
        self._filters = []
        self._orders = []

    def select(self, *_cols):
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def neq(self, field, value):
        self._filters.append(("neq", field, value))
        return self

    def order(self, field, **_kwargs):
        self._orders.append(field)
        return self

    def update(self, data):
        self._update = data
        return self

    def execute(self):
        if self.table_name == "agent_instances":
            if hasattr(self, "_update"):
                for row in self.store["agent_instances"]:
                    for op, field, value in self._filters:
                        if op == "eq" and row.get(field) != value:
                            break
                    else:
                        row.update(self._update)
                return type("R", (), {"data": []})()
            rows = list(self.store["agent_instances"])
        elif self.table_name == "bets":
            rows = list(self.store["bets"])
        else:
            rows = []

        for op, field, value in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "neq":
                rows = [r for r in rows if r.get(field) != value]

        for field in self._orders:
            rows.sort(key=lambda r: r.get(field) or "")

        return type("R", (), {"data": rows})()


class FakeDB:
    def __init__(self, agent_instances, bets):
        self.store = {"agent_instances": agent_instances, "bets": bets}

    def table(self, name):
        return FakeQuery(name, self.store)


def test_replay_bankroll_for_user_compounds_results(monkeypatch):
    user_id = "user-1"
    db = FakeDB(
        agent_instances=[{
            "user_id": user_id,
            "bankroll_starting": 1000,
            "bankroll_current": 1000,
            "unit_pct": 0.03,
        }],
        bets=[
            {
                "user_id": user_id,
                "date": "2026-06-01",
                "created_at": "2026-06-01T10:00:00Z",
                "result": "W",
                "units": 2,
                "odds": -110,
                "units_result": 1.82,
            },
            {
                "user_id": user_id,
                "date": "2026-06-02",
                "created_at": "2026-06-02T10:00:00Z",
                "result": "L",
                "units": 2,
                "odds": -110,
                "units_result": -2,
            },
        ],
    )

    monkeypatch.setattr(
        "agent.unit_tracker.refresh_stored_unit_size",
        lambda _db, _uid: 30.0,
    )

    result = replay_bankroll_for_user(db, user_id)
    assert result["bets_replayed"] == 2
    assert result["bankroll_current"] != 1000

    # Manual replay check
    bankroll = 1000.0
    unit_pct = 0.03
    for bet in db.store["bets"]:
        unit_size = compute_unit_size(bankroll, unit_pct)
        bankroll = apply_bet_result(bankroll, bet["units_result"], unit_size)
    assert round(result["bankroll_current"], 2) == round(bankroll, 2)
