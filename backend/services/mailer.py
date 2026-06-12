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


# ── HTML template helpers ─────────────────────────────────────────────────────

_CONFIDENCE_COLOR = {
    "HIGH":   "#22c55e",
    "MEDIUM": "#3b82f6",
    "LEAN":   "#f59e0b",
    "FLYER":  "#a855f7",
}

_GRADE_COLOR = {
    "A": "#22c55e",
    "B": "#3b82f6",
    "C": "#f59e0b",
    "D": "#f97316",
    "F": "#ef4444",
}


def _play_html(play: dict) -> str:
    conf = play.get("confidence", "MEDIUM")
    color = _CONFIDENCE_COLOR.get(conf, "#3b82f6")
    odds = play.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    key_factors = "".join(f"<li>{f}</li>" for f in play.get("key_factors", []))
    return f"""
    <div style="background:#1e293b;border-left:4px solid {color};
                border-radius:6px;padding:16px 20px;margin-bottom:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;
                  flex-wrap:wrap;gap:8px;margin-bottom:8px;">
        <span style="font-size:13px;font-weight:600;color:#94a3b8;
                     text-transform:uppercase;letter-spacing:.05em;">
          {play.get('sport','')} &nbsp;·&nbsp; {play.get('game','')}
        </span>
        <span style="font-size:12px;color:{color};font-weight:700;
                     text-transform:uppercase;">{conf}</span>
      </div>
      <div style="font-size:18px;font-weight:700;color:#f1f5f9;margin-bottom:6px;">
        {play.get('bet','')}
      </div>
      <div style="font-size:14px;color:#94a3b8;margin-bottom:10px;">
        {odds_str} &nbsp;·&nbsp; {play.get('units', 2)}u &nbsp;·&nbsp;
        {play.get('book','DraftKings')} &nbsp;·&nbsp;
        {play.get('game_time_mdt', '')}
      </div>
      <div style="font-size:14px;color:#cbd5e1;margin-bottom:8px;">
        {play.get('edge_summary','')}
      </div>
      <ul style="color:#94a3b8;font-size:13px;margin:0;padding-left:18px;">
        {key_factors}
      </ul>
      <div style="font-size:12px;color:#64748b;margin-top:8px;">
        ⚠️ Risk: {play.get('main_risk','')}
      </div>
    </div>"""


def _lean_html(lean: dict) -> str:
    odds = lean.get("odds", 0)
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    return f"""
    <div style="background:#162032;border-left:3px solid #f59e0b;
                border-radius:4px;padding:12px 16px;margin-bottom:10px;">
      <span style="font-size:14px;color:#fbbf24;font-weight:600;">
        {lean.get('sport','')} — {lean.get('bet','')}
      </span>
      <span style="font-size:13px;color:#94a3b8;margin-left:10px;">
        {odds_str} · {lean.get('units',1)}u
      </span>
      <div style="font-size:13px;color:#64748b;margin-top:4px;">
        {lean.get('note','')}
      </div>
    </div>"""


def build_html_email(card: dict, card_date: str = None) -> str:
    card_date = card_date or card.get("date", date.today().isoformat())
    grade = card.get("slate_grade", "?")
    grade_color = _GRADE_COLOR.get(grade, "#94a3b8")
    grade_note = card.get("slate_grade_note", "")

    plays_html = "".join(_play_html(p) for p in card.get("official_plays", []))
    leans_html = "".join(_lean_html(l) for l in card.get("leans", []))

    qr_items = "".join(
        f'<li style="margin-bottom:6px;color:#cbd5e1;">{qr}</li>'
        for qr in card.get("quick_reads", [])
    )
    pass_items = "".join(
        f'<li style="margin-bottom:6px;color:#64748b;">{p}</li>'
        for p in card.get("pass_notes", [])
    )

    has_leans = bool(card.get("leans"))
    has_passes = bool(card.get("pass_notes"))

    record = card.get("running_record", {})
    record_html = ""
    if record.get("provided"):
        record_html = f"""
        <div style="background:#1e293b;border-radius:6px;padding:14px 18px;
                    margin-bottom:20px;font-size:14px;color:#94a3b8;">
          📊 Record: {record.get('summary','')}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>ESM Daily Card — {card_date}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;">
    <tr><td align="center" style="padding:24px 16px;">
      <table width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:#0f172a;">

        <!-- Header -->
        <tr><td style="padding-bottom:24px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <div style="font-size:22px;font-weight:800;color:#f1f5f9;
                            letter-spacing:-.02em;">ESM</div>
                <div style="font-size:12px;color:#475569;text-transform:uppercase;
                            letter-spacing:.1em;">Edge Sports Media</div>
              </td>
              <td align="right">
                <div style="font-size:13px;color:#475569;">{card_date}</div>
                <div style="font-size:28px;font-weight:800;color:{grade_color};
                            line-height:1;">Grade {grade}</div>
                <div style="font-size:11px;color:#475569;max-width:160px;text-align:right;">
                  {grade_note}
                </div>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- Divider -->
        <tr><td style="border-top:1px solid #1e293b;padding-bottom:20px;"></td></tr>

        {record_html}

        <!-- Official Plays -->
        <tr><td style="padding-bottom:6px;">
          <div style="font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;
                      letter-spacing:.1em;margin-bottom:14px;">
            Official Plays ({len(card.get('official_plays', []))})
          </div>
          {plays_html if plays_html else '<div style="color:#475569;font-size:14px;padding:12px 0;">No official plays — slate grade too weak.</div>'}
        </td></tr>

        {"<!-- Leans --><tr><td style='padding-bottom:6px;'><div style='font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;margin-top:8px;'>Leans</div>" + leans_html + "</td></tr>" if has_leans else ""}

        <!-- Quick Reads -->
        {"<tr><td style='padding-bottom:6px;'><div style='font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;margin-top:8px;'>Quick Reads</div><ul style='margin:0;padding-left:18px;'>" + qr_items + "</ul></td></tr>" if qr_items else ""}

        <!-- Pass Notes -->
        {"<tr><td style='padding-bottom:6px;'><div style='font-size:11px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px;margin-top:8px;'>Passes</div><ul style='margin:0;padding-left:18px;'>" + pass_items + "</ul></td></tr>" if has_passes else ""}

        <!-- Footer -->
        <tr><td style="border-top:1px solid #1e293b;padding-top:20px;padding-bottom:4px;">
          <div style="font-size:11px;color:#334155;line-height:1.6;">
            ESM cards are for informational purposes only. Gambling involves risk.
            Never bet more than you can afford to lose. Odds subject to change —
            always verify at your sportsbook before placing.
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Send functions ────────────────────────────────────────────────────────────

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

    # No email transport configured — save to file
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
