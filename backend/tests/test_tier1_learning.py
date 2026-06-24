"""Tests for Tier 1 learning: pipeline-split memory and bankroll backfill."""

from agent.bankroll import apply_bet_result, compute_unit_size
from agent.bankroll_backfill import replay_bankroll_for_user
from learning.memory import (
    _aggregate_bets,
    _compute_user_stats,
    _format_user_memory,
    _format_platform_memory,
    _pipeline_key,
    get_performance_context,
)


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
    stats = _aggregate_bets(bets, include_recent_losses=True)
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["net_units"] == -0.18
    assert stats["by_market"]["player_points"]["W"] == 1
    assert len(stats["recent_losses"]) == 1
    assert stats["recent_losses"][0]["pipeline"] == "world_cup"


def test_format_user_memory_prioritizes_agent_pipeline():
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
    text = _format_user_memory(stats, pipeline="agent")
    assert "YOUR MEMORY (PRIMARY" in text
    assert "Your AGENT bets" in text
    assert "Your all-pipeline record" in text
    assert "Your pipeline breakdown" in text
    assert "world_cup:" in text


def test_format_platform_memory_is_anonymized():
    stats = {
        "lookback_days": 90,
        "active_users": 12,
        "wins": 80,
        "losses": 65,
        "pushes": 5,
        "net_units": 8.0,
        "roi_pct": 4.0,
        "total_bets": 150,
        "by_market": {
            "batter_hits": {"W": 10, "L": 25, "P": 0, "net": -12.0},
        },
        "by_sport": {},
        "by_confidence": {},
        "by_odds_bucket": {},
        "weak_markets": [{"market": "batter_hits", "record": "10-25", "net_units": -12.0}],
        "by_pipeline": {
            "agent": {
                "wins": 40,
                "losses": 30,
                "pushes": 2,
                "net_units": 6.0,
                "roi_pct": 5.0,
                "total_bets": 72,
                "by_market": {},
                "by_sport": {},
                "by_confidence": {},
                "by_odds_bucket": {},
                "weak_markets": [{"market": "batter_hits", "record": "10-25", "net_units": -12.0}],
            },
        },
    }
    text = _format_platform_memory(stats, pipeline="agent")
    assert "PLATFORM AGENT BRAIN (SECONDARY" in text
    assert "12 active user" in text
    assert "trust the user's own history" in text
    assert "Platform weak markets" in text
    assert "batter_hits" in text
    # No individual bet strings in platform brain
    assert "Over" not in text


def test_get_performance_context_user_first_then_platform():
    class FakeDB:
        def table(self, name):
            return self

        def select(self, *_cols):
            return self

        def eq(self, field, value):
            self._eq = (field, value)
            return self

        def execute(self):
            if self._eq == ("user_id", "user-1"):
                return type("R", (), {"data": [{
                    "stats": {
                        "lookback_days": 90,
                        "wins": 2, "losses": 1, "pushes": 0,
                        "net_units": 1.0, "roi_pct": 10.0, "total_bets": 3,
                        "by_market": {}, "by_sport": {}, "by_confidence": {},
                        "by_odds_bucket": {}, "recent_losses": [],
                        "by_pipeline": {
                            "agent": {
                                "wins": 2, "losses": 1, "pushes": 0,
                                "net_units": 1.0, "roi_pct": 10.0, "total_bets": 3,
                                "by_market": {}, "by_sport": {}, "by_confidence": {},
                                "by_odds_bucket": {}, "recent_losses": [],
                            },
                        },
                    },
                }]})()
            if self._eq == ("key", "global"):
                return type("R", (), {"data": [{
                    "stats": {
                        "lookback_days": 90,
                        "active_users": 5,
                        "wins": 20, "losses": 18, "pushes": 0,
                        "net_units": 2.0, "roi_pct": 3.0, "total_bets": 38,
                        "by_market": {}, "by_sport": {}, "by_confidence": {},
                        "by_odds_bucket": {}, "weak_markets": [],
                        "by_pipeline": {
                            "agent": {
                                "wins": 15, "losses": 12, "pushes": 0,
                                "net_units": 3.0, "roi_pct": 5.0, "total_bets": 27,
                                "by_market": {}, "by_sport": {}, "by_confidence": {},
                                "by_odds_bucket": {}, "weak_markets": [],
                            },
                        },
                    },
                }]})()
            return type("R", (), {"data": []})()

    text = get_performance_context(FakeDB(), "user-1", pipeline="agent")
    user_pos = text.find("YOUR MEMORY (PRIMARY")
    platform_pos = text.find("PLATFORM AGENT BRAIN (SECONDARY")
    assert user_pos >= 0
    assert platform_pos >= 0
    assert user_pos < platform_pos


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
