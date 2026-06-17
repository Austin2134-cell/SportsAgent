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
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
        <tr>
          <td style="width:33%;text-align:center;padding:8px 4px;
                     background:#0a0f1e;border-radius:4px;">
            <div style="font-size:10px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:2px;">Implied</div>
            <div style="font-size:15px;font-weight:700;color:#94a3b8;">{implied}%</div>
          </td>
          <td style="width:4%;"></td>
          <td style="width:33%;text-align:center;padding:8px 4px;
                     background:#0a0f1e;border-radius:4px;">
            <div style="font-size:10px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:2px;">True Prob</div>
            <div style="font-size:15px;font-weight:700;color:{color};">{true_p}%</div>
          </td>
          <td style="width:4%;"></td>
          <td style="width:33%;text-align:center;padding:8px 4px;
                     background:#0a0f1e;border-radius:4px;">
            <div style="font-size:10px;color:#475569;text-transform:uppercase;
                        letter-spacing:.08em;margin-bottom:2px;">Edge</div>
            <div style="font-size:15px;font-weight:700;color:#00e5a0;">+{edge}%</div>
          </td>
        </tr>
      </table>"""
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:{bg};border:1px solid {color}22;
                  border-left:3px solid {color};border-radius:8px;
                  margin-bottom:14px;overflow:hidden;">
      <tr><td style="padding:16px 18px;">
        <!-- Sport / game / conf badge -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:10px;">
          <tr>
            <td>
              <span style="font-size:11px;font-weight:700;color:#475569;
                           text-transform:uppercase;letter-spacing:.08em;">
                {play.get('sport','')}
              </span>
              <span style="font-size:11px;color:#334155;margin:0 6px;">·</span>
              <span style="font-size:11px;color:#64748b;">
                {play.get('game','')}
              </span>
            </td>
            <td align="right">
              <span style="font-size:10px;font-weight:800;color:{color};
                           text-transform:uppercase;letter-spacing:.1em;
                           background:{color}22;padding:3px 8px;border-radius:3px;">
                {conf}
              </span>
            </td>
          </tr>
        </table>
        <!-- Bet + odds -->
        <div style="font-size:17px;font-weight:800;color:#f1f5f9;
                    letter-spacing:-.01em;margin-bottom:4px;">
          {play.get('bet','')}
        </div>
        <div style="font-size:13px;color:#64748b;margin-bottom:12px;">
          <span style="color:{color};font-weight:700;font-size:15px;">{odds_str}</span>
          &nbsp;·&nbsp; {play.get('units', 2)}u
          &nbsp;·&nbsp; {play.get('book','DraftKings')}
          {"&nbsp;·&nbsp; " + play.get('game_time_mdt','') if play.get('game_time_mdt') else ""}
        </div>
        {stats_row}
        <!-- Edge summary -->
        <div style="font-size:13px;color:#94a3b8;line-height:1.55;
                    border-top:1px solid #1e293b;padding-top:10px;">
          {play.get('edge_summary','')}
        </div>
      </td></tr>
    </table>"""


def _lean_html(lean: dict) -> str:
    odds = lean.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0d1424;border-left:2px solid #f59e0b;
                  border-radius:4px;margin-bottom:8px;">
      <tr><td style="padding:10px 14px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td>
              <span style="font-size:11px;font-weight:700;color:#f59e0b;
                           text-transform:uppercase;letter-spacing:.06em;">
                {lean.get('sport','')}
              </span>
              <span style="font-size:13px;color:#cbd5e1;margin-left:8px;">
                {lean.get('bet','')}
              </span>
            </td>
            <td align="right">
              <span style="font-size:13px;font-weight:700;color:#f59e0b;">{odds_str}</span>
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
        f'<tr><td style="padding:6px 0;border-bottom:1px solid #111827;">'
        f'<span style="color:#00c3ff;margin-right:8px;">›</span>'
        f'<span style="font-size:13px;color:#94a3b8;line-height:1.5;">{qr}</span>'
        f'</td></tr>'
        for qr in card.get("quick_reads", [])
    )
    pass_items = "".join(
        f'<tr><td style="padding:5px 0;">'
        f'<span style="color:#ef4444;margin-right:8px;font-size:11px;">✕</span>'
        f'<span style="font-size:12px;color:#475569;">{p}</span>'
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
        <div style="text-align:center;padding:28px 0;">
          <div style="font-size:32px;margin-bottom:8px;">—</div>
          <div style="font-size:14px;color:#334155;">No official plays today.</div>
          <div style="font-size:12px;color:#1e293b;margin-top:4px;">
            Protecting capital is part of the edge.
          </div>
        </div>"""

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
<tr><td align="center" style="padding:20px 12px 32px;">

  <table width="600" cellpadding="0" cellspacing="0"
         style="max-width:600px;width:100%;">

    <!-- ═══ HEADER BANNER ═══ -->
    <tr><td style="background:#080e1c;border-radius:10px 10px 0 0;
                   border:1px solid #0f1e38;border-bottom:none;
                   padding:0;">

      <!-- Top accent line: gradient from teal → green -->
      <div style="height:3px;background:linear-gradient(90deg,#00c3ff 0%,#00e5a0 100%);
                  border-radius:10px 10px 0 0;"></div>

      <table width="100%" cellpadding="0" cellspacing="0"
             style="padding:22px 28px 20px;">
        <tr>
          <!-- ESM logotype -->
          <td valign="middle">
            <table cellpadding="0" cellspacing="0">
              <tr>
                <!-- Circuit dot cluster -->
                <td valign="middle" style="padding-right:12px;">
                  <table cellpadding="0" cellspacing="2">
                    <tr>
                      <td style="width:5px;height:5px;background:#00c3ff;
                                 border-radius:50%;"></td>
                      <td style="width:5px;height:5px;background:#00e5a0;
                                 border-radius:50%;"></td>
                    </tr>
                    <tr>
                      <td style="width:5px;height:5px;background:#0f2a4a;
                                 border-radius:50%;"></td>
                      <td style="width:5px;height:5px;background:#00c3ff;
                                 border-radius:50%;"></td>
                    </tr>
                  </table>
                </td>
                <td valign="middle">
                  <div style="font-size:32px;font-weight:900;letter-spacing:-.03em;
                              line-height:1;">
                    <span style="color:#00c3ff;">E</span><span style="color:#00d4b0;">S</span><span style="color:#00e5a0;">M</span>
                  </div>
                  <div style="font-size:9px;color:#1e4060;text-transform:uppercase;
                              letter-spacing:.18em;margin-top:1px;">
                    Edge Sports Media
                  </div>
                </td>
              </tr>
            </table>
          </td>

          <!-- Date + grade badge -->
          <td align="right" valign="middle">
            <div style="font-size:11px;color:#1e4060;text-transform:uppercase;
                        letter-spacing:.1em;margin-bottom:6px;">{card_date}</div>
            <div style="display:inline-block;background:{grade_color}18;
                        border:1px solid {grade_color}55;border-radius:6px;
                        padding:6px 14px;text-align:center;">
              <div style="font-size:10px;color:{grade_color};text-transform:uppercase;
                          letter-spacing:.12em;font-weight:700;">Slate Grade</div>
              <div style="font-size:26px;font-weight:900;color:{grade_color};
                          line-height:1.1;">{grade}</div>
              <div style="font-size:10px;color:{grade_color}aa;font-weight:700;
                          text-transform:uppercase;letter-spacing:.1em;">{grade_label}</div>
            </div>
          </td>
        </tr>

        <!-- Grade note -->
        {"" if not grade_note else f'<tr><td colspan="2" style="padding-top:14px;"><div style="font-size:12px;color:#334155;line-height:1.55;border-top:1px solid #0f1e38;padding-top:12px;">{grade_note}</div></td></tr>'}
      </table>
    </td></tr>

    <!-- ═══ BODY ═══ -->
    <tr><td style="background:#080e1c;border:1px solid #0f1e38;
                   border-top:none;border-bottom:none;padding:0 28px 4px;">

      {record_html}

      <!-- Section: Official Plays -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="padding:18px 0 12px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <span style="font-size:10px;font-weight:800;color:#1e4060;
                             text-transform:uppercase;letter-spacing:.15em;">
                  Official Plays
                </span>
              </td>
              <td align="right">
                <span style="font-size:10px;color:#0f2a4a;font-weight:700;
                             text-transform:uppercase;letter-spacing:.1em;">
                  {play_count} play{"s" if play_count != 1 else ""}
                </span>
              </td>
            </tr>
          </table>
          <!-- teal rule -->
          <div style="height:1px;background:linear-gradient(90deg,#00c3ff44 0%,#00c3ff00 100%);
                      margin-top:6px;"></div>
        </td></tr>
      </table>

      {plays_html if plays_html else no_plays_html}

    </td></tr>

    {"<!-- Leans --><tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 28px 16px;'><div style='font-size:10px;font-weight:800;color:#1e4060;text-transform:uppercase;letter-spacing:.15em;margin-bottom:4px;'>Leans</div><div style=\'height:1px;background:linear-gradient(90deg,#f59e0b44 0%,#f59e0b00 100%);margin-bottom:12px;\'></div>" + leans_html + "</td></tr>" if has_leans else ""}

    {"<!-- Quick Reads --><tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 28px 20px;'><div style='font-size:10px;font-weight:800;color:#1e4060;text-transform:uppercase;letter-spacing:.15em;margin-bottom:4px;'>Quick Reads</div><div style='height:1px;background:linear-gradient(90deg,#00c3ff44 0%,#00c3ff00 100%);margin-bottom:10px;'></div><table width='100%' cellpadding='0' cellspacing='0'>" + qr_items + "</table></td></tr>" if has_qr else ""}

    {"<!-- Pass Notes --><tr><td style='background:#080e1c;border:1px solid #0f1e38;border-top:none;border-bottom:none;padding:0 28px 20px;'><div style='font-size:10px;font-weight:800;color:#1e4060;text-transform:uppercase;letter-spacing:.15em;margin-bottom:4px;'>Passes</div><div style='height:1px;background:linear-gradient(90deg,#ef444444 0%,#ef444400 100%);margin-bottom:8px;'></div><table width='100%' cellpadding='0' cellspacing='0'>" + pass_items + "</table></td></tr>" if has_passes else ""}

    <!-- ═══ FOOTER ═══ -->
    <tr><td style="background:#04080f;border:1px solid #0f1e38;border-top:none;
                   border-radius:0 0 10px 10px;padding:16px 28px 18px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <div style="font-size:11px;font-weight:800;letter-spacing:.08em;">
              <span style="color:#00c3ff;">E</span><span style="color:#00d4b0;">S</span><span style="color:#00e5a0;">M</span>
            </div>
          </td>
          <td align="right">
            <div style="font-size:9px;color:#0f1e38;line-height:1.5;text-align:right;">
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
