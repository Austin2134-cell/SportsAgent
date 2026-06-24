"""
memory.py — persistent performance profile for the EdgeBet agent.

Computes stats from graded bets and stores them in the agent_memory table.
Called by grader.py after each grading run and read by agent_runner.py
to inject historical context into the daily prompt.
"""

from datetime import date, timedelta

from services.units import normalize_units_result

LOOKBACK_DAYS = 90
PIPELINE_TAGS = ("agent", "esm", "world_cup")


def refresh_memory(db, user_id: str) -> None:
    """Recompute and store performance stats for one user."""
    try:
        stats = _compute_stats(db, user_id)
        db.table("agent_memory").upsert(
            {"user_id": user_id, "stats": stats, "updated_at": date.today().isoformat()},
            on_conflict="user_id",
        ).execute()
    except Exception as e:
        print(f"[memory] Error refreshing memory for {user_id}: {e}")


def refresh_memory_all_users(db) -> dict:
    """Recompute agent_memory for every user with at least one graded bet."""
    users_result = db.table("bets").select("user_id").neq("result", "pending").execute()
    user_ids = sorted({row["user_id"] for row in (users_result.data or []) if row.get("user_id")})
    for uid in user_ids:
        refresh_memory(db, uid)
    return {"users_refreshed": len(user_ids)}


def get_performance_context(db, user_id: str, pipeline: str | None = "agent") -> str:
    """Return a compact performance block for prompt injection, or empty string."""
    result = db.table("agent_memory").select("stats").eq("user_id", user_id).execute()
    if not result.data:
        return ""
    stats = result.data[0].get("stats") or {}
    return _format_for_prompt(stats, pipeline=pipeline)


def _pipeline_key(bet: dict) -> str:
    tag = (bet.get("post_slate_tag") or "").strip().lower()
    if tag in PIPELINE_TAGS:
        return tag
    return "other"


def _compute_stats(db, user_id: str) -> dict:
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    result = (
        db.table("bets").select("*")
        .eq("user_id", user_id)
        .neq("result", "pending")
        .gte("date", cutoff)
        .execute()
    )
    bets = result.data or []
    if not bets:
        return {}

    overall = _aggregate_bets(bets)
    by_pipeline: dict = {}
    for key in (*PIPELINE_TAGS, "other"):
        pipeline_bets = [b for b in bets if _pipeline_key(b) == key]
        if pipeline_bets:
            by_pipeline[key] = _aggregate_bets(pipeline_bets)

    return {
        "lookback_days": LOOKBACK_DAYS,
        **overall,
        "by_pipeline": by_pipeline,
    }


def _aggregate_bets(bets: list) -> dict:
    wins = losses = pushes = 0
    net_units = 0.0
    units_risked_total = 0.0
    by_market: dict = {}
    by_sport: dict = {}
    by_confidence: dict = {}
    by_odds_bucket: dict = {}
    recent_losses: list = []

    for bet in bets:
        result_val = bet.get("result", "")
        units_risked = float(bet.get("units") or 0)
        units_risked_total += units_risked
        units_result = normalize_units_result(bet)
        market = bet.get("market", "unknown")
        sport = bet.get("sport", "unknown")
        confidence = (bet.get("confidence") or "MEDIUM").upper()
        odds = int(bet.get("odds", -110))

        if result_val == "W":
            wins += 1
            net_units += units_result
        elif result_val == "L":
            losses += 1
            net_units += units_result
            recent_losses.append({
                "date": bet.get("date", ""),
                "sport": sport,
                "market": market,
                "bet": bet.get("bet", ""),
                "odds": odds,
                "pipeline": _pipeline_key(bet),
            })
        elif result_val == "P":
            pushes += 1

        _tally(by_market, market, result_val, units_result)
        _tally(by_sport, sport, result_val, units_result)
        _tally(by_confidence, confidence, result_val, units_result)
        _tally(by_odds_bucket, _odds_bucket(odds), result_val, units_result)

    roi = round(net_units / units_risked_total * 100, 1) if units_risked_total > 0 else 0.0

    return {
        "total_bets": len(bets),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "units_risked": round(units_risked_total, 2),
        "net_units": round(net_units, 2),
        "roi_pct": roi,
        "by_market": by_market,
        "by_sport": by_sport,
        "by_confidence": by_confidence,
        "by_odds_bucket": by_odds_bucket,
        "recent_losses": recent_losses[-10:],
    }


def _tally(bucket: dict, key: str, result_val: str, units_result: float) -> None:
    rec = bucket.setdefault(key, {"W": 0, "L": 0, "P": 0, "net": 0.0})
    if result_val in rec:
        rec[result_val] += 1
    rec["net"] = round(rec["net"] + units_result, 2)


def _odds_bucket(odds: int) -> str:
    if odds <= -200:
        return "heavy_fav (≤-200)"
    if odds <= -150:
        return "big_fav (-150 to -200)"
    if odds <= -110:
        return "fav (-110 to -150)"
    if odds <= 100:
        return "pick (-110 to +100)"
    if odds <= 150:
        return "dog (+100 to +150)"
    return "big_dog (>+150)"


def _format_for_prompt(stats: dict, pipeline: str | None = "agent") -> str:
    if not stats:
        return ""

    sign = lambda n: ("+" if n >= 0 else "") + f"{n:.1f}"
    lookback = stats.get("lookback_days", 90)
    lines = [f"\n--- AGENT PERFORMANCE MEMORY ({lookback}-day window) ---"]

    by_pipeline = stats.get("by_pipeline") or {}
    if pipeline and pipeline in by_pipeline:
        lines.extend(_format_summary_block(by_pipeline[pipeline], f"{pipeline.upper()} pipeline", sign))
        lines.append("")
        lines.extend(_format_breakdowns(by_pipeline[pipeline], sign, recent_label="Recent losses (this pipeline):"))
        lines.append("")
        lines.append(
            f"Overall (all pipelines): {stats['wins']}-{stats['losses']}-{stats['pushes']} "
            f"| Net: {sign(stats['net_units'])}u | ROI: {stats['roi_pct']}%"
        )
    else:
        lines.extend(_format_summary_block(stats, "Overall", sign))

    if not pipeline or pipeline not in by_pipeline:
        lines.extend(_format_breakdowns(stats, sign))

    # Cross-pipeline snapshot when viewing agent context
    if pipeline == "agent" and len(by_pipeline) > 1:
        lines.append("Pipeline summary:")
        for key in (*PIPELINE_TAGS, "other"):
            block = by_pipeline.get(key)
            if not block:
                continue
            label = key if key != "other" else "untagged"
            lines.append(
                f"  {label}: {block['wins']}-{block['losses']}-{block['pushes']} "
                f"({sign(block['net_units'])}u, ROI {block['roi_pct']}%)"
            )

    lines.append(
        "Use this data to weight markets/sports/confidence tiers where ROI is positive "
        "and avoid repeating losing patterns. Prefer your own pipeline stats when calibrating. "
        "Do NOT mechanically exclude weak markets — use this as a calibration signal."
    )

    return "\n".join(lines)


def _format_summary_block(block: dict, label: str, sign) -> list[str]:
    return [
        f"{label}: {block['wins']}-{block['losses']}-{block['pushes']} "
        f"| Net: {sign(block['net_units'])}u | ROI: {block['roi_pct']}% "
        f"({block['total_bets']} bets)",
    ]


def _format_breakdowns(block: dict, sign, recent_label: str = "Recent losses (identify patterns to avoid):") -> list[str]:
    lines: list[str] = []

    market_rows = [
        (m, r) for m, r in block.get("by_market", {}).items()
        if r["W"] + r["L"] + r["P"] >= 3
    ]
    if market_rows:
        lines.append("By market:")
        for m, r in sorted(market_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {m}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    sport_rows = [
        (s, r) for s, r in block.get("by_sport", {}).items()
        if r["W"] + r["L"] + r["P"] >= 2
    ]
    if sport_rows:
        lines.append("By sport:")
        for s, r in sorted(sport_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {s}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    conf_rows = []
    for tier in ("HIGH", "MEDIUM", "LOW"):
        r = block.get("by_confidence", {}).get(tier)
        if r and r["W"] + r["L"] >= 2:
            conf_rows.append((tier, r))
    if conf_rows:
        lines.append("By confidence tier:")
        for tier, r in conf_rows:
            lines.append(f"  {tier}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    bucket_rows = [
        (b, r) for b, r in block.get("by_odds_bucket", {}).items()
        if r["W"] + r["L"] >= 3
    ]
    if bucket_rows:
        lines.append("By odds range:")
        for b, r in sorted(bucket_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {b}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    recent_losses = block.get("recent_losses", [])[-5:]
    if recent_losses:
        lines.append(recent_label)
        for loss in recent_losses:
            pipe = loss.get("pipeline")
            pipe_note = f" [{pipe}]" if pipe and pipe != "agent" else ""
            lines.append(
                f"  {loss['date']} | {loss['sport']} | {loss['market']} "
                f"| {loss['bet']} (odds: {loss['odds']}){pipe_note}"
            )

    return lines
