#!/usr/bin/env python3
"""
Daily Finance Digest
Fetches equity & credit market articles from RSS feeds,
generates a PDF table, and emails it to the recipient.
"""

import base64
import email.utils
import os
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape as xml_escape

import requests
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
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
RESEND_API_KEY  = os.getenv("RESEND_API_KEY", "")   # get free key at resend.com
SENDER_FROM     = "Finance Digest <onboarding@resend.dev>"  # Resend free-tier sender

MAX_ARTICLES_PER_SOURCE = 10  # cap per feed
CUTOFF_DAYS = 30              # ignore articles older than this

# ---------------------------------------------------------------------------
# RSS Feed definitions
# section: "general" = equity/credit markets
#          "hy"      = high yield & distressed specialists
# ---------------------------------------------------------------------------

FEEDS = [
    # ── General markets ──────────────────────────────────────────────────────
    {"section": "general", "source": "Yahoo Finance",
     "url": "https://finance.yahoo.com/rss/topstories"},
    {"section": "general", "source": "CNBC Markets",
     "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"section": "general", "source": "CNBC Finance",
     "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
    {"section": "general", "source": "MarketWatch",
     "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
    {"section": "general", "source": "WSJ Markets",
     "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"section": "general", "source": "WSJ Business",
     "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"},
    {"section": "general", "source": "FT",
     "url": "https://www.ft.com/rss/home/uk"},
    {"section": "general", "source": "Bloomberg Markets",
     "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"section": "general", "source": "Reuters Business",
     "url": "https://feeds.reuters.com/reuters/businessNews"},

    # ── HY & Distressed specialists ───────────────────────────────────────
    {"section": "hy", "source": "9fin",
     "url": "https://9fin.com/rss"},
    {"section": "hy", "source": "Debtwire",
     "url": "https://www.debtwire.com/info/rss"},
    {"section": "hy", "source": "Octus (Reorg)",
     "url": "https://reorg.com/feed/"},
    {"section": "hy", "source": "Bloomberg Credit",
     "url": "https://feeds.bloomberg.com/blaw/news.rss"},
    {"section": "hy", "source": "S&P LCD",
     "url": "https://www.lcdcomps.com/lcd/rss.html"},
]

# Keywords — general section filter
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

# Keywords — HY/distressed section (articles from any feed matching these
# also flow into the HY section even if from a general source)
HY_KEYWORDS = {
    "high yield", "distressed", "restructur", "bankruptcy", "chapter 11",
    "chapter 7", "default", "leveraged loan", "leveraged buyout", "lbo",
    "fallen angel", "ccc", "b-rated", "payment-in-kind", "pik", "covenant",
    "special situation", "stressed credit", "workout", "debt exchange",
    "liability management", "lme ", "out-of-court", "in-court",
    "9fin", "debtwire", "reorg", "octus", "lcd ",
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


def parse_date(raw: str) -> datetime | None:
    """Return timezone-aware datetime from an RSS/Atom date string, or None."""
    raw = raw.strip()
    if not raw:
        return None
    # RFC 2822 (RSS pubDate): "Fri, 04 Apr 2026 07:00:00 +0000"
    try:
        return email.utils.parsedate_to_datetime(raw)
    except Exception:
        pass
    # ISO 8601 (Atom): "2026-04-04T07:00:00Z" / "+00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def is_within_cutoff(raw: str) -> bool:
    dt = parse_date(raw)
    if dt is None:
        return True  # keep if we can't parse
    cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
    return dt >= cutoff


def is_hy(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in HY_KEYWORDS)


def is_general(title: str) -> bool:
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


def _sort_key(article: dict):
    """Sort newest-first; articles with no date go to the end."""
    dt = parse_date(article.get("published", ""))
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt


def gather_articles() -> tuple[list[dict], list[dict]]:
    """
    Returns (general_articles, hy_articles) both sorted newest-first,
    filtered to the last CUTOFF_DAYS days.
    """
    seen_titles: set[str] = set()
    general: list[dict] = []
    hy: list[dict] = []

    for feed in FEEDS:
        print(f"  Fetching {feed['source']} ...")
        items = fetch_rss(feed)
        count = 0
        for item in items:
            title = item.get("title", "").strip()
            if not title or title.lower() in seen_titles:
                continue
            pub = item.get("published", "")
            if not is_within_cutoff(pub):
                continue  # older than 30 days
            seen_titles.add(title.lower())

            art = {
                "source": feed["source"],
                "category": classify(title),
                "title": title,
                "link": item.get("link", ""),
                "published": pub,
            }

            # HY feeds always go to HY section; general feeds split by keyword
            if feed["section"] == "hy" or is_hy(title):
                hy.append(art)
            elif is_general(title):
                general.append(art)
            else:
                continue  # irrelevant

            count += 1
            if count >= MAX_ARTICLES_PER_SOURCE:
                break

    general.sort(key=_sort_key, reverse=True)
    hy.sort(key=_sort_key, reverse=True)
    return general, hy


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


_DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z",   # RSS: Mon, 04 Apr 2026 07:00:00 +0000
    "%a, %d %b %Y %H:%M:%S GMT",   # RSS no-offset variant
    "%Y-%m-%dT%H:%M:%S%z",         # Atom: 2026-04-04T07:00:00+00:00
    "%Y-%m-%dT%H:%M:%SZ",          # Atom UTC
    "%Y-%m-%d",
]

def fmt_date(raw: str) -> str:
    """Parse a raw RSS/Atom date string and return e.g. '04 Apr 09:00'."""
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%d %b %H:%M")
        except ValueError:
            continue
    # fallback: return first 10 chars if we can't parse
    return raw[:10] if raw else "—"


HY_HEADER_BG = colors.HexColor("#7b2d2d")  # dark red for HY section


def _build_article_table(articles: list[dict], styles: dict, start_idx: int = 1) -> Table:
    """Build a ReportLab Table for a list of articles."""
    col_widths = [1.0 * cm, 3.0 * cm, 2.6 * cm, 11.2 * cm, 6.5 * cm]

    cell_style = styles["cell"]
    link_style = styles["link"]
    header_style = styles["header"]

    headers = ["#", "Category", "Date", "Article Title", "Source & Link"]
    data = [[Paragraph(h, header_style) for h in headers]]

    for idx, art in enumerate(articles, start=start_idx):
        safe_title  = xml_escape(art["title"])
        safe_link   = xml_escape(art["link"]) if art["link"] else ""
        safe_source = xml_escape(art["source"])
        link_text = (
            f'<link href="{safe_link}">{safe_link[:70]}{"…" if len(safe_link) > 70 else ""}</link>'
            if safe_link else "—"
        )
        data.append([
            Paragraph(str(idx), cell_style),
            Paragraph(art["category"], cell_style),
            Paragraph(fmt_date(art.get("published", "")), cell_style),
            Paragraph(safe_title, cell_style),
            Paragraph(f'<b>{safe_source}</b><br/>{link_text}', link_style),
        ])

    table = Table(data, colWidths=col_widths, repeatRows=1)
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), styles["header_bg"]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_ROW]),
        ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",   (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]
    for i, art in enumerate(articles, start=1):
        bg = CATEGORY_COLORS.get(art["category"], colors.white)
        row_styles.append(("BACKGROUND", (1, i), (1, i), bg))
    table.setStyle(TableStyle(row_styles))
    return table


def build_pdf(general: list[dict], hy: list[dict]) -> bytes:
    """Render two-section PDF and return bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    base = getSampleStyleSheet()

    def _para_style(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    shared_styles = {
        "cell": _para_style("Cell", fontSize=8, leading=11, wordWrap="CJK"),
        "link": _para_style("Link", fontSize=7, textColor=colors.HexColor("#1155cc"), leading=10),
        "header": _para_style("Hdr", fontSize=9, textColor=colors.white,
                              fontName="Helvetica-Bold", alignment=TA_CENTER),
        "header_bg": HEADER_BG,
    }
    hy_styles = {**shared_styles,
                 "header": _para_style("HdrHY", fontSize=9, textColor=colors.white,
                                       fontName="Helvetica-Bold", alignment=TA_CENTER),
                 "header_bg": HY_HEADER_BG}

    section_title = _para_style("SecTitle", fontSize=13, fontName="Helvetica-Bold",
                                textColor=HEADER_BG, spaceBefore=14, spaceAfter=4)
    hy_section_title = _para_style("SecTitleHY", fontSize=13, fontName="Helvetica-Bold",
                                   textColor=HY_HEADER_BG, spaceBefore=14, spaceAfter=4)
    cutoff_note = _para_style("CutoffNote", fontSize=8, textColor=colors.grey, spaceAfter=6)

    today = datetime.now().strftime("%A, %d %B %Y")
    cutoff_date = (datetime.now() - timedelta(days=CUTOFF_DAYS)).strftime("%d %b %Y")

    elements = [
        Paragraph("Daily Finance Digest", _para_style("Title", fontSize=18,
                  textColor=HEADER_BG, fontName="Helvetica-Bold", spaceAfter=2)),
        Paragraph(f"{today}  ·  Articles from last {CUTOFF_DAYS} days (since {cutoff_date})",
                  _para_style("Sub", fontSize=10, textColor=colors.grey, spaceAfter=10)),
    ]

    # ── Section 1: General Markets ───────────────────────────────────────────
    elements.append(Paragraph(f"Equity & Credit Markets  ({len(general)} articles)", section_title))
    if general:
        elements.append(_build_article_table(general, shared_styles, start_idx=1))
    else:
        elements.append(Paragraph("No articles found for this section.", cutoff_note))

    # ── Section 2: HY & Distressed ───────────────────────────────────────────
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        f"High Yield & Distressed  ({len(hy)} articles)  ·  Octus · 9fin · Bloomberg · Debtwire",
        hy_section_title))
    elements.append(Paragraph(
        "Sources include specialist HY/distressed feeds. Paywalled sources may show limited articles.",
        cutoff_note))
    if hy:
        elements.append(_build_article_table(hy, hy_styles, start_idx=1))
    else:
        elements.append(Paragraph(
            "No HY/distressed articles found. Specialist sources (Octus, 9fin, Debtwire) "
            "require subscriptions — their feeds may be restricted.",
            cutoff_note))

    # Footer
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  "
        f"{len(general) + len(hy)} total articles  |  {CUTOFF_DAYS}-day cutoff",
        _para_style("Footer", fontSize=7, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(elements)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(pdf_bytes: bytes, article_count: int) -> None:
    if not RESEND_API_KEY:
        raise ValueError(
            "RESEND_API_KEY is not set. Get a free key at https://resend.com"
        )

    today    = datetime.now().strftime("%d %b %Y")
    subject  = f"Finance Digest — {today} ({article_count} articles)"
    filename = f"finance_digest_{datetime.now().strftime('%Y%m%d')}.pdf"

    payload = {
        "from":    SENDER_FROM,
        "to":      [RECIPIENT_EMAIL],
        "subject": subject,
        "text":    (
            f"Hi,\n\n"
            f"Your daily finance digest for {today} is attached.\n\n"
            f"{article_count} articles across equity and credit markets.\n\n"
            f"— Finance Digest Bot"
        ),
        "attachments": [
            {
                "filename": filename,
                "content":  base64.b64encode(pdf_bytes).decode(),
            }
        ],
    }

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type":  "application/json",
        },
        json=payload,
        timeout=15,
    )

    if resp.status_code in (200, 201):
        print(f"  Email sent to {RECIPIENT_EMAIL}")
    else:
        raise RuntimeError(
            f"Resend API error {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*60}")
    print(f"  Finance Digest  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print("[1/3] Fetching articles ...")
    general, hy = gather_articles()
    print(f"  → {len(general)} general  |  {len(hy)} HY/distressed  "
          f"(cutoff: last {CUTOFF_DAYS} days)\n")

    if not general and not hy:
        print("No articles found. Check network / feed URLs.")
        return

    print("[2/3] Building PDF ...")
    pdf_bytes = build_pdf(general, hy)
    print(f"  → PDF size: {len(pdf_bytes) / 1024:.1f} KB\n")

    print("[3/3] Sending email ...")
    send_email(pdf_bytes, len(general) + len(hy))

    print("\nDone.\n")


if __name__ == "__main__":
    main()
