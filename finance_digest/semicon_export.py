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

# Company names alone imply both country AND semiconductor — no extra keyword needed
_KOREA_COMPANIES  = {"samsung", "sk hynix", "hynix", "sk telecom"}
_TAIWAN_COMPANIES = {"tsmc", "mediatek", "umc", "ase group", "taiwan semiconductor"}

# Geographic keywords still need a semiconductor word alongside them
_KOREA_GEO  = {"korea", "korean", "motie", "kita", "kotra"}
_TAIWAN_GEO = {"taiwan", "taiwanese"}

_SEMICON_KW = {
    "semiconductor", "chip", "chips", "memory", "dram", "nand", "hbm",
    "wafer", "integrated circuit", "export", "shipment",
    "foundry", "fab", "ai chip", "logic chip", "packaging",
    "earnings", "revenue", "production", "output", "capacity",
}


def _classify(title: str) -> str:
    """Return 'korea', 'taiwan', 'both', or '' based on title keywords."""
    t = title.lower()
    korea_co  = any(kw in t for kw in _KOREA_COMPANIES)
    taiwan_co = any(kw in t for kw in _TAIWAN_COMPANIES)
    has_semicon = any(kw in t for kw in _SEMICON_KW)
    korea_geo   = any(kw in t for kw in _KOREA_GEO)
    taiwan_geo  = any(kw in t for kw in _TAIWAN_GEO)

    # Company name alone is enough; geo keywords require a semicon word too
    korea  = korea_co  or (has_semicon and korea_geo)
    taiwan = taiwan_co or (has_semicon and taiwan_geo)

    if not (korea or taiwan):
        return ""
    if korea and taiwan:
        return "both"
    return "korea" if korea else "taiwan"


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
# Korea official data — KOSIS Open API (free key at kosis.kr/openapi)
# ---------------------------------------------------------------------------

def fetch_korea_data() -> list[dict] | None:
    """
    Fetch Korea semiconductor monthly export figures via KOSIS Open API.
    Returns parsed list [{month, value_usd_bn, unit_raw}] or None.
    Free key: https://kosis.kr/openapi/
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
        "orgId":      "142",   # Korea Customs Service
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
        raw = resp.json()
        if isinstance(raw, dict) and raw.get("err"):
            print(f"  [WARN] KOSIS error: {raw}")
            return None
        if not isinstance(raw, list):
            return None
        return _parse_kosis(raw)
    except Exception as exc:
        print(f"  [WARN] KOSIS: {exc}")
        return None


def _parse_kosis(records: list) -> list[dict]:
    """Convert raw KOSIS list into [{month, label, value_usd_bn, unit}] newest-first."""
    out = []
    for r in records:
        period = r.get("PRD_DE", "")      # e.g. "202504"
        value  = r.get("DT", "").replace(",", "").strip()
        unit   = r.get("UNIT_NM", "")     # e.g. "백만달러" = million USD
        itm    = r.get("ITM_NM_ENG") or r.get("ITM_NM", "")
        if not period or not value:
            continue
        try:
            val_f = float(value)
        except ValueError:
            continue
        # Convert million USD → billion USD for display
        val_bn = val_f / 1000 if "백만" in unit or "million" in unit.lower() else val_f
        try:
            label = datetime.strptime(period, "%Y%m").strftime("%b %Y")
        except ValueError:
            label = period
        out.append({"month": period, "label": label,
                    "value_bn": val_bn, "item": itm, "unit": unit})
    # Sort newest first, deduplicate by month+item
    seen: set[str] = set()
    result = []
    for r in sorted(out, key=lambda x: x["month"], reverse=True):
        key = f"{r['month']}|{r['item']}"
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result[:12]  # last 12 months


# ---------------------------------------------------------------------------
# Taiwan official data — Taiwan gov open data portal (no key needed)
# ---------------------------------------------------------------------------

def fetch_taiwan_data() -> list[dict] | None:
    """
    Fetch Taiwan monthly semiconductor export data from data.gov.tw (no API key).
    Returns parsed list [{month, label, value_bn, category}] or None.
    Source: Taiwan MOF monthly export statistics by HS commodity code.
    """
    # Taiwan open data — MOF monthly export by commodity (HS level)
    # Dataset: 301000000A-000154-002  (trade stats by 2-digit HS)
    ENDPOINTS = [
        "https://data.gov.tw/api/v2/rest/datastore/301000000A-000154-002",
        "https://data.gov.tw/api/v2/rest/datastore/301000000A-000154-001",
    ]
    for url in ENDPOINTS:
        try:
            resp = requests.get(
                url,
                params={"format": "json", "limit": 100},
                headers=HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            body = resp.json()
            records = (body.get("result") or {}).get("records") or []
            if records:
                parsed = _parse_taiwan(records)
                if parsed:
                    print(f"  Taiwan: {len(parsed)} records from {url}")
                    return parsed
        except Exception as exc:
            print(f"  [WARN] Taiwan {url}: {exc}")

    # Fallback: Taiwan Customs Administration open data
    try:
        resp = requests.get(
            "https://data.gov.tw/api/v2/rest/datastore/6484",
            params={"format": "json", "limit": 100},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        records = (body.get("result") or {}).get("records") or []
        if records:
            parsed = _parse_taiwan(records)
            if parsed:
                return parsed
    except Exception as exc:
        print(f"  [WARN] Taiwan fallback: {exc}")

    return None


def _parse_taiwan(records: list) -> list[dict]:
    """
    Try to extract semiconductor (HS 8541/8542) monthly export rows.
    Returns [{month, label, value_bn, category}] newest-first.
    """
    out = []
    for r in records:
        # Look for HS code fields under various possible key names
        hs = str(r.get("HS", "") or r.get("hs_code", "") or r.get("商品", "") or "")
        if hs and not any(c in hs for c in ("8541", "8542", "85")):
            continue  # skip non-semiconductor rows if we can identify the field

        # Find a period field
        period_raw = (r.get("年月") or r.get("period") or r.get("date")
                      or r.get("Month") or r.get("yearmonth") or "")
        # Find a value field (export value, likely in million USD or NTD)
        value_raw = (r.get("出口値") or r.get("export_value") or r.get("Export")
                     or r.get("value") or r.get("Value") or "")

        if not period_raw or not value_raw:
            out.append({"month": "", "label": "", "value_bn": None,
                        "category": "", "_raw": r})
            continue

        period_s = str(period_raw).replace("/", "").replace("-", "").strip()
        # Taiwan uses ROC calendar (year since 1912), convert if needed
        if len(period_s) == 5 and period_s.isdigit():
            roc_year  = int(period_s[:3])
            month_num = int(period_s[3:])
            ad_year   = roc_year + 1911
            period_s  = f"{ad_year}{month_num:02d}"
        try:
            label = datetime.strptime(period_s[:6], "%Y%m").strftime("%b %Y")
        except ValueError:
            label = period_raw

        try:
            val = float(str(value_raw).replace(",", "").strip())
            val_bn = round(val / 30_000, 2) if val > 10_000 else round(val / 1000, 2)
        except (ValueError, TypeError):
            val_bn = None

        out.append({"month": period_s[:6], "label": label,
                    "value_bn": val_bn, "category": hs, "_raw": r})

    out.sort(key=lambda x: x.get("month", ""), reverse=True)
    return [r for r in out if r.get("month")][:12]


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

_TH_BASE = (
    "padding:7px 10px;text-align:left;font-size:12px;font-weight:600;"
    "border-bottom:2px solid #ddd"
)
_TD = "padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top"


def _data_table_html(rows: list[dict] | None, accent: str, source_label: str) -> str:
    """Render official monthly export data as a metrics table, or a compact offline note."""
    if not rows:
        return (
            f'<p style="font-size:12px;color:#999;font-style:italic;margin:0 0 14px">'
            f'Official figures unavailable — source: '
            f'<a href="#" style="color:#1155cc">{source_label}</a></p>'
        )

    th = f"padding:6px 10px;font-size:11px;font-weight:600;background:{accent}15;text-align:left;border-bottom:1px solid {accent}40"
    td_val = f"padding:6px 10px;font-size:12px;border-bottom:1px solid #f0f0f0;font-weight:600;color:#1a1a1a"
    td_sub = f"padding:6px 10px;font-size:12px;border-bottom:1px solid #f0f0f0;color:#555"

    header = (
        f"<tr>"
        f"<th style='{th}'>Month</th>"
        f"<th style='{th}'>Export (USD)</th>"
        f"<th style='{th}'>Item / Notes</th>"
        f"</tr>"
    )
    body_rows = []
    for r in rows[:6]:
        val = f"${r['value_bn']:.1f}B" if r.get("value_bn") is not None else "—"
        note = xml_escape(str(r.get("item") or r.get("category") or ""))[:50]
        body_rows.append(
            f"<tr>"
            f"<td style='{td_sub}'>{r['label']}</td>"
            f"<td style='{td_val}'>{val}</td>"
            f"<td style='{td_sub}'>{note}</td>"
            f"</tr>"
        )

    return (
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;'
        f'margin-bottom:16px;border:1px solid {accent}30;border-radius:4px">'
        f"<thead>{header}</thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        f'</table>'
    )


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


def build_html(news: dict, korea_data: list | None, taiwan_data: list | None) -> str:
    today    = datetime.now().strftime("%A, %d %B %Y")
    gen_ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total    = sum(len(v) for v in news.values())

    korea_articles  = news.get("korea", []) + news.get("both", [])
    taiwan_articles = news.get("taiwan", []) + news.get("both", [])

    _sk = lambda a: _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc)
    korea_articles.sort(key=_sk, reverse=True)
    taiwan_articles.sort(key=_sk, reverse=True)

    th_navy = f"{_TH_BASE};background:#eef2f8"
    th_red  = f"{_TH_BASE};background:#fdf0f0"

    korea_data_html  = _data_table_html(korea_data,  "#1a3a5c", "KOSIS / Korea Customs Service")
    taiwan_data_html = _data_table_html(taiwan_data, "#8b1a1a", "Taiwan MOF / data.gov.tw")

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
      {today} &#183; Korea &amp; Taiwan &#183; {total} headlines compiled
    </p>
  </div>

  <!-- Korea section -->
  <div style="background:white;padding:22px 24px;border:1px solid #dce3ec;border-top:none">
    <h2 style="margin:0 0 5px;font-size:16px;color:#1a3a5c">
      &#127472;&#127479; Korea Semiconductor Exports
    </h2>
    <p style="margin:0 0 14px;font-size:12px;color:#666;line-height:1.6">
      ~80-85% of Korea's semiconductor exports are memory (DRAM + NAND).
      Samsung &amp; SK Hynix are the two largest memory producers on Earth.
      Monthly MOTIE data leads the global memory cycle by 2-4 weeks.
    </p>

    {korea_data_html}

    <h3 style="font-size:12px;color:#555;margin:0 0 6px;
               text-transform:uppercase;letter-spacing:.6px">This week's coverage</h3>
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
      TSMC captures ~90% of advanced-node foundry revenue globally.
      Taiwan's monthly MOF export data tracks logic/AI chip demand &#8212;
      a strong complement to Korea's memory cycle signal.
    </p>

    {taiwan_data_html}

    <h3 style="font-size:12px;color:#555;margin:0 0 6px;
               text-transform:uppercase;letter-spacing:.6px">This week's coverage</h3>
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
    Generated {gen_ts} &#183; Weekly Semiconductor Export Digest &#183; github.com/yelmosharaf/FYP
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

    print("[2/3] Fetching official export data ...")
    korea_data  = fetch_korea_data()
    taiwan_data = fetch_taiwan_data()
    print(f"  Korea (KOSIS):  {'loaded — ' + str(len(korea_data)) + ' records' if korea_data else 'unavailable (add KOSIS_API_KEY secret for live figures)'}")
    print(f"  Taiwan (MOF):   {'loaded — ' + str(len(taiwan_data)) + ' records' if taiwan_data else 'unavailable'}\n")

    print("[3/3] Sending email ...")
    html = build_html(news, korea_data, taiwan_data)
    send_email(html, total)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
