"""Shared prompt text for interpreting Action Network public/money splits."""

SPLIT_INTERPRETATION_GUIDANCE = """
SPLIT INTERPRETATION (when MARKET INTELLIGENCE includes public/money %):
• Decision order stays: fundamentals → true_prob_pct, then market intel, then posted price → implied_prob_pct.
• Splits confirm or fade — they never replace fundamentals or create edge by themselves.
• Ticket % (public bets) vs money % (handle):
  - Ticket % much higher than money % on a side → recreational/public heavy; fade candidate if your model disagrees.
  - Money % much higher than ticket % → sharp/big-money signal; confirmation if fundamentals agree.
• Reverse line (flagged): public heavy on one side but line moved toward the other — respect the price action.
• Totals splits: heavy public on one side (70%+) is context only — note in edge_summary if it
  confirms or contradicts your fundamental total read; never pick Over or Under solely because
  of ticket %.
• Game lines (ML/spread/total) splits apply to game-level bets; player props have no prop-level split feed —
  use game-level total/ML context only as secondary color, not as the prop edge.
• If splits missing for a game, rely on line movement flags and fundamentals only.
"""
