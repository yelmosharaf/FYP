"""
Weekly networking digest: reads Google Sheets, computes overdue contacts,
renders an HTML email with a PDF intelligence report, and delivers via Gmail SMTP.
"""

import os
import smtplib
import sys
from datetime import date
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import config
import sheets as sh
from insights import generate_insights
from pdf_report import build_pdf


def _days_since(last_met_str: str) -> int | None:
    d = sh._parse_date(last_met_str)
    if d is None:
        return None
    return (date.today() - d).days


def _cadence(contact: dict) -> int:
    override = str(contact.get("Cadence Override (days)", "")).strip()
    if override.isdigit():
        return int(override)
    priority = int(contact.get("Priority", 3) or 3)
    return config.CADENCE_DAYS.get(priority, 90)


def _days_overdue(contact: dict) -> int | None:
    since = _days_since(contact.get("Last Met", ""))
    cad = _cadence(contact)
    if since is None:
        return None  # never met — handled separately
    overdue = since - cad
    return overdue if overdue > 0 else None


def build_context() -> dict:
    contacts = sh.get_contacts()
    funds = sh.get_funds()
    recent_meetings = sh.get_meetings(days_back=14)
    today = date.today()
    week_label = today.strftime("%-d %B %Y")

    never_met = []
    overdue = []
    on_track = []

    for c in contacts:
        if not c.get("Name", "").strip():
            continue
        since = _days_since(c.get("Last Met", ""))
        od = _days_overdue(c)

        c["_days_since"] = since
        c["_cadence"] = _cadence(c)
        c["_days_overdue"] = od
        c["_is_urgent"] = od is not None and od >= config.URGENT_BUFFER_DAYS

        if since is None:
            never_met.append(c)
        elif od is not None:
            overdue.append(c)
        else:
            on_track.append(c)

    # Sort overdue worst-first
    overdue.sort(key=lambda c: c["_days_overdue"] or 0, reverse=True)

    # Fund coverage map: fund name → stats
    fund_map: dict[str, dict] = {}
    for f in funds:
        name = f.get("Fund Name", "").strip()
        if name:
            fund_map[name] = {
                "fund": f,
                "contacts": [],
                "last_touch_days": None,
            }
    for c in contacts:
        fn = c.get("Fund", "").strip()
        if fn not in fund_map:
            fund_map[fn] = {"fund": {"Fund Name": fn}, "contacts": [], "last_touch_days": None}
        fund_map[fn]["contacts"].append(c)
        since = c.get("_days_since")
        if since is not None:
            prev = fund_map[fn]["last_touch_days"]
            fund_map[fn]["last_touch_days"] = min(since, prev) if prev is not None else since

    fund_rows = sorted(fund_map.values(), key=lambda r: r["last_touch_days"] or 9999)

    return {
        "week_label": week_label,
        "never_met": never_met,
        "overdue": overdue,
        "on_track": on_track,
        "fund_rows": fund_rows,
        "recent_meetings": recent_meetings,
        "total_contacts": len(contacts),
        "action_count": len(never_met) + len(overdue),
    }


def render_email(context: dict) -> str:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("email.html")
    return template.render(**context)


def send_email(html: str, week_label: str, pdf_bytes: bytes | None = None) -> None:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Networking Digest — {week_label}"
    msg["From"] = config.SMTP_USER
    msg["To"] = config.DIGEST_TO

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    if pdf_bytes:
        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=f"Network_Intelligence_{date.today().strftime('%Y-%m-%d')}.pdf",
        )
        msg.attach(attachment)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.sendmail(config.SMTP_USER, config.DIGEST_TO, msg.as_string())

    print(f"Digest sent to {config.DIGEST_TO}")


def main() -> None:
    context = build_context()
    html = render_email(context)

    if "--dry-run" in sys.argv:
        out = Path("digest_preview.html")
        out.write_text(html)
        print(f"Dry run: preview written to {out.resolve()}")
        return

    pdf_bytes = None
    try:
        print("Generating network intelligence…")
        intel = generate_insights(context)
        print(f"  Network score: {intel.get('network_score')}")
        pdf_bytes = build_pdf(context, intel)
        print(f"  PDF built ({len(pdf_bytes):,} bytes)")
    except Exception as exc:
        print(f"Warning: PDF generation failed ({exc}); sending digest without attachment.")

    send_email(html, context["week_label"], pdf_bytes)


if __name__ == "__main__":
    main()
