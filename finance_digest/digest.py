#!/usr/bin/env python3
"""
Daily Finance Digest
Fetches equity & credit market articles from RSS feeds,
generates a PDF table, and emails it to the recipient.
"""

import os
import io
import smtplib
import ssl
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "elmusharf@gmail.com")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")        # your Gmail address
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")  # Gmail App Password

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465  # SSL

MAX_ARTICLES_PER_SOURCE = 8  # cap per feed to keep digest manageable

# ---------------------------------------------------------------------------
# RSS Feed definitions
# Topics: equity markets, credit markets, macro
# ---------------------------------------------------------------------------

FEEDS = [
    {
        "source": "Reuters Markets",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "category": "Equity / Macro",
    },
    {
        "source": "Yahoo Finance",
        "url": "https://finance.yahoo.com/rss/topstories",
        "category": "Equity / Macro",
    },
    {
        "source": "MarketWatch Top Stories",
        "url": "http://feeds.marketwatch.com/marketwatch/topstories/",
        "category": "Equity / Macro",
    },
    {
        "source": "CNBC Markets",
        "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",
        "category": "Equity",
    },
    {
        "source": "Investopedia",
        "url": "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_articles",
        "category": "Equity / Credit",
    },
    {
        "source": "FT Markets",
        "url": "https://www.ft.com/markets?format=rss",
        "category": "Equity / Credit",
    },
    {
        "source": "WSJ Markets",
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "category": "Equity / Credit",
    },
    {
        "source": "Seeking Alpha Markets",
        "url": "https://seekingalpha.com/market_currents.xml",
        "category": "Equity / Credit",
    },
]

# Keywords to filter for credit / equity relevance
CREDIT_KEYWORDS = {
    "credit", "bond", "yield", "spread", "cds", "high yield", "investment grade",
    "ig ", "hy ", "fixed income", "debt", "coupon", "treasury", "bund", "gilt",
    "leveraged loan", "structured", "clo", "securit", "default", "rating",
    "moody", "s&p", "fitch", "junk", "issuance", "corporate bond",
}
EQUITY_KEYWORDS = {
    "stock", "equit", "share", "market", "s&p", "nasdaq", "dow", "ftse", "dax",
    "nikkei", "hang seng", "earnings", "ipo", "dividend", "buyback", "valuation",
    "pe ratio", "bull", "bear", "rally", "sell-off", "index",
}


# ---------------------------------------------------------------------------
# RSS parsing (no feedparser dependency)
# ---------------------------------------------------------------------------

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FinanceDigestBot/1.0; "
        "+https://github.com/yelmosharaf/FYP)"
    )
}


def _text(el, *tags):
    """Return stripped text of the first matching child tag."""
    for tag in tags:
        child = el.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def fetch_rss(feed_info: dict) -> list[dict]:
    """Download and parse an RSS/Atom feed, return list of article dicts."""
    try:
        resp = requests.get(feed_info["url"], headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [WARN] {feed_info['source']}: {exc}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        print(f"  [WARN] {feed_info['source']} XML parse error: {exc}")
        return []

    # Detect RSS vs Atom
    tag = root.tag.lower()
    if "feed" in tag:
        # Atom
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        items = []
        for e in entries:
            title = _text(e, "{http://www.w3.org/2005/Atom}title")
            link_el = e.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            pub = _text(e, "{http://www.w3.org/2005/Atom}updated",
                        "{http://www.w3.org/2005/Atom}published")
            items.append({"title": title, "link": link, "published": pub})
        return items
    else:
        # RSS 2.0 / RDF
        channel = root.find("channel")
        if channel is None:
            channel = root
        raw_items = channel.findall("item")
        items = []
        for e in raw_items:
            title = _text(e, "title")
            link = _text(e, "link")
            pub = _text(e, "pubDate", "dc:date",
                        "{http://purl.org/dc/elements/1.1/}date")
            items.append({"title": title, "link": link, "published": pub})
        return items


def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in EQUITY_KEYWORDS | CREDIT_KEYWORDS)


def classify(title: str) -> str:
    t = title.lower()
    has_credit = any(kw in t for kw in CREDIT_KEYWORDS)
    has_equity = any(kw in t for kw in EQUITY_KEYWORDS)
    if has_credit and has_equity:
        return "Equity & Credit"
    if has_credit:
        return "Credit"
    if has_equity:
        return "Equity"
    return "Macro"


def gather_articles() -> list[dict]:
    """Pull articles from all feeds, deduplicate by title."""
    seen_titles: set[str] = set()
    articles: list[dict] = []

    for feed in FEEDS:
        print(f"  Fetching {feed['source']} ...")
        items = fetch_rss(feed)
        count = 0
        for item in items:
            title = item.get("title", "").strip()
            if not title or title.lower() in seen_titles:
                continue
            if not is_relevant(title):
                continue
            seen_titles.add(title.lower())
            articles.append({
                "source": feed["source"],
                "category": classify(title),
                "title": title,
                "link": item.get("link", ""),
                "published": item.get("published", ""),
            })
            count += 1
            if count >= MAX_ARTICLES_PER_SOURCE:
                break

    # Sort: Credit first, then Equity, then others
    order = {"Credit": 0, "Equity & Credit": 1, "Equity": 2, "Macro": 3}
    articles.sort(key=lambda a: (order.get(a["category"], 9), a["source"]))
    return articles


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

CATEGORY_COLORS = {
    "Credit": colors.HexColor("#d4edff"),
    "Equity & Credit": colors.HexColor("#dff5e1"),
    "Equity": colors.HexColor("#fff8dc"),
    "Macro": colors.HexColor("#f5f5f5"),
}

HEADER_BG = colors.HexColor("#1a3a5c")
ALT_ROW = colors.HexColor("#f9f9f9")


def build_pdf(articles: list[dict]) -> bytes:
    """Render articles into a PDF and return bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DigestTitle",
        parent=styles["Title"],
        fontSize=18,
        textColor=HEADER_BG,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DigestSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=12,
    )
    cell_style = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        wordWrap="CJK",
    )
    link_style = ParagraphStyle(
        "Link",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.HexColor("#1155cc"),
        leading=10,
    )
    header_style = ParagraphStyle(
        "Header",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )

    today = datetime.now().strftime("%A, %d %B %Y")
    elements = [
        Paragraph("Daily Finance Digest", title_style),
        Paragraph(f"Equity & Credit Markets  —  {today}", subtitle_style),
        Spacer(1, 0.3 * cm),
    ]

    # Build table data
    col_widths = [3.5 * cm, 3.2 * cm, 12.5 * cm, 7.5 * cm]
    headers = ["#", "Category", "Article Title", "Source & Link"]
    header_row = [Paragraph(h, header_style) for h in headers]
    data = [header_row]

    for idx, art in enumerate(articles, start=1):
        title_para = Paragraph(art["title"], cell_style)
        link_text = (
            f'<link href="{art["link"]}">{art["link"][:70]}{"…" if len(art["link"]) > 70 else ""}</link>'
            if art["link"] else "—"
        )
        source_para = Paragraph(
            f'<b>{art["source"]}</b><br/>{link_text}', link_style
        )
        data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(art["category"], cell_style),
            title_para,
            source_para,
        ])

    table = Table(data, colWidths=col_widths, repeatRows=1)

    # Row background colours
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    # Colour category column per type
    for i, art in enumerate(articles, start=1):
        bg = CATEGORY_COLORS.get(art["category"], colors.white)
        row_styles.append(("BACKGROUND", (1, i), (1, i), bg))

    table.setStyle(TableStyle(row_styles))
    elements.append(table)

    # Footer note
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(
        Paragraph(
            f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}  |  "
            f"{len(articles)} articles from {len(FEEDS)} sources",
            ParagraphStyle("Footer", parent=styles["Normal"],
                           fontSize=7, textColor=colors.grey,
                           alignment=TA_CENTER),
        )
    )

    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(pdf_bytes: bytes, article_count: int) -> None:
    if not SENDER_EMAIL or not SENDER_APP_PASSWORD:
        raise ValueError(
            "SENDER_EMAIL and SENDER_APP_PASSWORD must be set in .env"
        )

    today = datetime.now().strftime("%d %b %Y")
    subject = f"Finance Digest — {today} ({article_count} articles)"

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECIPIENT_EMAIL
    msg["Subject"] = subject

    body = (
        f"Hi,\n\n"
        f"Your daily finance digest for {today} is attached.\n\n"
        f"Today's digest covers {article_count} articles across equity and credit markets.\n\n"
        f"Sources: Reuters, Yahoo Finance, MarketWatch, CNBC, Investopedia, FT, WSJ, Seeking Alpha\n\n"
        f"—\nFinance Digest Bot"
    )
    msg.attach(MIMEText(body, "plain"))

    filename = f"finance_digest_{datetime.now().strftime('%Y%m%d')}.pdf"
    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())

    print(f"  Email sent to {RECIPIENT_EMAIL}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*60}")
    print(f"  Finance Digest  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print("[1/3] Fetching articles ...")
    articles = gather_articles()
    print(f"  → {len(articles)} relevant articles collected\n")

    if not articles:
        print("No articles found. Check network / feed URLs.")
        return

    print("[2/3] Building PDF ...")
    pdf_bytes = build_pdf(articles)
    print(f"  → PDF size: {len(pdf_bytes) / 1024:.1f} KB\n")

    print("[3/3] Sending email ...")
    send_email(pdf_bytes, len(articles))

    print("\nDone.\n")


if __name__ == "__main__":
    main()
