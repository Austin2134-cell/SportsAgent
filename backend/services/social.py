"""
Twitter/X thread generator for ESM daily cards.

Formats a card dict into a ready-to-post tweet thread.
Each element in the returned list is one tweet (≤ 280 chars).
Caller is responsible for posting via Twitter API v2 if wired up.
"""


_CONF_LABEL = {
    "HIGH":   "🔒",
    "MEDIUM": "🎯",
    "LEAN":   "📌",
    "FLYER":  "🎰",
}

_GRADE_LABEL = {
    "A": "🔥 ELITE",
    "B": "✅ STRONG",
    "C": "⚠️ PLAYABLE",
    "D": "🔻 THIN",
    "F": "🚫 NO PLAY",
}

_SPORT_EMOJI = {
    "SOCCER":  "⚽",
    "NBA":     "🏀",
    "MLB":     "⚾",
    "NHL":     "🏒",
    "NFL":     "🏈",
    "NCAAB":   "🏀",
}

HASHTAGS_WORLD_CUP = "#WorldCup2026 #WorldCupBetting #ESM #SoccerBetting"
HASHTAGS_DEFAULT   = "#SportsBetting #ESM #DailyCard"


def build_twitter_thread(card: dict, card_date: str = None) -> list[str]:
    """Return a list of tweet strings forming the daily card thread."""
    card_date = card_date or card.get("date", "today")
    plays = card.get("official_plays", [])
    leans = card.get("leans", [])
    grade = card.get("slate_grade", "?")
    grade_label = _GRADE_LABEL.get(grade, f"Grade {grade}")
    grade_note = card.get("slate_grade_note", "")

    is_world_cup = any(p.get("sport", "").upper() == "SOCCER" for p in plays + leans)
    hashtags = HASHTAGS_WORLD_CUP if is_world_cup else HASHTAGS_DEFAULT
    header_sport = "⚽ FIFA WORLD CUP 2026 ⚽" if is_world_cup else "🎯 ESM DAILY CARD"

    tweets = []

    # Tweet 1 — header + grade
    intro_lines = [
        f"{header_sport}",
        f"📅 {card_date}",
        "",
        f"Slate: {grade_label}",
    ]
    if grade_note:
        intro_lines.append(_truncate(grade_note, 100))
    intro_lines += ["", f"Card below 👇", "", hashtags]
    tweets.append("\n".join(intro_lines))

    # One tweet per official play
    for i, play in enumerate(plays, 1):
        sport = play.get("sport", "").upper()
        emoji = _SPORT_EMOJI.get(sport, "🎯")
        conf = play.get("confidence", "MEDIUM")
        conf_icon = _CONF_LABEL.get(conf, "🎯")
        odds = play.get("odds", 0)
        odds_str = f"+{odds}" if odds > 0 else str(odds)
        units = play.get("units", 2)
        bet = play.get("bet", "")
        game = play.get("game", "")
        summary = _truncate(play.get("edge_summary", ""), 120)

        tweet_lines = [
            f"{emoji} PLAY {i}/{len(plays)} {conf_icon} {conf}",
            f"{game}",
            f"",
            f"▶ {bet}",
            f"  {odds_str} · {units}u · {play.get('book','DraftKings')}",
            f"",
            _truncate(summary, 130),
        ]
        tweets.append("\n".join(tweet_lines))

    # Leans tweet (if any)
    if leans:
        lean_lines = ["📌 LEANS (lower conviction, smaller size):"]
        for lean in leans[:4]:
            odds = lean.get("odds", 0)
            odds_str = f"+{odds}" if odds > 0 else str(odds)
            sport = lean.get("sport", "")
            bet_text = _truncate(lean.get("bet", ""), 60)
            lean_lines.append(f"  {sport} — {bet_text} ({odds_str})")
        tweets.append("\n".join(lean_lines))

    # Quick reads tweet
    qr = card.get("quick_reads", [])
    if qr:
        qr_lines = ["🔑 QUICK READS:"]
        for item in qr[:4]:
            qr_lines.append(f"  → {_truncate(item, 90)}")
        tweets.append("\n".join(qr_lines))

    # Closer / CTA
    closer_lines = [
        "That's the card.",
        "",
        "Track this card & see full reasoning at EdgeBet.",
        "Follow for daily cards all tournament long.",
        "",
        hashtags,
    ]
    if is_world_cup:
        closer_lines.insert(0, "⚽ Let's get these W's at the World Cup. 🌍")
    else:
        closer_lines.insert(0, "Let's ride. Good luck today. 🤞")
    tweets.append("\n".join(closer_lines))

    # Enforce 280-char limit per tweet
    return [_enforce_limit(t) for t in tweets]


def format_thread_for_display(tweets: list[str]) -> str:
    """Pretty-print the thread for console or log output."""
    lines = ["=" * 60, "  TWITTER / X THREAD", "=" * 60]
    for i, tweet in enumerate(tweets, 1):
        lines.append(f"\n── Tweet {i}/{len(tweets)} ({len(tweet)} chars) ──")
        lines.append(tweet)
    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _enforce_limit(tweet: str, limit: int = 280) -> str:
    if len(tweet) <= limit:
        return tweet
    # Hard-trim to limit with ellipsis
    return tweet[:limit - 1] + "…"
