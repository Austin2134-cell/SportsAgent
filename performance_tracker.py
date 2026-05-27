"""
performance_tracker.py — ESM adaptive learning engine.

Reads bet history, computes win rates across multiple dimensions, and generates
a performance intelligence report that gets injected into Claude's daily prompt.

Dimensions tracked:
  - market type (pitcher_strikeouts, batter_hits, etc.)
  - juice bucket (very_neg, negative, near_even, positive, very_pos)
  - line tier (for K lines: 4.5, 5.5, 6.5, 7.5+)
  - sport (MLB, NBA, NHL)
  - market + juice combined (most predictive)
  - rolling 14-day window vs all-time

Auto-rules:
  - SKIP: market+juice combo < 40% win rate on 10+ bets
  - BOOST: market+juice combo > 60% win rate on 10+ bets
  - WARNING: 0-3 or worse active streak in any dimension
"""

import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

BETS_CSV = Path(__file__).parent / "data" / "bets.csv"
MIN_SAMPLE = 10       # minimum bets before a dimension influences decisions
FULL_CONFIDENCE = 25  # sample size for full edge weight
COLD_THRESHOLD = 0.40 # below this → auto-skip rule
HOT_THRESHOLD = 0.60  # above this → boost signal


# ── Juice bucketing ──────────────────────────────────────────────────────────

def juice_bucket(odds: int) -> str:
    """Categorize American odds into a named bucket."""
    if odds <= -151:
        return "heavy_neg"      # -150 or worse (usually avoid)
    elif odds <= -121:
        return "negative"       # -150 to -121
    elif odds <= -101:
        return "near_neg"       # -120 to -101
    elif odds <= 100:
        return "near_even"      # -100 to +100
    elif odds <= 120:
        return "positive"       # +101 to +120
    else:
        return "very_pos"       # +121 and better

JUICE_LABELS = {
    "heavy_neg":  "≤-150",
    "negative":   "-149 to -121",
    "near_neg":   "-120 to -101",
    "near_even":  "-100 to +100",
    "positive":   "+101 to +120",
    "very_pos":   "+121 or better",
}


def line_tier(market: str, bet: str) -> Optional[str]:
    """
    Extract line tier for prop markets.
    e.g. 'Over 5.5 Strikeouts' → '5.5'
    """
    import re
    m = re.search(r'over\s+([\d.]+)', bet, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    if market == "pitcher_strikeouts":
        if val <= 4.5:   return "K_4.5"
        elif val <= 5.5: return "K_5.5"
        elif val <= 6.5: return "K_6.5"
        else:            return "K_7.5+"
    elif market == "pitcher_outs":
        if val <= 15.5:  return "outs_15.5"
        elif val <= 17.5: return "outs_17.5"
        else:            return "outs_18.5+"
    elif market in ("batter_hits",):
        return f"hits_{val}"
    elif market in ("batter_total_bases",):
        return f"bases_{val}"
    return None


# ── Data loading ─────────────────────────────────────────────────────────────

def load_graded_bets(days_back: int = None) -> list[dict]:
    """Load all graded (non-pending) bets from CSV."""
    if not BETS_CSV.exists():
        return []

    cutoff = None
    if days_back:
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()

    rows = []
    with open(BETS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["result"] not in ("W", "L"):
                continue  # skip pending and pushes
            if cutoff and row["date"] < cutoff:
                continue
            try:
                row["_odds"] = int(float(row.get("odds") or -110))
                row["_units"] = float(row.get("units") or 2)
                row["_units_result"] = float(row.get("units_result") or 0)
                row["_juice_bucket"] = juice_bucket(row["_odds"])
                row["_line_tier"] = line_tier(row.get("market",""), row.get("bet",""))
            except (ValueError, TypeError):
                continue
            rows.append(row)

    return rows


# ── Stats computation ─────────────────────────────────────────────────────────

class DimStats:
    def __init__(self):
        self.wins = 0
        self.losses = 0
        self.net_units = 0.0

    def add(self, result: str, units_result: float):
        if result == "W":
            self.wins += 1
        else:
            self.losses += 1
        self.net_units += units_result

    @property
    def total(self): return self.wins + self.losses

    @property
    def win_rate(self): return self.wins / self.total if self.total > 0 else None

    @property
    def has_data(self): return self.total >= MIN_SAMPLE

    def edge_score(self) -> float:
        """
        Returns edge score: positive = above break-even, negative = below.
        Scaled by sample confidence (0→1 over MIN_SAMPLE→FULL_CONFIDENCE bets).
        """
        if not self.win_rate:
            return 0.0
        raw_edge = self.win_rate - 0.52  # 52% ≈ break-even for -110 juice
        confidence = min(1.0, (self.total - MIN_SAMPLE) / (FULL_CONFIDENCE - MIN_SAMPLE))
        confidence = max(0.0, confidence)
        return round(raw_edge * confidence, 3)

    def streak(self, results: list[str]) -> str:
        """Return current streak string, e.g. 'L3' or 'W4'."""
        if not results:
            return ""
        cur = results[-1]
        count = 0
        for r in reversed(results):
            if r == cur:
                count += 1
            else:
                break
        return f"{cur}{count}"

    def summary(self) -> str:
        if self.total == 0:
            return "No data"
        wr = self.win_rate
        sign = "+" if self.net_units >= 0 else ""
        return f"{self.wins}W-{self.losses}L ({wr:.0%}) | {sign}{self.net_units:.1f}u"


def compute_stats(bets: list[dict]) -> dict[str, dict[str, DimStats]]:
    """
    Returns nested dict: {dimension_name: {dimension_value: DimStats}}
    """
    dims = {
        "market": defaultdict(DimStats),
        "juice_bucket": defaultdict(DimStats),
        "line_tier": defaultdict(DimStats),
        "sport": defaultdict(DimStats),
        "market_juice": defaultdict(DimStats),   # combined
        "market_line": defaultdict(DimStats),    # combined
    }

    for bet in bets:
        result = bet["result"]
        ur = bet["_units_result"]
        mkt = bet.get("market", "unknown")
        jb = bet["_juice_bucket"]
        lt = bet["_line_tier"]
        sport = bet.get("sport", "unknown")

        dims["market"][mkt].add(result, ur)
        dims["juice_bucket"][jb].add(result, ur)
        dims["sport"][sport].add(result, ur)
        dims["market_juice"][f"{mkt}|{jb}"].add(result, ur)

        if lt:
            dims["line_tier"][lt].add(result, ur)
            dims["market_line"][f"{mkt}|{lt}"].add(result, ur)

    return dims


# ── Rule generation ───────────────────────────────────────────────────────────

def generate_rules(dims: dict) -> dict:
    """
    Returns:
      skip_rules: list of (key, label, stats) — markets to avoid
      boost_rules: list of (key, label, stats) — markets to prioritize
    """
    skip_rules = []
    boost_rules = []

    for dim_name, dim_data in dims.items():
        for key, stats in dim_data.items():
            if not stats.has_data:
                continue
            wr = stats.win_rate
            if wr is not None and wr < COLD_THRESHOLD:
                skip_rules.append((dim_name, key, stats))
            elif wr is not None and wr > HOT_THRESHOLD:
                boost_rules.append((dim_name, key, stats))

    # Sort by severity
    skip_rules.sort(key=lambda x: x[2].win_rate)
    boost_rules.sort(key=lambda x: -x[2].win_rate)

    return {"skip": skip_rules, "boost": boost_rules}


def detect_streaks(bets: list[dict]) -> list[dict]:
    """Find active cold streaks (3+ losses in a row) in any tracked dimension."""
    # Group bets by dimension value, sorted by date
    groups = defaultdict(list)
    for bet in sorted(bets, key=lambda x: x["date"]):
        mkt = bet.get("market", "?")
        jb = bet["_juice_bucket"]
        groups[f"{mkt}"].append(bet["result"])
        groups[f"{mkt}|{jb}"].append(bet["result"])
        groups[f"sport:{bet.get('sport','?')}"].append(bet["result"])

    streaks = []
    for key, results in groups.items():
        if len(results) < 3:
            continue
        tail = results[-3:]
        if all(r == "L" for r in tail):
            count = 0
            for r in reversed(results):
                if r == "L": count += 1
                else: break
            streaks.append({"key": key, "streak": f"L{count}", "last_n": results[-5:]})

    return streaks


# ── Main report ───────────────────────────────────────────────────────────────

def get_performance_report(include_raw: bool = False) -> str:
    """
    Generate the full performance intelligence section for injection
    into Claude's daily prompt.
    """
    all_bets = load_graded_bets()
    recent_bets = load_graded_bets(days_back=30)

    total_graded = len(all_bets)

    if total_graded == 0:
        return (
            "\n--- MODEL PERFORMANCE INTELLIGENCE ---\n"
            "Tracking started fresh. No graded bets yet.\n"
            "Apply standard ESM framework — no historical adjustments active.\n"
        )

    lines = ["\n--- MODEL PERFORMANCE INTELLIGENCE ---"]
    lines.append(f"Total graded: {total_graded} bets | Last 30 days: {len(recent_bets)} bets")

    # Overall record
    wins = sum(1 for b in all_bets if b["result"] == "W")
    losses = total_graded - wins
    net = sum(b["_units_result"] for b in all_bets)
    wagered = sum(b["_units"] for b in all_bets)
    roi = (net / wagered * 100) if wagered else 0
    sign = "+" if net >= 0 else ""
    lines.append(f"Overall: {wins}W-{losses}L ({wins/total_graded:.0%}) | {sign}{net:.1f}u | ROI {roi:+.1f}%")

    # Compute stats on recent bets (for rules) and all-time (for context)
    dims_recent = compute_stats(recent_bets) if recent_bets else compute_stats(all_bets)
    dims_all = compute_stats(all_bets)
    rules = generate_rules(dims_recent)
    streaks = detect_streaks(all_bets)

    # ── AUTO-SKIP RULES ──────────────────────────────────────────────────────
    if rules["skip"]:
        lines.append("\n⛔ AUTO-SKIP RULES (below 40% threshold — avoid unless +150 or better):")
        for dim_name, key, stats in rules["skip"][:5]:
            label = _format_key(dim_name, key)
            lines.append(f"  • {label}: {stats.summary()}")
    else:
        lines.append("\n⛔ AUTO-SKIP RULES: None active yet.")

    # ── BOOST SIGNALS ────────────────────────────────────────────────────────
    if rules["boost"]:
        lines.append("\n✅ BOOST SIGNALS (above 60% — prioritize these markets):")
        for dim_name, key, stats in rules["boost"][:5]:
            label = _format_key(dim_name, key)
            lines.append(f"  • {label}: {stats.summary()}")
    else:
        lines.append("\n✅ BOOST SIGNALS: None active yet.")

    # ── ACTIVE COLD STREAKS ───────────────────────────────────────────────────
    if streaks:
        lines.append("\n🔴 ACTIVE COLD STREAKS (3+ consecutive losses):")
        for s in streaks[:4]:
            lines.append(f"  • {s['key']}: {s['streak']} — last 5: {s['last_n']}")
    else:
        lines.append("\n🔴 ACTIVE COLD STREAKS: None.")

    # ── MARKET BREAKDOWN (sufficient sample only) ─────────────────────────────
    lines.append("\n📊 MARKET PERFORMANCE (10+ bets):")
    shown = 0
    for mkt, stats in sorted(dims_all["market"].items(), key=lambda x: -(x[1].total)):
        if stats.has_data:
            edge = stats.edge_score()
            edge_label = f"  [edge: {edge:+.2f}]" if stats.total >= MIN_SAMPLE else ""
            lines.append(f"  {mkt}: {stats.summary()}{edge_label}")
            shown += 1
    if shown == 0:
        lines.append("  Building sample — need 10+ graded bets per market.")

    # ── JUICE PERFORMANCE ────────────────────────────────────────────────────
    lines.append("\n📊 JUICE RANGE PERFORMANCE (10+ bets):")
    shown = 0
    for jb, stats in sorted(dims_all["juice_bucket"].items(), key=lambda x: -(x[1].total)):
        if stats.has_data:
            lines.append(f"  {JUICE_LABELS.get(jb, jb)}: {stats.summary()}")
            shown += 1
    if shown == 0:
        lines.append("  Building sample.")

    # ── INSTRUCTIONS FOR CLAUDE ───────────────────────────────────────────────
    lines.append("""
⚙️  HOW TO USE THIS DATA:
  1. AUTO-SKIP markets listed above — do not make them official plays
  2. Apply BOOST SIGNALS — these are proven edges, weight them higher
  3. Avoid markets in active cold streaks unless edge is exceptional (+150 or better)
  4. Markets with no data: use standard ESM framework rules
  5. Edge score > +0.10 = strong historical edge. < -0.10 = avoid.
""")

    return "\n".join(lines)


def _format_key(dim_name: str, key: str) -> str:
    """Make dimension keys human-readable."""
    if "|" in key:
        parts = key.split("|")
        if dim_name == "market_juice":
            return f"{parts[0]} @ {JUICE_LABELS.get(parts[1], parts[1])}"
        return " | ".join(parts)
    if dim_name == "juice_bucket":
        return f"Juice {JUICE_LABELS.get(key, key)}"
    return key


# ── Play scorer ───────────────────────────────────────────────────────────────

def score_play(market: str, odds: int, bet: str, sport: str) -> dict:
    """
    Score a specific potential play against historical performance.
    Returns a dict with edge_score, signal, and reasoning.
    Used internally — not injected into prompt directly.
    """
    all_bets = load_graded_bets()
    if not all_bets:
        return {"edge": 0.0, "signal": "neutral", "reason": "No history yet"}

    dims = compute_stats(all_bets)
    jb = juice_bucket(odds)
    lt = line_tier(market, bet)

    scores = []
    reasons = []

    # Market score
    mkt_stats = dims["market"].get(market)
    if mkt_stats and mkt_stats.has_data:
        scores.append(mkt_stats.edge_score())
        reasons.append(f"{market}: {mkt_stats.win_rate:.0%} ({mkt_stats.total} bets)")

    # Market+juice score (most predictive)
    mj_key = f"{market}|{jb}"
    mj_stats = dims["market_juice"].get(mj_key)
    if mj_stats and mj_stats.has_data:
        scores.append(mj_stats.edge_score() * 1.5)  # weight this higher
        reasons.append(f"{market} @ {JUICE_LABELS.get(jb)}: {mj_stats.win_rate:.0%} ({mj_stats.total} bets)")

    # Line tier score
    if lt:
        lt_stats = dims["line_tier"].get(lt)
        if lt_stats and lt_stats.has_data:
            scores.append(lt_stats.edge_score())
            reasons.append(f"Line tier {lt}: {lt_stats.win_rate:.0%} ({lt_stats.total} bets)")

    if not scores:
        return {"edge": 0.0, "signal": "neutral", "reason": "Insufficient history for this play type"}

    avg_edge = sum(scores) / len(scores)

    if avg_edge > 0.10:
        signal = "strong_play"
    elif avg_edge > 0.03:
        signal = "lean_play"
    elif avg_edge < -0.10:
        signal = "avoid"
    elif avg_edge < -0.03:
        signal = "caution"
    else:
        signal = "neutral"

    return {
        "edge": round(avg_edge, 3),
        "signal": signal,
        "reason": " | ".join(reasons),
    }


if __name__ == "__main__":
    report = get_performance_report()
    print(report)
