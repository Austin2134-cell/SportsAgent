"""
memory.py — dual-brain performance memory for AgentEdge.

Primary brain:  per-user agent_memory (this user's track record — calibrate here first)
Secondary brain: platform_memory (collective stats across all users — fill gaps only)
"""

from datetime import date, timedelta

from services.units import normalize_units_result

LOOKBACK_DAYS = 90
PIPELINE_TAGS = ("agent", "esm", "world_cup")
PLATFORM_MEMORY_KEY = "global"


# ── Refresh ───────────────────────────────────────────────────────────────────

def refresh_memory(db, user_id: str) -> None:
    """Recompute and store per-user performance stats (primary brain)."""
    try:
        stats = _compute_user_stats(db, user_id)
        db.table("agent_memory").upsert(
            {"user_id": user_id, "stats": stats, "updated_at": date.today().isoformat()},
            on_conflict="user_id",
        ).execute()
    except Exception as e:
        print(f"[memory] Error refreshing user memory for {user_id}: {e}")


def refresh_platform_memory(db) -> None:
    """Recompute and store platform-wide collective stats (secondary brain)."""
    try:
        stats = _compute_platform_stats(db)
        db.table("platform_memory").upsert(
            {
                "key": PLATFORM_MEMORY_KEY,
                "stats": stats,
                "updated_at": date.today().isoformat(),
            },
            on_conflict="key",
        ).execute()
    except Exception as e:
        print(f"[memory] Error refreshing platform memory: {e}")


def refresh_memory_all_users(db) -> dict:
    """Recompute user memory for all users with graded bets + platform brain."""
    users_result = db.table("bets").select("user_id").neq("result", "pending").execute()
    user_ids = sorted({row["user_id"] for row in (users_result.data or []) if row.get("user_id")})
    for uid in user_ids:
        refresh_memory(db, uid)
    refresh_platform_memory(db)
    return {"users_refreshed": len(user_ids), "platform_refreshed": True}


# ── Prompt injection ──────────────────────────────────────────────────────────

def get_performance_context(db, user_id: str, pipeline: str | None = "agent") -> str:
    """
    Return dual-brain performance block for prompt injection.
    Primary (user) first; secondary (platform) follows.
    """
    parts: list[str] = []

    user_result = db.table("agent_memory").select("stats").eq("user_id", user_id).execute()
    user_stats = user_result.data[0].get("stats") if user_result.data else {}
    if user_stats:
        parts.append(_format_user_memory(user_stats, pipeline=pipeline))
    else:
        parts.append(
            "\n--- YOUR MEMORY (PRIMARY) ---\n"
            "No graded bet history for this user yet — rely on platform brain below "
            "until user-specific data accumulates."
        )

    platform_result = (
        db.table("platform_memory")
        .select("stats")
        .eq("key", PLATFORM_MEMORY_KEY)
        .execute()
    )
    platform_stats = platform_result.data[0].get("stats") if platform_result.data else {}
    if not platform_stats:
        platform_stats = _compute_platform_stats(db)

    if platform_stats:
        parts.append(_format_platform_memory(platform_stats, pipeline=pipeline))

    return "\n".join(parts)


# ── Stats computation ─────────────────────────────────────────────────────────

def _pipeline_key(bet: dict) -> str:
    tag = (bet.get("post_slate_tag") or "").strip().lower()
    if tag in PIPELINE_TAGS:
        return tag
    return "other"


def _compute_user_stats(db, user_id: str) -> dict:
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

    overall = _aggregate_bets(bets, include_recent_losses=True)
    by_pipeline: dict = {}
    for key in (*PIPELINE_TAGS, "other"):
        pipeline_bets = [b for b in bets if _pipeline_key(b) == key]
        if pipeline_bets:
            by_pipeline[key] = _aggregate_bets(pipeline_bets, include_recent_losses=True)

    return {
        "lookback_days": LOOKBACK_DAYS,
        "scope": "user",
        **overall,
        "by_pipeline": by_pipeline,
    }


def _compute_platform_stats(db) -> dict:
    cutoff = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    result = (
        db.table("bets").select("*")
        .neq("result", "pending")
        .gte("date", cutoff)
        .execute()
    )
    bets = result.data or []
    if not bets:
        return {}

    user_ids = {b["user_id"] for b in bets if b.get("user_id")}
    overall = _aggregate_bets(bets, include_recent_losses=False)
    overall["weak_markets"] = _weak_markets_platform(bets, min_bets=5)

    by_pipeline: dict = {}
    for key in (*PIPELINE_TAGS, "other"):
        pipeline_bets = [b for b in bets if _pipeline_key(b) == key]
        if pipeline_bets:
            block = _aggregate_bets(pipeline_bets, include_recent_losses=False)
            block["weak_markets"] = _weak_markets_platform(pipeline_bets, min_bets=5)
            by_pipeline[key] = block

    return {
        "lookback_days": LOOKBACK_DAYS,
        "scope": "platform",
        "active_users": len(user_ids),
        **overall,
        "by_pipeline": by_pipeline,
    }


def _aggregate_bets(bets: list, *, include_recent_losses: bool) -> dict:
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
            if include_recent_losses:
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

    out = {
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
    }
    if include_recent_losses:
        out["recent_losses"] = recent_losses[-10:]
    return out


def _weak_markets_platform(bets: list, min_bets: int = 5) -> list:
    """Anonymized market-level underperformance for platform brain (no user bet text)."""
    by_market: dict = {}
    for bet in bets:
        market = bet.get("market", "unknown")
        result_val = bet.get("result", "")
        units_result = normalize_units_result(bet)
        _tally(by_market, market, result_val, units_result)

    weak = []
    for market, rec in by_market.items():
        total = rec["W"] + rec["L"] + rec["P"]
        if total < min_bets:
            continue
        if rec["net"] < 0:
            weak.append({
                "market": market,
                "record": f"{rec['W']}-{rec['L']}",
                "net_units": rec["net"],
            })
    weak.sort(key=lambda x: x["net_units"])
    return weak[:8]


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


# ── Formatting ────────────────────────────────────────────────────────────────

def _format_user_memory(stats: dict, pipeline: str | None = "agent") -> str:
    if not stats:
        return ""

    sign = lambda n: ("+" if n >= 0 else "") + f"{n:.1f}"
    lookback = stats.get("lookback_days", 90)
    lines = [
        f"\n--- YOUR MEMORY (PRIMARY — {lookback}-day window, this user only) ---",
        "Calibrate sizing, market selection, and pass discipline from THIS block first.",
    ]

    by_pipeline = stats.get("by_pipeline") or {}
    if pipeline and pipeline in by_pipeline:
        block = by_pipeline[pipeline]
        lines.extend(_format_summary_block(block, f"Your {pipeline.upper()} bets", sign))
        lines.append("")
        lines.extend(_format_breakdowns(
            block, sign,
            recent_label="Your recent losses (patterns to avoid for this user):",
        ))
        lines.append("")
        lines.append(
            f"Your all-pipeline record: {stats['wins']}-{stats['losses']}-{stats['pushes']} "
            f"| Net: {sign(stats['net_units'])}u | ROI: {stats['roi_pct']}%"
        )
    else:
        lines.extend(_format_summary_block(stats, "Your overall record", sign))
        lines.extend(_format_breakdowns(stats, sign, recent_label="Your recent losses:"))

    if pipeline == "agent" and len(by_pipeline) > 1:
        lines.append("Your pipeline breakdown:")
        for key in (*PIPELINE_TAGS, "other"):
            block = by_pipeline.get(key)
            if not block:
                continue
            label = key if key != "other" else "untagged"
            lines.append(
                f"  {label}: {block['wins']}-{block['losses']}-{block['pushes']} "
                f"({sign(block['net_units'])}u, ROI {block['roi_pct']}%)"
            )

    return "\n".join(lines)


def _format_platform_memory(stats: dict, pipeline: str | None = "agent") -> str:
    if not stats:
        return ""

    sign = lambda n: ("+" if n >= 0 else "") + f"{n:.1f}"
    lookback = stats.get("lookback_days", 90)
    users = stats.get("active_users", 0)
    lines = [
        f"\n--- PLATFORM AGENT BRAIN (SECONDARY — collective {lookback}-day intelligence) ---",
        f"Aggregated across {users} active user(s) and {stats.get('total_bets', 0)} graded bets.",
        "Use this to fill gaps when the user's sample is thin (<3 bets in a market).",
        "When user memory and platform brain conflict, ALWAYS trust the user's own history.",
    ]

    by_pipeline = stats.get("by_pipeline") or {}
    if pipeline and pipeline in by_pipeline:
        block = by_pipeline[pipeline]
        lines.extend(_format_summary_block(block, f"Platform {pipeline.upper()} pipeline", sign))
        lines.extend(_format_platform_breakdowns(block, sign))
    else:
        lines.extend(_format_summary_block(stats, "Platform overall", sign))
        lines.extend(_format_platform_breakdowns(stats, sign))

    if pipeline and pipeline in by_pipeline and len(by_pipeline) > 1:
        lines.append("Platform pipeline summary:")
        for key in (*PIPELINE_TAGS, "other"):
            block = by_pipeline.get(key)
            if not block:
                continue
            label = key if key != "other" else "untagged"
            lines.append(
                f"  {label}: {block['wins']}-{block['losses']}-{block['pushes']} "
                f"({sign(block['net_units'])}u, ROI {block['roi_pct']}%)"
            )

    return "\n".join(lines)


def _format_summary_block(block: dict, label: str, sign) -> list[str]:
    return [
        f"{label}: {block['wins']}-{block['losses']}-{block['pushes']} "
        f"| Net: {sign(block['net_units'])}u | ROI: {block['roi_pct']}% "
        f"({block['total_bets']} bets)",
    ]


def _format_breakdowns(
    block: dict,
    sign,
    recent_label: str = "Recent losses (identify patterns to avoid):",
) -> list[str]:
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
            pipe_note = f" [{pipe}]" if pipe else ""
            lines.append(
                f"  {loss['date']} | {loss['sport']} | {loss['market']} "
                f"| {loss['bet']} (odds: {loss['odds']}){pipe_note}"
            )

    return lines


def _format_platform_breakdowns(block: dict, sign) -> list[str]:
    """Platform brain: anonymized aggregates only — no individual user bet text."""
    lines: list[str] = []

    market_rows = [
        (m, r) for m, r in block.get("by_market", {}).items()
        if r["W"] + r["L"] + r["P"] >= 5
    ]
    if market_rows:
        lines.append("Platform by market (5+ bets):")
        for m, r in sorted(market_rows, key=lambda x: -(x[1]["W"] + x[1]["L"]))[:8]:
            lines.append(f"  {m}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    sport_rows = [
        (s, r) for s, r in block.get("by_sport", {}).items()
        if r["W"] + r["L"] + r["P"] >= 5
    ]
    if sport_rows:
        lines.append("Platform by sport (5+ bets):")
        for s, r in sorted(sport_rows, key=lambda x: -(x[1]["W"] + x[1]["L"]))[:6]:
            lines.append(f"  {s}: {r['W']}-{r['L']} ({sign(r['net'])}u)")

    weak = block.get("weak_markets") or []
    if weak:
        lines.append("Platform weak markets (collective underperformance):")
        for row in weak[:5]:
            lines.append(
                f"  {row['market']}: {row['record']} ({sign(row['net_units'])}u)"
            )

    return lines


# Backward-compatible alias for tests
_compute_stats = _compute_user_stats
_format_for_prompt = _format_user_memory
