"""
memory.py — persistent performance profile for the EdgeBet agent.

Computes stats from graded bets and stores them in the agent_memory table.
Called by grader.py after each grading run and read by agent_runner.py
to inject historical context into the daily prompt.
"""

from datetime import date, timedelta

LOOKBACK_DAYS = 90


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


def get_performance_context(db, user_id: str) -> str:
    """Return a compact performance block for prompt injection, or empty string."""
    result = db.table("agent_memory").select("stats").eq("user_id", user_id).execute()
    if not result.data:
        return ""
    stats = result.data[0].get("stats") or {}
    return _format_for_prompt(stats)


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

    wins = losses = pushes = 0
    net_units = 0.0
    by_market: dict = {}
    by_sport: dict = {}
    by_confidence: dict = {}
    by_odds_bucket: dict = {}
    recent_losses: list = []

    for bet in bets:
        result_val = bet.get("result", "")
        units_result = float(bet.get("units_result", 0))
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
            })
        elif result_val == "P":
            pushes += 1

        _tally(by_market, market, result_val, units_result)
        _tally(by_sport, sport, result_val, units_result)
        _tally(by_confidence, confidence, result_val, units_result)
        _tally(by_odds_bucket, _odds_bucket(odds), result_val, units_result)

    played = wins + losses
    roi = round(net_units / played * 100, 1) if played > 0 else 0.0

    return {
        "lookback_days": LOOKBACK_DAYS,
        "total_bets": len(bets),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
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


def _format_for_prompt(stats: dict) -> str:
    if not stats:
        return ""

    sign = lambda n: ("+" if n >= 0 else "") + f"{n:.1f}"
    lines = [
        f"\n--- AGENT PERFORMANCE MEMORY ({stats.get('lookback_days', 90)}-day window) ---",
        f"Overall: {stats['wins']}-{stats['losses']}-{stats['pushes']} "
        f"| Net: {sign(stats['net_units'])}u | ROI: {stats['roi_pct']}%",
    ]

    # Market breakdown — only markets with 3+ resolved bets
    market_rows = [
        (m, r) for m, r in stats.get("by_market", {}).items()
        if r["W"] + r["L"] + r["P"] >= 3
    ]
    if market_rows:
        lines.append("By market:")
        for m, r in sorted(market_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {m}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    # Sport breakdown — 2+ bets
    sport_rows = [
        (s, r) for s, r in stats.get("by_sport", {}).items()
        if r["W"] + r["L"] + r["P"] >= 2
    ]
    if sport_rows:
        lines.append("By sport:")
        for s, r in sorted(sport_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {s}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    # Confidence tier breakdown
    conf_rows = []
    for tier in ("HIGH", "MEDIUM", "LOW"):
        r = stats.get("by_confidence", {}).get(tier)
        if r and r["W"] + r["L"] >= 2:
            conf_rows.append((tier, r))
    if conf_rows:
        lines.append("By confidence tier:")
        for tier, r in conf_rows:
            lines.append(f"  {tier}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    # Odds bucket breakdown
    bucket_rows = [
        (b, r) for b, r in stats.get("by_odds_bucket", {}).items()
        if r["W"] + r["L"] >= 3
    ]
    if bucket_rows:
        lines.append("By odds range:")
        for b, r in sorted(bucket_rows, key=lambda x: -(x[1]["W"] + x[1]["L"])):
            lines.append(f"  {b}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    # Last 5 losses — the agent should learn from these patterns
    recent_losses = stats.get("recent_losses", [])[-5:]
    if recent_losses:
        lines.append("Recent losses (identify patterns to avoid):")
        for loss in recent_losses:
            lines.append(
                f"  {loss['date']} | {loss['sport']} | {loss['market']} "
                f"| {loss['bet']} (odds: {loss['odds']})"
            )

    lines.append(
        "Use this data to weight markets/sports/confidence tiers where ROI is positive "
        "and avoid repeating losing patterns. Do NOT mechanically exclude weak markets — "
        "use this as a calibration signal."
    )

    return "\n".join(lines)
