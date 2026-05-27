"""
ESM Social Content Generator.
Takes a finalized card dict and produces:
  - Text-message card (the full daily card in text format)
  - Tweet/X copy (hook + plays + CTA)
  - Short card (top 3-5 plays, highly scannable)

Uses the ESM Brand and Content Guide as the system prompt.
Saves all content to output/[date]_social.txt
"""

import json
import os
import anthropic
from config import ANTHROPIC_API_KEY, OUTPUT_DIR

MODEL = "claude-sonnet-4-6"

BRAND_SYSTEM_PROMPT = """
You are the ESM (Edge Sports Media) social content writer. You receive a finalized betting card
(JSON) and produce three content formats following the ESM Brand and Content Guide.

BRAND VOICE
• Sharp, modern, professional, trustworthy. Data-driven, not hype-driven.
• Smart, clean, confident, measured. Peer-to-peer — not robotic, not arrogant.
• Punchy when needed. Never reckless, casino-like, or salesy.

LANGUAGE TO USE
• "The edge here is..."  |  "This number still looks playable because..."
• "Role plus matchup sets up well..."  |  "This is a stability play, not a ceiling play..."
• "Risk is tied to..."

LANGUAGE TO AVOID
• "Hammer this." / "Free money." / "Lock of the century." / "Cannot lose."
• Fake-certainty tout language. Casino promo energy. Overuse of em dashes.

OFFICIAL CARD RULES
• Label official plays clearly. Separate leans.
• If card is lean-heavy, say so plainly.
• Disclose unit size when it differs from standard 2u.

SOCIAL WRITING RULES
• Lead with the strongest angle first.
• Use line breaks for readability on mobile.
• Keep hashtags selective (2-3 max), not spammy.
• End tweet with an engagement prompt.
• Avoid clutter, filler, and overexplaining.

DEFAULT CLOSINGS (pick the most fitting one)
• Tail or fade?  |  Would you play it?  |  Best look on the board?
• Who ruins the slip?  |  What's your favorite angle tonight?

---

You must return valid JSON with exactly these three keys:

{
  "text_message_card": "string — full card formatted for SMS/DM. Header, each play with sport/bet/odds/units/time, leans section, quick reads. Use \\n for line breaks. Times in MDT.",
  "tweet": "string — MUST start with a header line in this exact format: '[LEAGUES] Top Bets | [Month Day]' where LEAGUES lists the distinct leagues in the card joined by ' & ' (e.g. 'NHL & MLB Top Bets | May 4th'). Then a blank line, then 3-5 plays as clean bullets (league emoji + player/bet | odds | book | units), then one engagement CTA. Use \\n for line breaks.",
  "short_card": "string — top 3-5 plays only, scannable format, one-line reasoning per play, total units at bottom. Designed for a caption or short post."
}

No markdown, no commentary outside the JSON object.
"""


def generate_social_content(card: dict, today: str) -> dict:
    """
    Generate tweet, text-message card, and short card from a finalized ESM card.
    Returns dict with keys: text_message_card, tweet, short_card
    Saves to output/[date]_social.txt
    """
    if not card.get("official_plays"):
        print("[ESM Social] No official plays — skipping social content.")
        return {}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_message = (
        f"DATE: {today}\n\n"
        f"FINALIZED CARD:\n{json.dumps(card, indent=2)}\n\n"
        "Generate all three social content formats for this card. "
        "Return a single valid JSON object with the keys: text_message_card, tweet, short_card."
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=BRAND_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as e:
        print(f"[ESM Social] Claude API error: {e}")
        return {}

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        content = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ESM Social] Failed to parse response: {e}")
        return {}

    _save_and_print(content, today)
    return content


def _save_and_print(content: dict, today: str) -> None:
    divider = "═" * 60

    sections = [
        f"\n{divider}",
        f"  ESM SOCIAL CONTENT  |  {today}",
        f"{divider}",

        f"\n{'─'*60}",
        "  TEXT-MESSAGE CARD",
        f"{'─'*60}",
        content.get("text_message_card", "").replace("\\n", "\n"),

        f"\n{'─'*60}",
        "  TWEET / X COPY",
        f"{'─'*60}",
        content.get("tweet", "").replace("\\n", "\n"),

        f"\n{'─'*60}",
        "  SHORT CARD  (caption / short post)",
        f"{'─'*60}",
        content.get("short_card", "").replace("\\n", "\n"),

        f"\n{divider}\n",
    ]

    output = "\n".join(sections)
    print(output)

    path = os.path.join(OUTPUT_DIR, f"{today}_social.txt")
    with open(path, "w") as f:
        f.write(output)
    print(f"[ESM Social] Saved → {path}")
