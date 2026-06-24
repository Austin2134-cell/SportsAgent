"""Tests for hard calibration gates and post-grade reflection."""

from agent.calibration import (
    apply_calibration_to_positions,
    build_calibration_gates,
    evaluate_position,
    format_gates_for_prompt,
)


def _user_stats(market: str, w: int, l: int, net: float) -> dict:
    block = {
        "wins": w,
        "losses": l,
        "pushes": 0,
        "total_bets": w + l,
        "net_units": net,
        "roi_pct": -20.0,
        "by_market": {
            market: {"W": w, "L": l, "P": 0, "net": net},
        },
    }
    return {"by_pipeline": {"agent": block}, **block}


def test_build_block_gate_on_user_underperformance():
    stats = _user_stats("batter_hits", 1, 5, -8.0)
    gates = build_calibration_gates(stats, None)
    assert gates["markets"]["batter_hits"]["action"] == "block"
    assert "batter_hits" in gates["summary"][0]


def test_build_cap_gate_moderate_losses():
    stats = _user_stats("player_points", 1, 3, -2.5)
    gates = build_calibration_gates(stats, None)
    assert gates["markets"]["player_points"]["action"] == "cap"
    assert gates["markets"]["player_points"]["max_units"] == 1.0


def test_platform_weak_market_caps_thin_user_sample():
    user = {"by_pipeline": {"agent": {"by_market": {}}}}
    platform = {
        "by_pipeline": {
            "agent": {
                "weak_markets": [
                    {"market": "batter_total_bases", "record": "2-8", "net_units": -6.0},
                ],
            },
        },
    }
    gates = build_calibration_gates(user, platform)
    assert gates["markets"]["batter_total_bases"]["action"] == "cap"
    assert gates["markets"]["batter_total_bases"]["source"] == "platform"


def test_evaluate_position_block_and_cap():
    gates = build_calibration_gates(_user_stats("batter_hits", 1, 5, -8.0), None)
    allowed, max_u, reason = evaluate_position({"market": "batter_hits"}, gates)
    assert allowed is False
    assert "batter_hits" in reason

    cap_gates = build_calibration_gates(_user_stats("player_points", 1, 3, -2.5), None)
    allowed, max_u, reason = evaluate_position({"market": "player_points", "units": 2}, cap_gates)
    assert allowed is True
    assert max_u == 1.0


def test_apply_calibration_blocks_and_caps_units():
    gates = build_calibration_gates(_user_stats("batter_hits", 1, 5, -8.0), None)
    cap_gates = build_calibration_gates(_user_stats("player_points", 1, 3, -2.5), None)
    merged = {
        "markets": {
            **gates["markets"],
            **cap_gates["markets"],
        },
        "summary": gates["summary"] + cap_gates["summary"],
    }
    positions = [
        {"bet": "Over 1.5 Hits", "market": "batter_hits", "units": 2},
        {"bet": "Over 20.5 Points", "market": "player_points", "units": 2.5},
        {"bet": "Over 5.5 Rebounds", "market": "player_rebounds", "units": 2},
    ]
    accepted, blocked = apply_calibration_to_positions(positions, merged)
    assert len(blocked) == 1
    assert blocked[0]["market"] == "batter_hits"
    assert len(accepted) == 2
    points = next(p for p in accepted if p["market"] == "player_points")
    assert points["units"] == 1.0
    rebounds = next(p for p in accepted if p["market"] == "player_rebounds")
    assert rebounds["units"] == 2


def test_format_gates_for_prompt_nonempty():
    gates = build_calibration_gates(_user_stats("batter_hits", 1, 5, -8.0), None)
    text = format_gates_for_prompt(gates)
    assert "HARD CALIBRATION GATES" in text
    assert "batter_hits" in text


class EpisodeDB:
    def __init__(self):
        self.episodes = []
        self.beliefs = []

    def table(self, name):
        return Table(name, self)


class Table:
    def __init__(self, name, db):
        self.name = name
        self.db = db
        self._filters = {}
        self._payload = None

    def select(self, *_cols):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def insert(self, row):
        if self.name == "agent_episodes":
            self.db.episodes.append(row)
        elif self.name == "agent_beliefs":
            self.db.beliefs.append(row)
        return self

    def execute(self):
        if self.name == "agent_memory":
            return type("R", (), {"data": []})()
        if self.name == "platform_memory":
            return type("R", (), {"data": []})()
        return type("R", (), {"data": []})()


def test_reflect_on_grade_logs_loss_reflection(monkeypatch):
    from agent.calibration import reflect_on_grade

    db = EpisodeDB()
    monkeypatch.setattr(
        "agent.calibration.load_memory_context",
        lambda _db, _uid: {"gates": {"markets": {}}},
    )
    reflect_on_grade(
        db,
        {"user_id": "u1", "id": "b1", "market": "player_points", "bet": "Over 20.5", "sport": "NBA"},
        "L",
        -2.0,
    )
    assert len(db.episodes) == 1
    assert db.episodes[0]["episode_type"] == "reflection"
