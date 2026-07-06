"""Claude API model, token limits, and cost-control toggles."""

import os

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Output caps — JSON cards/scans rarely need 16k tokens; lower caps cut worst-case spend.
CARD_MAX_TOKENS = int(os.getenv("CLAUDE_CARD_MAX_TOKENS", "8192"))
AGENT_SCAN_MAX_TOKENS = int(os.getenv("CLAUDE_AGENT_SCAN_MAX_TOKENS", "4096"))

# Continuous agent scans are the largest Claude line item (~8/day × users).
# Set false on Railway until the product is profitable — daily cards still run on schedule.
AGENT_SCANS_ENABLED = os.getenv("AGENT_SCANS_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)

# Sonnet 4.6 list pricing (USD per million tokens) — for log estimates only.
INPUT_COST_PER_MTOK = float(os.getenv("CLAUDE_INPUT_COST_PER_MTOK", "3.0"))
OUTPUT_COST_PER_MTOK = float(os.getenv("CLAUDE_OUTPUT_COST_PER_MTOK", "15.0"))
CACHE_READ_COST_PER_MTOK = float(os.getenv("CLAUDE_CACHE_READ_COST_PER_MTOK", "0.30"))
CACHE_WRITE_COST_PER_MTOK = float(os.getenv("CLAUDE_CACHE_WRITE_COST_PER_MTOK", "3.75"))


def estimate_call_cost_usd(usage) -> float:
    """Rough USD from Anthropic usage object (for logging; not billing-grade)."""
    if usage is None:
        return 0.0
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    # Non-cached input = total input minus cache hits (approximate)
    plain_in = max(0, inp - cache_read)
    return (
        plain_in / 1_000_000 * INPUT_COST_PER_MTOK
        + cache_read / 1_000_000 * CACHE_READ_COST_PER_MTOK
        + cache_create / 1_000_000 * CACHE_WRITE_COST_PER_MTOK
        + out / 1_000_000 * OUTPUT_COST_PER_MTOK
    )


def log_claude_usage(caller: str, usage, *, extra: str = "") -> None:
    """Print token usage + estimated cost after every Claude call."""
    if usage is None:
        return
    cost = estimate_call_cost_usd(usage)
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    suffix = f" {extra}" if extra else ""
    print(
        f"[claude] {caller}: in={inp} out={out} "
        f"cache_read={cache_read} cache_create={cache_create} "
        f"~${cost:.4f}{suffix}"
    )
