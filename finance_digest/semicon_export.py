#!/usr/bin/env python3
"""
Weekly Korea & Taiwan Semiconductor Export Digest
Fetches semiconductor export headlines from RSS feeds and optional official
data via the KOSIS API, then emails a clean HTML summary.

Run manually:    python semicon_export.py
GitHub Actions:  weekly-semicon-export.yml  (every Monday 07:00 UTC)

Optional GitHub secrets:
  KOSIS_API_KEY  — free key from kosis.kr/openapi for official Korea figures
"""

import email.utils
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from xml.sax.saxutils import escape as xml_escape

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RECIPIENT_EMAIL  = os.getenv("RECIPIENT_EMAIL", "elmusharf@gmail.com")
RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")
KOSIS_API_KEY    = os.getenv("KOSIS_API_KEY", "")
SENDER_FROM      = "Finance Digest <onboarding@resend.dev>"

NEWS_LOOKBACK_DAYS = 7   # look back this many days for news articles
MAX_ARTICLES_PER_FEED = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SemiconDigestBot/1.0; "
        "+https://github.com/yelmosharaf/FYP)"
    )
}

# ---------------------------------------------------------------------------
# RSS feed list
# ---------------------------------------------------------------------------

FEEDS = [
    {"source": "Reuters Technology",
     "url": "https://feeds.reuters.com/reuters/technologyNews"},
    {"source": "Bloomberg Markets",
     "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"source": "CNBC Tech",
     "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html"},
    {"source": "WSJ Tech",
     "url": "https://feeds.a.dj.com/rss/RSSWSJD.xml"},
    {"source": "Korea Herald",
     "url": "http://www.koreaherald.com/rss/020000000000.xml"},
    {"source": "Korea JoongAng Daily",
     "url": "https://koreajoongangdaily.joins.com/rss/feed.xml"},
    {"source": "DigiTimes",
     "url": "https://www.digitimes.com/rss/daily.xml"},
    {"source": "EE Times",
     "url": "https://www.eetimes.com/rss/"},
    {"source": "Nikkei Asia",
     "url": "https://asia.nikkei.com/rss/feed/nar"},
    {"source": "Yahoo Finance Tech",
     "url": "https://finance.yahoo.com/rss/topstories"},
]

# ---------------------------------------------------------------------------
# Keyword classifiers
# ---------------------------------------------------------------------------

_KOREA_KW = {
    "korea", "korean", "samsung", "sk hynix", "hynix",
    "motie", "kita", "kotra",
}
_TAIWAN_KW = {
    "taiwan", "taiwanese", "tsmc", "mediatek", "umc",
    "ase group", "taiwan semiconductor",
}
_SEMICON_KW = {
    "semiconductor", "chip", "memory", "dram", "nand", "hbm",
    "wafer", "integrated circuit", "export", "shipment",
    "foundry", "fab ", "ai chip", "logic chip",
}


def _classify(title: str) -> str:
    """Return 'korea', 'taiwan', 'both', or '' based on title keywords."""
    t = title.lower()
    if not any(kw in t for kw in _SEMICON_KW):
        return ""
    korea  = any(kw in t for kw in _KOREA_KW)
    taiwan = any(kw in t for kw in _TAIWAN_KW)
    if korea and taiwan:
        return "both"
    if korea:
        return "korea"
    if taiwan:
        return "taiwan"
    return ""


# ---------------------------------------------------------------------------
# RSS helpers
# ---------------------------------------------------------------------------

def _text(el, *tags: str) -> str:
    for tag in tags:
        child = el.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return ""


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        return email.utils.parsedate_to_datetime(raw)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _fmt_date(raw: str) -> str:
    dt = _parse_dt(raw)
    return dt.strftime("%d %b %H:%M") if dt else (raw[:10] if raw else "—")


def _parse_feed(root: ET.Element) -> list[dict]:
    """Extract raw items from an RSS 2.0 or Atom feed element."""
    if "feed" in root.tag.lower():
        ns = "http://www.w3.org/2005/Atom"
        items = []
        for e in root.findall(f"{{{ns}}}entry"):
            link_el = e.find(f"{{{ns}}}link")
            items.append({
                "title": _text(e, f"{{{ns}}}title"),
                "link":  link_el.get("href", "") if link_el is not None else "",
                "pub":   _text(e, f"{{{ns}}}updated", f"{{{ns}}}published"),
            })
        return items
    else:
        ch = root.find("channel") or root
        dc_date = "{http://purl.org/dc/elements/1.1/}date"
        return [
            {
                "title": _text(e, "title"),
                "link":  _text(e, "link"),
                "pub":   _text(e, "pubDate", dc_date),
            }
            for e in ch.findall("item")
        ]


# ---------------------------------------------------------------------------
# News fetcher
# ---------------------------------------------------------------------------

def fetch_news() -> dict[str, list]:
    """
    Scan all RSS feeds and return articles from the last NEWS_LOOKBACK_DAYS days,
    bucketed as {"korea": [...], "taiwan": [...], "both": [...]}.
    Each article: {source, title, link, published}.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_LOOKBACK_DAYS)
    seen: set[str] = set()
    buckets: dict[str, list] = {"korea": [], "taiwan": [], "both": []}

    for feed in FEEDS:
        print(f"  {feed['source']} ...", end="", flush=True)
        try:
            resp = requests.get(feed["url"], headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as exc:
            print(f" skip ({exc})")
            continue

        added = 0
        for item in _parse_feed(root):
            title = item["title"].strip()
            if not title or title.lower() in seen:
                continue
            dt = _parse_dt(item["pub"])
            if dt and dt < cutoff:
                continue
            cat = _classify(title)
            if not cat:
                continue
            seen.add(title.lower())
            buckets[cat].append({
                "source":    feed["source"],
                "title":     title,
                "link":      item["link"],
                "published": item["pub"],
            })
            added += 1
            if added >= MAX_ARTICLES_PER_FEED:
                break

        print(f" {added}")

    _sort_key = lambda a: (
        _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc)
    )
    for cat in buckets:
        buckets[cat].sort(key=_sort_key, reverse=True)

    return buckets


# ---------------------------------------------------------------------------
# Korea official data — KOSIS Open API (optional)
# ---------------------------------------------------------------------------

def fetch_korea_kosis() -> list[dict] | None:
    """
    Fetch Korea semiconductor export data via KOSIS Open API.
    Returns raw JSON records or None if the API key is absent / call fails.

    Free key: https://kosis.kr/openapi/
    The table DT_142001_007 is Korea Customs Service > Exports by commodity.
    Verify the exact table at: https://kosis.kr/statHtml/statHtml.do?orgId=142&tblId=DT_142001_007
    """
    if not KOSIS_API_KEY:
        return None

    params = {
        "method":     "getList",
        "apiKey":     KOSIS_API_KEY,
        "itmId":      "T10+",
        "objL1":      "ALL",
        "format":     "json",
        "jsonVD":     "Y",
        "prdSe":      "M",
        "startPrdDe": (datetime.now() - timedelta(days=365)).strftime("%Y%m"),
        "endPrdDe":   datetime.now().strftime("%Y%m"),
        "orgId":      "142",
        "tblId":      "DT_142001_007",
        "vwCd":       "MT_ZTITLE",
    }
    try:
        resp = requests.get(
            "https://kosis.kr/openapi/statisticsData.do",
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        # KOSIS wraps errors in the JSON body
        if isinstance(data, dict) and data.get("err"):
            print(f"  [WARN] KOSIS error: {data}")
            return None
        return data if isinstance(data, list) else None
    except Exception as exc:
        print(f"  [WARN] KOSIS API: {exc}")
        return None


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

_TH_BASE = (
    "padding:7px 10px;text-align:left;font-size:12px;font-weight:600;"
    "border-bottom:2px solid #ddd"
)
_TD = "padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top"


def _article_rows(articles: list, max_n: int = 15) -> str:
    if not articles:
        return (
            "<tr><td colspan='3' style='padding:14px;color:#888;font-style:italic'>"
            "No relevant headlines found this week.</td></tr>"
        )
    rows = []
    for a in articles[:max_n]:
        title = xml_escape(a["title"])
        src   = xml_escape(a["source"])
        date  = _fmt_date(a["published"])
        href  = a["link"]
        cell  = (
            f'<a href="{href}" style="color:#1155cc;text-decoration:none">{title}</a>'
            if href else title
        )
        rows.append(
            f"<tr>"
            f"<td style='{_TD};width:80px;color:#777;white-space:nowrap'>{date}</td>"
            f"<td style='{_TD};width:130px;color:#555'>{src}</td>"
            f"<td style='{_TD}'>{cell}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _kosis_block(kosis_data: list | None) -> str:
    if kosis_data:
        return (
            f'<p style="color:#2a7a2a;font-size:12px;margin:0 0 10px">'
            f'&#10003; Official KOSIS data loaded ({len(kosis_data)} records).</p>'
        )
    return (
        '<div style="background:#fff8e1;border-left:3px solid #f0b400;'
        'padding:10px 14px;border-radius:3px;font-size:12px;color:#555;margin-bottom:12px">'
        '<strong>Live data tip:</strong> Add <code>KOSIS_API_KEY</code> as a GitHub secret '
        'to include official monthly figures from Statistics Korea. '
        'Free key at <a href="https://kosis.kr/openapi/" style="color:#1155cc">kosis.kr/openapi</a>.'
        '</div>'
    )


def build_html(news: dict, kosis_data: list | None) -> str:
    today    = datetime.now().strftime("%A, %d %B %Y")
    gen_ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total    = sum(len(v) for v in news.values())

    korea_articles  = news.get("korea", []) + news.get("both", [])
    taiwan_articles = news.get("taiwan", []) + news.get("both", [])

    korea_articles.sort(
        key=lambda a: _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    taiwan_articles.sort(
        key=lambda a: _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    th_navy = f"{_TH_BASE};background:#eef2f8"
    th_red  = f"{_TH_BASE};background:#fdf0f0"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Weekly Semiconductor Export Digest</title>
</head>
<body style="margin:0;padding:20px;font-family:Arial,Helvetica,sans-serif;
             background:#f0f4f8;color:#222">
<div style="max-width:880px;margin:0 auto">

  <!-- Header -->
  <div style="background:#1a3a5c;color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h1 style="margin:0;font-size:20px;font-weight:700">
      Weekly Semiconductor Export Digest
    </h1>
    <p style="margin:5px 0 0;font-size:13px;opacity:.75">
      {today} &nbsp;&middot;&nbsp; Korea &amp; Taiwan
      &nbsp;&middot;&nbsp; {total} headlines compiled
    </p>
  </div>

  <!-- Korea section -->
  <div style="background:white;padding:22px 24px;border:1px solid #dce3ec;border-top:none">
    <h2 style="margin:0 0 5px;font-size:16px;color:#1a3a5c">
      &#127472;&#127479; Korea Semiconductor Exports
    </h2>
    <p style="margin:0 0 14px;font-size:12px;color:#666;line-height:1.6">
      ~80&ndash;85&percnt; of Korea&rsquo;s semiconductor exports are memory (DRAM + NAND).
      Samsung &amp; SK Hynix are the two largest memory producers on Earth.
      Monthly MOTIE data is a leading indicator for the global memory cycle (2&ndash;4 week lag).
    </p>

    {_kosis_block(kosis_data)}

    <h3 style="font-size:12px;color:#555;margin:14px 0 6px;
               text-transform:uppercase;letter-spacing:.6px">
      This week&rsquo;s coverage
    </h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr>
        <th style="{th_navy};width:80px">Date</th>
        <th style="{th_navy};width:130px">Source</th>
        <th style="{th_navy}">Headline</th>
      </tr></thead>
      <tbody>{_article_rows(korea_articles)}</tbody>
    </table>
  </div>

  <!-- Gap -->
  <div style="height:8px;background:#f0f4f8"></div>

  <!-- Taiwan section -->
  <div style="background:white;padding:22px 24px;border:1px solid #dce3ec">
    <h2 style="margin:0 0 5px;font-size:16px;color:#8b1a1a">
      &#127481;&#127484; Taiwan Semiconductor Exports
    </h2>
    <p style="margin:0 0 14px;font-size:12px;color:#666;line-height:1.6">
      TSMC captures ~90&percnt; of advanced-node foundry revenue globally.
      Taiwan&rsquo;s monthly Ministry of Finance export data tracks logic/AI chip demand &mdash;
      a strong complement to Korea&rsquo;s memory cycle signal.
    </p>

    <div style="background:#fff8e1;border-left:3px solid #f0b400;
        padding:10px 14px;border-radius:3px;font-size:12px;color:#555;margin-bottom:12px">
      <strong>Official data:</strong> Taiwan Ministry of Finance publishes monthly trade statistics at
      <a href="https://www.mof.gov.tw/" style="color:#1155cc">mof.gov.tw</a>.
      The IC/semiconductor line item (HS 8541&ndash;8542) is released on the 1st week of each month.
    </div>

    <h3 style="font-size:12px;color:#555;margin:14px 0 6px;
               text-transform:uppercase;letter-spacing:.6px">
      This week&rsquo;s coverage
    </h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr>
        <th style="{th_red};width:80px">Date</th>
        <th style="{th_red};width:130px">Source</th>
        <th style="{th_red}">Headline</th>
      </tr></thead>
      <tbody>{_article_rows(taiwan_articles)}</tbody>
    </table>
  </div>

  <!-- Footer -->
  <div style="background:white;padding:12px 24px;border:1px solid #dce3ec;border-top:none;
              border-radius:0 0 8px 8px;text-align:center;font-size:11px;color:#aaa">
    Generated {gen_ts} &nbsp;&middot;&nbsp; Weekly Semiconductor Export Digest
    &nbsp;&middot;&nbsp; github.com/yelmosharaf/FYP
  </div>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email dispatch
# ---------------------------------------------------------------------------

def send_email(html_body: str, article_count: int) -> None:
    if not RESEND_API_KEY:
        raise ValueError(
            "RESEND_API_KEY is not set. Get a free key at https://resend.com"
        )

    today   = datetime.now().strftime("%d %b %Y")
    subject = f"Semiconductor Export Digest — {today}"

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "from":    SENDER_FROM,
            "to":      [RECIPIENT_EMAIL],
            "subject": subject,
            "html":    html_body,
            "text": (
                f"Semiconductor Export Digest — {today}\n\n"
                f"Korea & Taiwan semiconductor export summary.\n"
                f"{article_count} headlines compiled this week.\n\n"
                f"— Finance Digest Bot"
            ),
        },
        timeout=15,
    )

    if resp.status_code in (200, 201):
        print(f"  Sent to {RECIPIENT_EMAIL}")
    else:
        raise RuntimeError(
            f"Resend API error {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{'='*60}")
    print(f"  Weekly Semiconductor Export Digest")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    print("[1/3] Fetching semiconductor headlines ...")
    news  = fetch_news()
    total = sum(len(v) for v in news.values())
    print(
        f"\n  Korea: {len(news['korea'])}"
        f"  |  Taiwan: {len(news['taiwan'])}"
        f"  |  Both: {len(news['both'])}"
        f"  |  Total: {total}\n"
    )

    print("[2/3] Fetching official data ...")
    kosis = fetch_korea_kosis()
    status = f"loaded ({len(kosis)} records)" if kosis else "skipped (no KOSIS_API_KEY)"
    print(f"  KOSIS: {status}\n")

    print("[3/3] Sending email ...")
    html = build_html(news, kosis)
    send_email(html, total)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
