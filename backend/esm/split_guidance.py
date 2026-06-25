"""Shared prompt text for interpreting Action Network public/money splits."""

SPLIT_INTERPRETATION_GUIDANCE = """
SPLIT INTERPRETATION (when MARKET INTELLIGENCE includes public/money %):
• Decision order stays: fundamentals → true_prob_pct, then market intel, then posted price → implied_prob_pct.
• Splits confirm or fade — they never replace fundamentals or create edge by themselves.
• Ticket % (public bets) vs money % (handle):
  - Ticket % much higher than money % on a side → recreational/public heavy; fade candidate if your model disagrees.
  - Money % much higher than ticket % → sharp/big-money signal; confirmation if fundamentals agree.
• Reverse line (flagged): public heavy on one side but line moved toward the other — respect the price action.
• Totals: 70%+ public on Over + you like Under = classic contrarian setup — state it in edge_summary.
  70%+ public on Under + you like Over = same, reversed.
• Game lines (ML/spread/total) splits apply to game-level bets; player props have no prop-level split feed —
  use game-level total/ML context only as secondary color, not as the prop edge.
• If splits missing for a game, rely on line movement flags and fundamentals only.
"""
