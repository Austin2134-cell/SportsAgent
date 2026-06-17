"""
Email delivery for daily ESM cards.

Configure via environment variables:
  EMAIL_FROM        — sender address (default: cards@edgebet.com)
  EMAIL_SMTP_HOST   — SMTP server hostname
  EMAIL_SMTP_PORT   — SMTP port (default: 587)
  EMAIL_SMTP_USER   — SMTP username / login
  EMAIL_SMTP_PASS   — SMTP password / app-password
  SENDGRID_API_KEY  — alternative: SendGrid API key (skips SMTP)

If neither SMTP nor SendGrid is configured the formatted card is
written to /tmp/esm_card_<date>.html and the function returns False.
"""

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


_CONFIDENCE_COLOR = {
    "HIGH":   "#00e5a0",
    "MEDIUM": "#00c3ff",
    "LEAN":   "#f59e0b",
    "FLYER":  "#a855f7",
}

_GRADE_COLOR = {
    "A": "#00e5a0",
    "B": "#00c3ff",
    "C": "#f59e0b",
    "D": "#f97316",
    "F": "#ef4444",
}

_GRADE_LABEL = {
    "A": "ELITE",
    "B": "STRONG",
    "C": "PLAYABLE",
    "D": "THIN",
    "F": "NO PLAY",
}


def _sport_pill(sport: str) -> str:
    colors = {
        "SOCCER": ("#00c3ff", "rgba(0,195,255,0.15)"),
        "MLB":    ("#f59e0b", "rgba(245,158,11,0.15)"),
        "NBA":    ("#a855f7", "rgba(168,85,247,0.15)"),
        "NFL":    ("#00e5a0", "rgba(0,229,160,0.15)"),
        "NHL":    ("#60a5fa", "rgba(96,165,250,0.15)"),
        "NCAAB":  ("#f97316", "rgba(249,115,22,0.15)"),
        "NCAAF":  ("#34d399", "rgba(52,211,153,0.15)"),
    }
    c, bg = colors.get(sport.upper(), ("#94a3b8", "rgba(148,163,184,0.15)"))
    return (
        f'<span style="display:inline-block;font-size:10px;font-weight:800;'
        f'color:{c};background:{bg};padding:3px 8px;border-radius:3px;'
        f'text-transform:uppercase;letter-spacing:.08em;">{sport}</span>'
    )


def _section_bar(label: str, right_text: str = "", color: str = "#f59e0b") -> str:
    right = (
        f'<td align="right" valign="middle">'
        f'<span style="font-size:11px;font-weight:700;color:{color};'
        f'letter-spacing:.08em;">{right_text}</span></td>'
        if right_text else ""
    )
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:28px 0 18px;">
      <tr>
        <td style="padding:10px 16px;background:{color}18;
                   border-left:4px solid {color};border-radius:4px;"
            valign="middle">
          <span style="font-size:12px;font-weight:900;color:{color};
                       text-transform:uppercase;letter-spacing:.2em;">{label}</span>
        </td>
        {right}
      </tr>
    </table>"""


def _play_html(play: dict) -> str:
    conf = play.get("confidence", "MEDIUM")
    color = _CONFIDENCE_COLOR.get(conf, "#00c3ff")
    odds = play.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    implied = play.get("implied_prob_pct", "")
    true_p  = play.get("true_prob_pct", "")
    edge    = play.get("edge_gap_pct", "")
    sport   = play.get("sport", "")
    game_time = play.get("game_time_mdt", "")

    stats_row = ""
    if implied or true_p or edge:
        edge_display = f"+{edge}%" if str(edge) and not str(edge).startswith("+") else f"{edge}%"
        stats_row = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="margin:16px 0;">
        <tr>
          <td width="32%" style="text-align:center;padding:12px 8px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:10px;font-weight:700;color:#475569;
                        text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px;">
              Implied
            </div>
            <div style="font-size:20px;font-weight:800;color:#64748b;">{implied}%</div>
          </td>
          <td width="2%"></td>
          <td width="32%" style="text-align:center;padding:12px 8px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:10px;font-weight:700;color:#475569;
                        text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px;">
              True Prob
            </div>
            <div style="font-size:20px;font-weight:800;color:{color};">{true_p}%</div>
          </td>
          <td width="2%"></td>
          <td width="32%" style="text-align:center;padding:12px 8px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:10px;font-weight:700;color:#475569;
                        text-transform:uppercase;letter-spacing:.1em;margin-bottom:5px;">
              Edge
            </div>
            <div style="font-size:20px;font-weight:800;color:#00e5a0;">{edge_display}</div>
          </td>
        </tr>
      </table>"""

    time_part = f"&nbsp;·&nbsp; {game_time}" if game_time else ""

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0d1525;border-left:4px solid {color};
                  border-radius:6px;margin-bottom:16px;">
      <tr><td style="padding:20px 22px;">

        <!-- Sport pill · Game · Confidence badge -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
          <tr>
            <td valign="middle">
              {_sport_pill(sport)}
              <span style="font-size:13px;color:#475569;margin-left:10px;
                           vertical-align:middle;">{play.get('game','')}</span>
            </td>
            <td align="right" valign="middle">
              <span style="font-size:10px;font-weight:900;color:{color};
                           text-transform:uppercase;letter-spacing:.12em;
                           border:1px solid {color};padding:4px 10px;border-radius:4px;">
                {conf}
              </span>
            </td>
          </tr>
        </table>

        <!-- Bet name -->
        <div style="font-size:22px;font-weight:900;color:#f1f5f9;
                    letter-spacing:-.02em;line-height:1.2;margin-bottom:10px;">
          {play.get('bet','')}
        </div>

        <!-- Odds · units · book · time -->
        <div style="font-size:15px;color:#475569;margin-bottom:6px;">
          <span style="color:{color};font-weight:900;font-size:20px;">{odds_str}</span>
          &nbsp;·&nbsp;
          <span style="color:#94a3b8;font-weight:600;">{play.get('units', 2)}u</span>
          &nbsp;·&nbsp;
          <span style="color:#64748b;">{play.get('book','DraftKings')}</span>
          <span style="color:#334155;">{time_part}</span>
        </div>

        {stats_row}

        <!-- Edge summary -->
        <div style="font-size:14px;color:#64748b;line-height:1.7;
                    border-top:1px solid #131e30;padding-top:14px;margin-top:6px;">
          {play.get('edge_summary','')}
        </div>

      </td></tr>
    </table>"""


def _lean_html(lean: dict) -> str:
    odds = lean.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    sport = lean.get("sport", "")
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0d1525;border-radius:4px;margin-bottom:10px;">
      <tr><td style="padding:12px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td valign="middle">
              {_sport_pill(sport)}
              <span style="font-size:16px;font-weight:700;color:#cbd5e1;
                           margin-left:12px;vertical-align:middle;">
                {lean.get('bet','')}
              </span>
            </td>
            <td align="right" valign="middle">
              <span style="font-size:17px;font-weight:800;color:#f59e0b;">{odds_str}</span>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>"""


def build_html_email(card: dict, card_date: str = None) -> str:
    card_date = card_date or card.get("date", date.today().isoformat())
    grade = card.get("slate_grade", "?")
    grade_color = _GRADE_COLOR.get(grade, "#94a3b8")
    grade_label = _GRADE_LABEL.get(grade, grade)
    grade_note = card.get("slate_grade_note", "")

    plays = card.get("official_plays", [])
    leans = card.get("leans", [])
    quick_reads = card.get("quick_reads", [])
    pass_notes = card.get("pass_notes", [])

    plays_html = "".join(_play_html(p) for p in plays)
    leans_html = "".join(_lean_html(l) for l in leans)

    play_count = len(plays)
    play_count_label = f"{play_count} PLAY{'S' if play_count != 1 else ''}"

    qr_rows = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #0d1525;">'
        f'<span style="color:#00c3ff;font-size:18px;font-weight:700;'
        f'vertical-align:middle;margin-right:12px;">›</span>'
        f'<span style="font-size:15px;color:#94a3b8;line-height:1.6;'
        f'vertical-align:middle;">{qr}</span>'
        f'</td></tr>'
        for qr in quick_reads
    )

    pass_rows = "".join(
        f'<tr><td style="padding:8px 0 8px 14px;border-left:3px solid #ef4444;'
        f'border-radius:2px;margin-bottom:8px;display:block;">'
        f'<span style="font-size:14px;color:#64748b;">{p}</span>'
        f'</td></tr>'
        for p in pass_notes
    )

    no_plays_html = """
    <div style="text-align:center;padding:40px 0;">
      <div style="font-size:32px;margin-bottom:12px;">—</div>
      <div style="font-size:17px;font-weight:700;color:#334155;margin-bottom:8px;">
        No official plays today.
      </div>
      <div style="font-size:14px;color:#1e3a5a;">
        Protecting capital is part of the edge.
      </div>
    </div>"""

    record = card.get("running_record", {})
    record_html = ""
    if record.get("provided"):
        record_html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
      <tr><td style="background:#0a0f1e;border:1px solid #131e30;border-radius:6px;
                     padding:12px 16px;font-size:13px;color:#475569;">
        {record.get('summary','')}
      </td></tr>
    </table>"""

    leans_section = ""
    if leans:
        leans_section = f"""
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:0 30px 24px;">
      {_section_bar("Leans", "", "#f59e0b")}
      {leans_html}
    </td></tr>"""

    qr_section = ""
    if quick_reads:
        qr_section = f"""
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:0 30px 24px;">
      {_section_bar("Quick Reads", "", "#00c3ff")}
      <table width="100%" cellpadding="0" cellspacing="0">
        {qr_rows}
      </table>
    </td></tr>"""

    passes_section = ""
    if pass_notes:
        passes_section = f"""
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:0 30px 24px;">
      {_section_bar("Passes", "", "#ef4444")}
      <table width="100%" cellpadding="0" cellspacing="0">
        {pass_rows}
      </table>
    </td></tr>"""

    grade_note_html = ""
    if grade_note:
        grade_note_html = f"""
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:0 30px 20px;">
      <div style="font-size:15px;color:#475569;line-height:1.7;
                  border-left:3px solid {grade_color}55;padding-left:14px;">
        {grade_note}
      </div>
    </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>ESM Daily Card — {card_date}</title>
</head>
<body style="margin:0;padding:0;background:#05090f;
             font-family:'Segoe UI',Helvetica,Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#05090f;">
<tr><td align="center" style="padding:28px 12px 48px;">

  <table width="620" cellpadding="0" cellspacing="0"
         style="max-width:620px;width:100%;">

    <!-- ═══ TOP ACCENT ═══ -->
    <tr><td style="height:5px;background:linear-gradient(90deg,#00c3ff 0%,#00e5a0 60%,#f59e0b 100%);
                   border-radius:8px 8px 0 0;"></td></tr>

    <!-- ═══ HEADER ═══ -->
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:28px 30px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <!-- Left: branding + title -->
          <td valign="top">
            <!-- ESM wordmark -->
            <div style="font-size:13px;font-weight:900;color:#2a4a6a;
                        text-transform:uppercase;letter-spacing:.3em;
                        margin-bottom:14px;">
              EDGE SPORTS MEDIA
            </div>
            <!-- DAILY CARD title -->
            <div style="font-size:42px;font-weight:900;color:#f1f5f9;
                        letter-spacing:-.03em;line-height:1;margin-bottom:8px;">
              DAILY CARD
            </div>
            <!-- Subtitle -->
            <div style="font-size:12px;font-weight:600;color:#1e3a5a;
                        text-transform:uppercase;letter-spacing:.18em;
                        margin-bottom:6px;">
              PRECISION ANALYTICS
            </div>
            <!-- Date -->
            <div style="font-size:14px;color:#334155;margin-top:10px;">
              {card_date}
            </div>
          </td>

          <!-- Right: slate grade box -->
          <td align="right" valign="top" style="padding-left:20px;white-space:nowrap;">
            <table cellpadding="0" cellspacing="0" align="right">
              <tr><td style="border:2px solid {grade_color}55;border-radius:8px;
                             padding:16px 24px;text-align:center;
                             background:{grade_color}0d;min-width:100px;">
                <div style="font-size:10px;font-weight:800;color:{grade_color}99;
                            text-transform:uppercase;letter-spacing:.2em;
                            margin-bottom:6px;">
                  SLATE GRADE
                </div>
                <div style="font-size:52px;font-weight:900;color:{grade_color};
                            line-height:1;">{grade}</div>
                <div style="font-size:11px;font-weight:800;color:{grade_color}cc;
                            text-transform:uppercase;letter-spacing:.15em;
                            margin-top:6px;">{grade_label}</div>
              </td></tr>
            </table>
          </td>
        </tr>
      </table>
    </td></tr>

    {grade_note_html}

    <!-- ═══ OFFICIAL PLAYS ═══ -->
    <tr><td style="background:#080e1c;border-left:1px solid #0f1e38;
                   border-right:1px solid #0f1e38;padding:0 30px 28px;">
      {_section_bar("Official Plays", play_count_label, "#00c3ff")}
      {record_html}
      {plays_html if plays_html else no_plays_html}
    </td></tr>

    {leans_section}
    {qr_section}
    {passes_section}

    <!-- ═══ FOOTER ═══ -->
    <tr><td style="background:#04080f;border:1px solid #0f1e38;border-top:1px solid #0d1525;
                   border-radius:0 0 8px 8px;padding:16px 30px 18px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td valign="middle">
            <span style="font-size:11px;color:#1e3a5a;letter-spacing:.04em;">
              EDGE SPORTS MEDIA &nbsp;·&nbsp; FOR INFORMATIONAL PURPOSES ONLY
              &nbsp;·&nbsp; VERIFY ODDS BEFORE PLACING
            </span>
          </td>
          <td align="right" valign="middle">
            <span style="font-size:12px;font-weight:900;color:#1e3a5a;
                         letter-spacing:.08em;">{card_date}</span>
            <span style="font-size:14px;font-weight:900;color:#2a4a6a;
                         letter-spacing:.06em;margin-left:10px;">ESM</span>
          </td>
        </tr>
      </table>
    </td></tr>

  </table>

</td></tr>
</table>
</body>
</html>"""


def send_card_email(card: dict, to_address: str, card_date: str = None) -> bool:
    """Send the formatted card HTML to to_address. Returns True on success."""
    card_date = card_date or card.get("date", date.today().isoformat())
    html_body = build_html_email(card, card_date)
    subject = f"ESM Daily Card — {card_date} (Grade {card.get('slate_grade','?')})"

    sendgrid_key = os.getenv("SENDGRID_API_KEY", "")
    if sendgrid_key:
        return _send_via_sendgrid(html_body, subject, to_address, sendgrid_key)

    smtp_host = os.getenv("EMAIL_SMTP_HOST", "")
    if smtp_host:
        return _send_via_smtp(html_body, subject, to_address)

    path = f"/tmp/esm_card_{card_date}.html"
    with open(path, "w") as f:
        f.write(html_body)
    print(f"[mailer] No email transport configured. Card saved to: {path}")
    return False


def _send_via_smtp(html_body: str, subject: str, to_address: str) -> bool:
    from_addr = os.getenv("EMAIL_FROM", "cards@edgebet.com")
    smtp_host = os.getenv("EMAIL_SMTP_HOST")
    smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
    smtp_user = os.getenv("EMAIL_SMTP_USER", "")
    smtp_pass = os.getenv("EMAIL_SMTP_PASS", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
        print(f"[mailer] Email sent to {to_address} via SMTP ({smtp_host})")
        return True
    except Exception as e:
        print(f"[mailer] SMTP send failed: {e}")
        return False


def _send_via_sendgrid(html_body: str, subject: str, to_address: str, api_key: str) -> bool:
    try:
        import urllib.request
        import json as _json
        from_addr = os.getenv("EMAIL_FROM", "cards@edgebet.com")
        payload = _json.dumps({
            "personalizations": [{"to": [{"email": to_address}]}],
            "from": {"email": from_addr},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }).encode()
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 202):
                print(f"[mailer] Email sent to {to_address} via SendGrid")
                return True
        print(f"[mailer] SendGrid returned unexpected status {resp.status}")
        return False
    except Exception as e:
        print(f"[mailer] SendGrid send failed: {e}")
        return False
