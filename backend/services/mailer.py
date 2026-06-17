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

_CONFIDENCE_BG = {
    "HIGH":   "rgba(0,229,160,0.08)",
    "MEDIUM": "rgba(0,195,255,0.08)",
    "LEAN":   "rgba(245,158,11,0.08)",
    "FLYER":  "rgba(168,85,247,0.08)",
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


def _play_html(play: dict) -> str:
    conf = play.get("confidence", "MEDIUM")
    color = _CONFIDENCE_COLOR.get(conf, "#00c3ff")
    bg = _CONFIDENCE_BG.get(conf, "rgba(0,195,255,0.08)")
    odds = play.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    implied = play.get("implied_prob_pct", "")
    true_p  = play.get("true_prob_pct", "")
    edge    = play.get("edge_gap_pct", "")
    stats_row = ""
    if implied or true_p or edge:
        stats_row = f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:14px;">
        <tr>
          <td style="width:33%;text-align:center;padding:10px 6px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:11px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:4px;">Implied</div>
            <div style="font-size:18px;font-weight:700;color:#94a3b8;">{implied}%</div>
          </td>
          <td style="width:4%;"></td>
          <td style="width:33%;text-align:center;padding:10px 6px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:11px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:4px;">True Prob</div>
            <div style="font-size:18px;font-weight:700;color:{color};">{true_p}%</div>
          </td>
          <td style="width:4%;"></td>
          <td style="width:33%;text-align:center;padding:10px 6px;
                     background:#0a0f1e;border-radius:6px;">
            <div style="font-size:11px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:4px;">Edge</div>
            <div style="font-size:18px;font-weight:700;color:#00e5a0;">+{edge}%</div>
          </td>
        </tr>
      </table>"""
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:{bg};border:1px solid {color}33;
                  border-left:4px solid {color};border-radius:8px;
                  margin-bottom:18px;overflow:hidden;">
      <tr><td style="padding:20px 22px;">
        <!-- Sport / game / conf badge -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;">
          <tr>
            <td>
              <span style="font-size:12px;font-weight:700;color:#475569;
                           text-transform:uppercase;letter-spacing:.08em;">
                {play.get('sport','')}
              </span>
              <span style="font-size:12px;color:#334155;margin:0 8px;">·</span>
              <span style="font-size:13px;color:#64748b;">
                {play.get('game','')}
              </span>
            </td>
            <td align="right">
              <span style="font-size:11px;font-weight:800;color:{color};
                           text-transform:uppercase;letter-spacing:.1em;
                           background:{color}22;padding:4px 10px;border-radius:4px;">
                {conf}
              </span>
            </td>
          </tr>
        </table>
        <!-- Bet -->
        <div style="font-size:20px;font-weight:800;color:#f1f5f9;
                    letter-spacing:-.01em;margin-bottom:6px;line-height:1.2;">
          {play.get('bet','')}
        </div>
        <!-- Odds / units / book -->
        <div style="font-size:15px;color:#64748b;margin-bottom:16px;">
          <span style="color:{color};font-weight:800;font-size:18px;">{odds_str}</span>
          &nbsp;&nbsp;{play.get('units', 2)}u
          &nbsp;·&nbsp; {play.get('book','DraftKings')}
          {"&nbsp;·&nbsp; " + play.get('game_time_mdt','') if play.get('game_time_mdt') else ""}
        </div>
        {stats_row}
        <!-- Edge summary -->
        <div style="font-size:14px;color:#94a3b8;line-height:1.65;
                    border-top:1px solid #1e293b;padding-top:12px;">
          {play.get('edge_summary','')}
        </div>
      </td></tr>
    </table>"""


def _lean_html(lean: dict) -> str:
    odds = lean.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0d1424;border-left:3px solid #f59e0b;
                  border-radius:6px;margin-bottom:10px;">
      <tr><td style="padding:12px 16px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <span style="font-size:12px;font-weight:700;color:#f59e0b;
                           text-transform:uppercase;letter-spacing:.06em;">
                {lean.get('sport','')}
              </span>
              <span style="font-size:15px;color:#cbd5e1;margin-left:10px;">
                {lean.get('bet','')}
              </span>
            </td>
            <td align="right">
              <span style="font-size:16px;font-weight:700;color:#f59e0b;">{odds_str}</span>
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
    plays_html = "".join(_play_html(p) for p in plays)
    leans_html = "".join(_lean_html(l) for l in card.get("leans", []))

    qr_items = "".join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #111827;">'
        f'<span style="color:#00c3ff;margin-right:10px;font-size:16px;">›</span>'
        f'<span style="font-size:14px;color:#94a3b8;line-height:1.6;">{qr}</span>'
        f'</td></tr>'
        for qr in card.get("quick_reads", [])
    )
    pass_items = "".join(
        f'<tr><td style="padding:6px 0;">'
        f'<span style="color:#ef4444;margin-right:10px;font-size:13px;">✕</span>'
        f'<span style="font-size:13px;color:#475569;">{p}</span>'
        f'</td></tr>'
        for p in card.get("pass_notes", [])
    )

    has_leans = bool(card.get("leans"))
    has_passes = bool(card.get("pass_notes"))
    has_qr = bool(card.get("quick_reads"))

    record = card.get("running_record", {})
    record_html = ""
    if record.get("provided"):
        record_html = f"""
        <tr><td style="padding-bottom:18px;">
          <div style="background:#0d1424;border:1px solid #1e293b;border-radius:6px;
                      padding:12px 16px;font-size:13px;color:#64748b;">
            📊 &nbsp;{record.get('summary','')}
          </div>
        </td></tr>"""

    play_count = len(plays)
    no_plays_html = """
        <div style="text-align:center;padding:36px 0;">
          <div style="font-size:16px;color:#334155;margin-bottom:6px;">
            No official plays today.
          </div>
          <div style="font-size:14px;color:#1e293b;">
            Protecting capital is part of the edge.
          </div>
        </div>"""

    def section_header(label, rule_color):
        return (
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f'<tr><td style="padding:22px 0 14px;">'
            f'<div style="font-size:12px;font-weight:800;color:#2a4a6a;'
            f'text-transform:uppercase;letter-spacing:.18em;">{label}</div>'
            f'<div style="height:1px;background:linear-gradient(90deg,{rule_color}55 0%,{rule_color}00 100%);'
            f'margin-top:8px;"></div>'
            f'</td></tr></table>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>ESM Daily Card — {card_date}</title>
</head>
<body style="margin:0;padding:0;background:#060b16;
             font-family:'Segoe UI',Helvetica,Arial,sans-serif;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#060b16;">
<tr><td align="center" style="padding:24px 12px 40px;">

  <table width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;width:100%;">

    <!-- ═══ HEADER ═══ -->
    <tr><td style="background:#080e1c;border-radius:10px 10px 0 0;
                   border:1px solid #0f1e38;border-bottom:none;padding:0;">

      <!-- Gradient accent bar -->
      <div style="height:4px;background:linear-gradient(90deg,#00c3ff 0%,#00e5a0 100%);
                  border-radius:10px 10px 0 0;"></div>

      <table width="100%" cellpadding="0" cellspacing="0"
             style="padding:26px 30px 24px;">
        <tr>
          <!-- Brand wordmark -->
          <td valign="middle">
            <div style="font-size:36px;font-weight:900;color:#f1f5f9;
                        letter-spacing:-.04em;line-height:1;">ESM</div>
            <div style="font-size:11px;color:#2a4a6a;text-transform:uppercase;
                        letter-spacing:.2em;margin-top:3px;">Edge Sports Media</div>
          </td>

          <!-- Grade badge -->
          <td align="right" valign="middle">
            <div style="font-size:12px;color:#2a4a6a;text-transform:uppercase;
                        letter-spacing:.12em;margin-bottom:8px;">{card_date}</div>
            <table cellpadding="0" cellspacing="0" align="right">
              <tr><td style="background:{grade_color}18;border:1px solid {grade_color}44;
                             border-radius:8px;padding:10px 20px;text-align:center;">
                <div style="font-size:11px;color:{grade_color};text-transform:uppercase;
                            letter-spacing:.14em;font-weight:700;margin-bottom:4px;">
                  Slate Grade
                </div>
                <div style="font-size:38px;font-weight:900;color:{grade_color};
                            line-height:1;">{grade}</div>
                <div style="font-size:12px;color:{grade_color}bb;font-weight:700;
                            text-transform:uppercase;letter-spacing:.12em;
                            margin-top:4px;">{grade_label}</div>
              </td></tr>
            </table>
          </td>
        </tr>

        {"" if not grade_note else f'<tr><td colspan="2" style="padding-top:16px;"><div style="font-size:14px;color:#334155;line-height:1.6;border-top:1px solid #0f1e38;padding-top:14px;">{grade_note}</div></td></tr>'}
      </table>
    </td></tr>

    <!-- ═══ BODY ═══ -->
    <tr><td style="background:#080e1c;border:1px solid #0f1e38;
                   border-top:none;border-bottom:none;padding:0 30px 8px;">

      {record_html}

      {section_header(f"Official Plays &nbsp; <span style='color:#1e4060;font-weight:600;font-size:11px;'>{play_count} play{'s' if play_count != 1 else ''}</span>", "#00c3ff")}

      {plays_html if plays_html else no_plays_html}

    </td></tr>

    {"<tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 30px 20px;'>" + section_header("Leans", "#f59e0b") + leans_html + "</td></tr>" if has_leans else ""}

    {"<tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 30px 20px;'>" + section_header("Quick Reads", "#00c3ff") + "<table width='100%' cellpadding='0' cellspacing='0'>" + qr_items + "</table></td></tr>" if has_qr else ""}

    {"<tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 30px 20px;'>" + section_header("Passes", "#ef4444") + "<table width='100%' cellpadding='0' cellspacing='0'>" + pass_items + "</table></td></tr>" if has_passes else ""}

    <!-- ═══ FOOTER ═══ -->
    <tr><td style="background:#04080f;border:1px solid #0f1e38;border-top:none;
                   border-radius:0 0 10px 10px;padding:18px 30px 20px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <div style="font-size:14px;font-weight:800;color:#1e3a5a;
                        letter-spacing:.04em;">ESM</div>
          </td>
          <td align="right">
            <div style="font-size:11px;color:#0f1e38;line-height:1.6;text-align:right;">
              For informational purposes only. Gambling involves risk.<br/>
              Always verify odds at your sportsbook before placing.
            </div>
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
