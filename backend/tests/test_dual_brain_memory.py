"""Tests for dual-brain memory (user primary + platform secondary)."""

from learning.memory import _compute_platform_stats, _weak_markets_platform


def test_weak_markets_platform_anonymized():
    bets = [
        {"result": "L", "market": "batter_hits", "units": 2, "odds": -110, "units_result": -2},
        {"result": "L", "market": "batter_hits", "units": 2, "odds": -110, "units_result": -2},
        {"result": "L", "market": "batter_hits", "units": 2, "odds": -110, "units_result": -2},
        {"result": "W", "market": "batter_hits", "units": 2, "odds": -110, "units_result": 1.82},
        {"result": "L", "market": "batter_hits", "units": 2, "odds": -110, "units_result": -2},
        {"result": "W", "market": "player_points", "units": 2, "odds": -110, "units_result": 1.82},
    ]
    weak = _weak_markets_platform(bets, min_bets=5)
    assert len(weak) == 1
    assert weak[0]["market"] == "batter_hits"
    assert "bet" not in weak[0]


class BetsQuery:
    def __init__(self, bets):
        self.bets = bets
        self._filters = []

    def select(self, *_cols):
        return self

    def neq(self, field, value):
        self._filters.append(("neq", field, value))
        return self

    def gte(self, field, value):
        self._filters.append(("gte", field, value))
        return self

    def execute(self):
        rows = self.bets
        for op, field, val in self._filters:
            if op == "neq":
                rows = [r for r in rows if r.get(field) != val]
            elif op == "gte":
                rows = [r for r in rows if (r.get(field) or "") >= val]
        return type("R", (), {"data": rows})()


class PlatformDB:
    def __init__(self, bets):
        self.bets = bets

    def table(self, name):
        if name == "bets":
            return BetsQuery(self.bets)
        raise ValueError(name)


def test_compute_platform_stats_counts_users():
    bets = [
        {"user_id": "u1", "result": "W", "date": "2026-06-01", "market": "m", "sport": "MLB",
         "units": 2, "odds": -110, "units_result": 1.82, "confidence": "HIGH"},
        {"user_id": "u2", "result": "L", "date": "2026-06-01", "market": "m", "sport": "MLB",
         "units": 2, "odds": -110, "units_result": -2, "confidence": "MEDIUM"},
    ]
    stats = _compute_platform_stats(PlatformDB(bets))
    assert stats["scope"] == "platform"
    assert stats["active_users"] == 2
    assert stats["total_bets"] == 2
    assert "recent_losses" not in stats
