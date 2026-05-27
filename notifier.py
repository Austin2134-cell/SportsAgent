"""
ESM Mobile Notifier.
Sends the daily card + social content to your email (iPhone push notification via Mail app).
Uses Gmail with an App Password — no third-party services required.

Setup: see instructions at the bottom of this file.
"""

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    UNIT_SIZE_DOLLARS,
    OUTPUT_DIR,
)
from dotenv import load_dotenv

_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_here, ".env"), override=True)

GMAIL_ADDRESS  = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAIL   = os.getenv("NOTIFY_EMAIL", "")   # your phone's email — can be same as Gmail


def send_daily_card(card: dict, social: dict, today: str = None) -> bool:
    """
    Send the daily card + social content to NOTIFY_EMAIL.
    Returns True if sent successfully.
    """
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASS, NOTIFY_EMAIL]):
        print("[Notifier] Email not configured — skipping. See notifier.py for setup.")
        return False

    today = today or date.today().strftime("%B %-d, %Y")
    plays  = card.get("official_plays", [])
    grade  = card.get("slate_grade", "?")
    grade_note = card.get("slate_grade_note", "")
    leans  = card.get("leans", [])
    quick  = card.get("quick_reads", [])

    subject = _build_subject(card, today)
    html    = _build_html(plays, leans, quick, grade, grade_note, social, today)
    text    = _build_text(plays, leans, quick, grade, social, today)

    return _send(subject, html, text)


def _build_subject(card: dict, today: str) -> str:
    plays  = card.get("official_plays", [])
    grade  = card.get("slate_grade", "?")
    leagues = sorted({p.get("sport", "") for p in plays if p.get("sport")})
    league_str = " & ".join(leagues) if leagues else "ESM"
    return f"ESM | {league_str} Top Bets | {today} | Slate {grade}"


def _build_html(plays, leans, quick, grade, grade_note, social, today) -> str:
    # Confidence colors
    conf_colors = {
        "HIGH":   "#22c55e",
        "MEDIUM": "#3b82f6",
        "LEAN":   "#f59e0b",
        "FLYER":  "#a855f7",
    }

    plays_html = ""
    for i, p in enumerate(plays, 1):
        conf   = p.get("confidence", "MEDIUM")
        color  = conf_colors.get(conf, "#3b82f6")
        odds   = p.get("odds", "")
        odds_s = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
        last   = p.get("last_playable_number", "")
        last_s = f"+{last}" if isinstance(last, int) and last > 0 else str(last)
        corr   = p.get("correlation_note", "none")
        factors = p.get("key_factors", [])

        plays_html += f"""
        <div style="background:#1e1e2e;border-left:4px solid {color};
                    border-radius:8px;padding:16px;margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span style="color:#94a3b8;font-size:12px;font-weight:600;letter-spacing:1px;">
              {p.get('sport','')} &nbsp;|&nbsp; {p.get('game','')}
            </span>
            <span style="color:{color};font-size:11px;font-weight:700;
                         background:rgba(255,255,255,.05);padding:2px 8px;border-radius:4px;">
              {conf}
            </span>
          </div>
          <div style="color:#f1f5f9;font-size:16px;font-weight:700;margin-bottom:4px;">
            {i}. {p.get('bet','')}
          </div>
          <div style="color:#94a3b8;font-size:13px;margin-bottom:10px;">
            {p.get('game_time_mdt','')}
          </div>
          <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap;">
            <span style="color:#f1f5f9;font-size:14px;">
              <strong style="color:#94a3b8;">ODDS</strong>&nbsp; {odds_s}
            </span>
            <span style="color:#f1f5f9;font-size:14px;">
              <strong style="color:#94a3b8;">BOOK</strong>&nbsp; {p.get('book','DK')}
            </span>
            <span style="color:#f1f5f9;font-size:14px;">
              <strong style="color:#94a3b8;">UNITS</strong>&nbsp; {p.get('units',2)}u
            </span>
            <span style="color:#94a3b8;font-size:14px;">
              Last playable: {last_s}
            </span>
          </div>
          <div style="color:#cbd5e1;font-size:13px;margin-bottom:8px;line-height:1.5;">
            <strong style="color:#94a3b8;">EDGE</strong>&nbsp; {p.get('edge_summary','')}
          </div>
          {"".join(f'<div style="color:#64748b;font-size:12px;margin-bottom:2px;">• {f}</div>' for f in factors)}
          <div style="color:#f87171;font-size:12px;margin-top:8px;">
            <strong>RISK</strong>&nbsp; {p.get('main_risk','')}
          </div>
          {f'<div style="color:#f59e0b;font-size:12px;margin-top:6px;">⚠ {corr}</div>' if corr and corr.lower() != "none" else ""}
        </div>"""

    leans_html = ""
    if leans:
        leans_html = "<h3 style='color:#94a3b8;font-size:13px;letter-spacing:1px;margin:24px 0 8px;'>LEANS</h3>"
        for lean in leans:
            odds = lean.get("odds", "")
            odds_s = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
            leans_html += f"""
            <div style="background:#1e1e2e;border-radius:6px;padding:12px;margin-bottom:8px;">
              <span style="color:#f1f5f9;font-size:13px;">[{lean.get('sport','')}]
                {lean.get('bet','')} &nbsp;{odds_s}&nbsp; {lean.get('units',1)}u</span>
              <div style="color:#64748b;font-size:12px;margin-top:4px;">{lean.get('note','')}</div>
            </div>"""

    quick_html = ""
    if quick:
        quick_html = "<h3 style='color:#94a3b8;font-size:13px;letter-spacing:1px;margin:24px 0 8px;'>QUICK READS</h3>"
        for qr in quick:
            quick_html += f"<div style='color:#cbd5e1;font-size:13px;margin-bottom:6px;'>• {qr}</div>"

    tweet_html = ""
    tweet_text = social.get("tweet", "").replace("\\n", "\n")
    if tweet_text:
        tweet_lines = tweet_text.replace("\n", "<br>")
        tweet_html = f"""
        <div style="background:#0f172a;border:1px solid #334155;border-radius:8px;
                    padding:16px;margin-top:24px;">
          <div style="color:#3b82f6;font-size:11px;font-weight:700;letter-spacing:1px;
                      margin-bottom:8px;">TWEET / X COPY</div>
          <div style="color:#f1f5f9;font-size:14px;line-height:1.7;">{tweet_lines}</div>
        </div>"""

    grade_color = {"A":"#22c55e","B":"#3b82f6","C":"#f59e0b","D":"#f97316","F":"#ef4444"}.get(grade, "#94a3b8")
    total_units = sum(p.get("units", 2) for p in plays)

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
    <body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,sans-serif;">
      <div style="max-width:600px;margin:0 auto;padding:20px;">

        <!-- Header -->
        <div style="background:#1e1e2e;border-radius:12px;padding:20px;margin-bottom:20px;
                    text-align:center;">
          <div style="color:#94a3b8;font-size:11px;letter-spacing:2px;margin-bottom:4px;">
            EDGE SPORTS MEDIA
          </div>
          <div style="color:#f1f5f9;font-size:22px;font-weight:800;margin-bottom:4px;">
            Daily Card — {today}
          </div>
          <div style="display:inline-block;background:{grade_color}22;
                      border:1px solid {grade_color};border-radius:6px;
                      color:{grade_color};font-size:13px;font-weight:700;
                      padding:4px 14px;margin-top:8px;">
            SLATE {grade}
          </div>
          <div style="color:#64748b;font-size:12px;margin-top:8px;">{grade_note}</div>
          <div style="color:#94a3b8;font-size:12px;margin-top:8px;">
            {len(plays)} official plays &nbsp;·&nbsp; {total_units}u total
            &nbsp;·&nbsp; ${UNIT_SIZE_DOLLARS:.0f}/unit
          </div>
        </div>

        <!-- Plays -->
        <h3 style="color:#94a3b8;font-size:13px;letter-spacing:1px;margin:0 0 12px;">
          OFFICIAL PLAYS
        </h3>
        {plays_html}
        {leans_html}
        {quick_html}
        {tweet_html}

        <!-- Footer -->
        <div style="text-align:center;color:#334155;font-size:11px;margin-top:24px;">
          ESM Betting Agent &nbsp;·&nbsp; Data-driven, not hype-driven.
        </div>
      </div>
    </body>
    </html>"""


def _build_text(plays, leans, quick, grade, social, today) -> str:
    """Plain text fallback for email clients that don't render HTML."""
    lines = [
        f"ESM DAILY CARD | {today} | SLATE {grade}",
        "=" * 50,
        "",
    ]
    for i, p in enumerate(plays, 1):
        odds = p.get("odds", "")
        odds_s = f"+{odds}" if isinstance(odds, int) and odds > 0 else str(odds)
        lines += [
            f"{i}. [{p.get('sport','')}] {p.get('bet','')}",
            f"   {odds_s} | {p.get('book','')} | {p.get('units',2)}u | {p.get('confidence','')}",
            f"   {p.get('edge_summary','')}",
            f"   Risk: {p.get('main_risk','')}",
            "",
        ]

    tweet = social.get("tweet", "").replace("\\n", "\n")
    if tweet:
        lines += ["TWEET COPY", "-" * 30, tweet, ""]

    return "\n".join(lines)


def _send(subject: str, html: str, text: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = NOTIFY_EMAIL
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASS)
            server.sendmail(GMAIL_ADDRESS, NOTIFY_EMAIL, msg.as_string())
        print(f"[Notifier] Card sent to {NOTIFY_EMAIL} ✓")
        return True
    except Exception as e:
        print(f"[Notifier] Email failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# GMAIL SETUP (one-time, 5 minutes)
# ─────────────────────────────────────────────────────────────────────────────
#
# 1. Go to myaccount.google.com → Security → 2-Step Verification (enable if not on)
# 2. Go to myaccount.google.com → Security → App Passwords
# 3. Select "Mail" and your device, click Generate
# 4. Copy the 16-character password shown
# 5. Add these three lines to your .env file:
#
#    GMAIL_ADDRESS=yourgmail@gmail.com
#    GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx    ← the 16-char app password (spaces ok)
#    NOTIFY_EMAIL=youremail@icloud.com          ← where to send it (can be same as Gmail)
#
# That's it. The card will land in your inbox every morning as a push notification.
# ─────────────────────────────────────────────────────────────────────────────
