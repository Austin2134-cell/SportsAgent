"""Tests for Claude cost-control helpers."""

from esm.claude_config import AGENT_SCANS_ENABLED, estimate_call_cost_usd


class FakeUsage:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_estimate_call_cost_usd_basic():
    usage = FakeUsage(input_tokens=10_000, output_tokens=2_000)
    cost = estimate_call_cost_usd(usage)
    # 10k in @ $3 + 2k out @ $15 = 0.03 + 0.03 = 0.06
    assert 0.05 < cost < 0.07


def test_estimate_call_cost_usd_with_cache_read():
    usage = FakeUsage(input_tokens=10_000, output_tokens=1_000, cache_read_input_tokens=8_000)
    cost = estimate_call_cost_usd(usage)
    assert cost > 0


def test_agent_scans_enabled_parses(monkeypatch):
    monkeypatch.setenv("AGENT_SCANS_ENABLED", "false")
    from importlib import reload
    import esm.claude_config as mod
    reload(mod)
    assert mod.AGENT_SCANS_ENABLED is False
