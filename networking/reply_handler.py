"""
Reply handler: polls Gmail for replies to digest emails, uses Claude to parse
them into structured meeting notes, updates Google Sheets, and sends confirmation.

Runs every hour via GitHub Actions. Can also be run manually:
    python reply_handler.py
"""

import email as _email
import imaplib
import json
import os
import re
import smtplib
import textwrap
from datetime import date
from email.header import decode_header as _decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic

import config
import sheets as sh


# ---------------------------------------------------------------------------
# Gmail IMAP helpers
# ---------------------------------------------------------------------------

IMAP_HOST = "imap.gmail.com"
DIGEST_SUBJECT_MARKER = "Networking Digest"


def _imap_connect() -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(config.SMTP_USER, config.SMTP_PASSWORD)
    return conn


def _decode_header_value(value: str) -> str:
    parts = _decode_header(value or "")
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            out.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(part)
    return " ".join(out)


def _extract_text_body(msg: _email.message.Message) -> str:
    """Return the plain-text body of an email, stripping quoted history."""
    body_parts = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                body_parts.append(payload.decode(charset, errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        charset = msg.get_content_charset() or "utf-8"
        body_parts.append(payload.decode(charset, errors="replace"))

    full = "\n".join(body_parts)

    # Strip quoted history (lines starting with > or "On ... wrote:")
    lines = full.splitlines()
    clean = []
    for line in lines:
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        clean.append(line)
    return "\n".join(clean).strip()


def fetch_unread_replies() -> list[dict]:
    """Return unread replies to digest emails from the inbox."""
    conn = _imap_connect()
    conn.select("INBOX")

    # Search for unread mails with "Re: Networking Digest" in subject
    _, data = conn.search(None, f'(UNSEEN SUBJECT "Re: {DIGEST_SUBJECT_MARKER}")')
    ids = data[0].split()

    results = []
    for uid in ids:
        _, msg_data = conn.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = _email.message_from_bytes(raw)

        subject = _decode_header_value(msg.get("Subject", ""))
        sender = _decode_header_value(msg.get("From", ""))
        body = _extract_text_body(msg)

        results.append({"uid": uid, "subject": subject, "from": sender, "body": body})

    conn.close()
    conn.logout()
    return results


def mark_as_read(uids: list[bytes]) -> None:
    conn = _imap_connect()
    conn.select("INBOX")
    for uid in uids:
        conn.store(uid, "+FLAGS", "\\Seen")
    conn.close()
    conn.logout()


# ---------------------------------------------------------------------------
# Claude parsing
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an assistant that parses email replies to a networking digest for a finance professional covering London credit funds.

Extract structured data from the email. Return ONLY valid JSON matching this schema exactly:
{
  "meetings": [
    {
      "contact": "<full name>",
      "date": "<YYYY-MM-DD, use today if not specified>",
      "type": "<Coffee | Lunch | Call | Conference | Drinks | Other>",
      "notes": "<what was discussed>",
      "action_items": "<any follow-ups mentioned>",
      "follow_up_by": "<YYYY-MM-DD or empty string>"
    }
  ],
  "contact_updates": [
    {
      "name": "<contact name>",
      "field": "<Role | Fund | Priority | Background | Tags | Email>",
      "value": "<new value>"
    }
  ],
  "new_contacts": [
    {
      "name": "<full name>",
      "fund": "<fund name>",
      "role": "<job title>",
      "linkedin": "<URL or empty>",
      "background": "<any context mentioned>",
      "priority": "<1 | 2 | 3>"
    }
  ],
  "summary": "<one sentence summarising what was logged>"
}

If nothing actionable is found, return all arrays empty and summary as "No updates found."
Today's date is PLACEHOLDER_DATE.
"""


def parse_reply_with_claude(body: str) -> dict:
    system = SYSTEM_PROMPT.replace("PLACEHOLDER_DATE", str(date.today()))
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": body}],
    )
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Apply updates to Google Sheets
# ---------------------------------------------------------------------------

def apply_updates(parsed: dict) -> list[str]:
    """Write parsed data to Google Sheets. Returns human-readable change lines."""
    changes = []
    book = sh._book()

    # 1. Log meetings + update Last Met
    for m in parsed.get("meetings", []):
        contact = m.get("contact", "").strip()
        if not contact:
            continue
        sh.log_meeting(
            contact_name=contact,
            fund=_fund_for_contact(book, contact),
            meeting_date=m.get("date", str(date.today())),
            meeting_type=m.get("type", "Meeting"),
            notes=m.get("notes", ""),
            action_items=m.get("action_items", ""),
            follow_up_by=m.get("follow_up_by", ""),
        )
        changes.append(f"Logged meeting with {contact} on {m.get('date')} ({m.get('type')})")

    # 2. Contact field updates
    ws_contacts = book.worksheet(sh.TAB_CONTACTS)
    records = ws_contacts.get_all_records()
    headers = ws_contacts.row_values(1)

    for upd in parsed.get("contact_updates", []):
        name = upd.get("name", "").strip().lower()
        field = upd.get("field", "").strip()
        value = upd.get("value", "")
        if field not in headers:
            continue
        col = headers.index(field) + 1
        for i, row in enumerate(records, start=2):
            if row.get("Name", "").strip().lower() == name:
                ws_contacts.update_cell(i, col, value)
                changes.append(f"Updated {upd.get('name')} → {field}: {value}")
                break

    # 3. New contacts
    for nc in parsed.get("new_contacts", []):
        name = nc.get("name", "").strip()
        if not name:
            continue
        # Check not already present
        existing_names = [r.get("Name", "").strip().lower() for r in records]
        if name.lower() in existing_names:
            changes.append(f"Skipped duplicate contact: {name}")
            continue
        new_id = str(len(records) + 1)
        ws_contacts.append_row(
            [
                new_id, name, nc.get("fund", ""), nc.get("role", ""),
                nc.get("linkedin", ""), "",
                "", nc.get("priority", "2"), "",
                nc.get("background", ""), "",
            ],
            value_input_option="USER_ENTERED",
        )
        changes.append(f"Added new contact: {name} ({nc.get('fund', 'unknown fund')})")

    return changes


def _fund_for_contact(book: sh.gspread.Spreadsheet, name: str) -> str:
    ws = book.worksheet(sh.TAB_CONTACTS)
    for row in ws.get_all_records():
        if row.get("Name", "").strip().lower() == name.strip().lower():
            return row.get("Fund", "")
    return ""


# ---------------------------------------------------------------------------
# Confirmation email
# ---------------------------------------------------------------------------

CONFIRMATION_HTML = """\
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background:#f0f2f5; color:#1a1a2e; margin:0; padding:0; }}
  .wrapper {{ max-width:560px; margin:0 auto; padding:24px 16px; }}
  .header {{ background:linear-gradient(135deg,#0d1b3e,#1a3a6b); border-radius:12px;
             padding:24px; margin-bottom:20px; color:white; }}
  .header h1 {{ font-size:18px; font-weight:700; margin:0 0 4px; }}
  .header p {{ font-size:12px; color:#8ba8d4; margin:0; }}
  .card {{ background:white; border-radius:10px; padding:16px 20px;
           border-left:4px solid #22c55e; box-shadow:0 1px 3px rgba(0,0,0,.06);
           margin-bottom:10px; }}
  .card h3 {{ font-size:13px; font-weight:700; color:#111827; margin:0 0 8px; }}
  .change {{ font-size:13px; color:#374151; padding:4px 0;
             border-bottom:1px solid #f3f4f6; }}
  .change:last-child {{ border-bottom:none; }}
  .summary {{ background:#eff6ff; border-radius:8px; padding:12px 16px;
              font-size:13px; color:#1d4ed8; margin-top:16px; }}
  .footer {{ text-align:center; font-size:11px; color:#9ca3af; padding:20px 0 4px; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Sheet Updated</h1>
    <p>Your networking digest reply has been processed</p>
  </div>
  <div class="card">
    <h3>Changes Applied</h3>
    {change_rows}
  </div>
  <div class="summary">{summary}</div>
  <div class="footer">Reply again anytime to log more meetings or update contacts.</div>
</div>
</body>
</html>
"""


def send_confirmation(changes: list[str], summary: str) -> None:
    change_rows = "".join(
        f'<div class="change">&#10003; {c}</div>' for c in changes
    ) or '<div class="change">No changes were applied.</div>'

    html = CONFIRMATION_HTML.format(change_rows=change_rows, summary=summary)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Sheet Updated — Networking Digest"
    msg["From"] = config.SMTP_USER
    msg["To"] = config.DIGEST_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USER, config.DIGEST_TO, msg.as_string())

    print(f"Confirmation sent → {config.DIGEST_TO}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Checking Gmail for digest replies…")
    replies = fetch_unread_replies()

    if not replies:
        print("No new replies found.")
        return

    print(f"Found {len(replies)} reply(ies) to process.")
    processed_uids = []

    for reply in replies:
        print(f"  Processing: {reply['subject']}")
        try:
            parsed = parse_reply_with_claude(reply["body"])
            print(f"  Parsed: {parsed.get('summary', '')}")

            changes = apply_updates(parsed)
            send_confirmation(changes, parsed.get("summary", "No updates found."))
            processed_uids.append(reply["uid"])
        except Exception as exc:
            print(f"  ERROR: {exc}")

    if processed_uids:
        mark_as_read(processed_uids)
        print(f"Marked {len(processed_uids)} email(s) as read.")


if __name__ == "__main__":
    main()
