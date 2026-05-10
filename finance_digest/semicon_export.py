#!/usr/bin/env python3
"""
Weekly Korea & Taiwan Semiconductor Export Digest
Scrapes news articles and optional official APIs for monthly export figures,
then emails an HTML summary with a 3-month bar chart.

Run manually:    python semicon_export.py
GitHub Actions:  weekly-semicon-export.yml  (every Monday 07:00 UTC)

Optional GitHub secrets:
  KOSIS_API_KEY  — free key from kosis.kr/openapi for official Korea figures
"""

import email.utils
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RECIPIENT_EMAIL    = os.getenv("RECIPIENT_EMAIL", "elmusharf@gmail.com")
RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")
KOSIS_API_KEY      = os.getenv("KOSIS_API_KEY", "")
SENDER_FROM        = "Finance Digest <onboarding@resend.dev>"
NEWS_LOOKBACK_DAYS = 7
MAX_ARTICLES_PER_FEED = 8
DATA_FILE = Path(__file__).parent / "data" / "semicon_history.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# RSS feed list
# ---------------------------------------------------------------------------

_GN = "https://news.google.com/rss/search?hl=en&gl=US&ceid=US:en&q="

FEEDS = [
    # Google News search feeds — reliable from GitHub Actions, aggregate many sources
    {"source": "GNews: Korea chip exports",
     "url": _GN + "Korea+semiconductor+chip+exports"},
    {"source": "GNews: Taiwan chip exports",
     "url": _GN + "Taiwan+semiconductor+chip+exports"},
    {"source": "GNews: Samsung",
     "url": _GN + "Samsung+semiconductor+earnings+exports"},
    {"source": "GNews: SK Hynix",
     "url": _GN + "SK+Hynix+memory+chip"},
    {"source": "GNews: TSMC",
     "url": _GN + "TSMC+revenue+exports"},
    {"source": "GNews: Korea trade data",
     "url": _GN + "Korea+exports+trade+MOTIE+monthly"},
    {"source": "GNews: Taiwan trade data",
     "url": _GN + "Taiwan+exports+trade+ministry+monthly"},
    # Direct publication feeds (work from most server environments)
    {"source": "Korea Herald",
     "url": "http://www.koreaherald.com/rss/020000000000.xml"},
    {"source": "Korea JoongAng Daily",
     "url": "https://koreajoongangdaily.joins.com/rss/feed.xml"},
    {"source": "Yonhap News",
     "url": "https://en.yna.co.kr/RSS/economy.xml"},
    {"source": "Focus Taiwan Business",
     "url": "https://focustaiwan.tw/rss/business"},
    {"source": "Taipei Times",
     "url": "https://www.taipeitimes.com/xml/rss.xml"},
    {"source": "The Korea Times Economy",
     "url": "https://www.koreatimes.co.kr/www2/common/rss.php?cat=business"},
    {"source": "EE Times",
     "url": "https://www.eetimes.com/rss/"},
    {"source": "Nikkei Asia",
     "url": "https://asia.nikkei.com/rss/feed/nar"},
]

# ---------------------------------------------------------------------------
# Keyword classifiers
# ---------------------------------------------------------------------------

_KOREA_COMPANIES  = {"samsung", "sk hynix", "hynix", "sk telecom"}
_TAIWAN_COMPANIES = {"tsmc", "mediatek", "umc", "ase group", "taiwan semiconductor"}
_KOREA_GEO  = {"korea", "korean", "motie", "kita", "kotra"}
_TAIWAN_GEO = {"taiwan", "taiwanese"}
_SEMICON_KW = {
    "semiconductor", "chip", "chips", "memory", "dram", "nand", "hbm",
    "wafer", "integrated circuit", "export", "shipment",
    "foundry", "fab", "ai chip", "logic chip", "packaging",
    "earnings", "revenue", "production", "output", "capacity",
}


def _classify(title: str) -> str:
    t = title.lower()
    korea_co  = any(kw in t for kw in _KOREA_COMPANIES)
    taiwan_co = any(kw in t for kw in _TAIWAN_COMPANIES)
    has_semicon = any(kw in t for kw in _SEMICON_KW)
    korea_geo   = any(kw in t for kw in _KOREA_GEO)
    taiwan_geo  = any(kw in t for kw in _TAIWAN_GEO)
    korea  = korea_co  or (has_semicon and korea_geo)
    taiwan = taiwan_co or (has_semicon and taiwan_geo)
    if not (korea or taiwan):
        return ""
    if korea and taiwan:
        return "both"
    return "korea" if korea else "taiwan"


# ---------------------------------------------------------------------------
# Persistent history
# ---------------------------------------------------------------------------

def load_history() -> dict:
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"korea": [], "taiwan": [], "last_updated": None}


def save_history(history: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(history, f, indent=2)


def merge_records(existing: list, new_records: list) -> tuple[list, bool]:
    """Merge new_records into existing list. Returns (merged_list, changed_flag)."""
    known = {r["month"] for r in existing}
    changed = False
    for r in new_records:
        if r.get("month") and r["month"] not in known:
            existing.append(r)
            known.add(r["month"])
            changed = True
    existing.sort(key=lambda x: x.get("month", ""), reverse=True)
    return existing[:24], changed


def _compute_mom(records: list[dict]) -> list[dict]:
    """Add mom_pct to records that have a value_bn and a consecutive previous month."""
    out = [dict(r) for r in records]
    out.sort(key=lambda x: x.get("month", ""), reverse=True)
    for i, r in enumerate(out):
        if r.get("mom_pct") is not None or r.get("value_bn") is None:
            continue
        if i + 1 < len(out) and out[i + 1].get("value_bn") is not None:
            prev = out[i + 1]["value_bn"]
            curr = r["value_bn"]
            if prev > 0:
                out[i]["mom_pct"] = round((curr - prev) / prev * 100, 1)
    return out


# ---------------------------------------------------------------------------
# Web scraping helpers
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
    "nov": "11", "dec": "12",
}

# Sources we can actually scrape (no paywall / JS-only rendering)
_OPEN_SOURCES = {
    "Korea Herald", "Korea JoongAng Daily", "Yonhap News",
    "Focus Taiwan Business", "Taipei Times", "The Korea Times Economy",
    "EE Times", "Nikkei Asia",
}

# Quarter → last month of that quarter (YYYYMM suffix)
_QUARTER_MONTH = {"q1": "03", "q2": "06", "q3": "09", "q4": "12",
                  "first quarter": "03", "second quarter": "06",
                  "third quarter": "09", "fourth quarter": "12"}


def _fetch_page_text(url: str, timeout: int = 15) -> str:
    """Fetch a web page and return stripped plain text (max 60k chars)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&#?\w+;", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text[:60_000]
    except Exception as exc:
        print(f"    [skip] {url[:70]}: {exc}")
        return ""


def _parse_month_from_text(text: str) -> str | None:
    """
    Return the most plausible data-month ('YYYYMM') from text.
    Uses a scoring system so quarter labels and "in Month" beat bare words
    and datelines like "Seoul, May 6 --".
    """
    now = datetime.now()
    year_now = now.year
    today_str = now.strftime("%Y%m")
    cutoff    = (now + timedelta(days=62)).strftime("%Y%m")

    hits: list[tuple[int, str]] = []  # (score, YYYYMM)

    def _add(score: int, yr: int, m_num: str) -> None:
        if 2020 <= yr <= year_now + 1:
            key = f"{yr}{m_num}"
            if key <= cutoff:
                hits.append((score, key))

    # Score 10 — quarter labels (most reliable data-period signal)
    for q_name, q_month in _QUARTER_MONTH.items():
        for m in re.finditer(
            rf"\b{re.escape(q_name)}\b[\s,of]*(\d{{4}})?", text, re.I
        ):
            yr = int(m.group(1)) if m.group(1) else year_now
            _add(10, yr, q_month)

    for m_name, m_num in _MONTH_MAP.items():
        # Score 8 — "April 2026", "in April 2026"
        for m in re.finditer(rf"\b{m_name}\b[\s,]*(\d{{4}})\b", text, re.I):
            _add(8, int(m.group(1)), m_num)

        # Score 6 — "in April", "April exports/shipments/data/figures"
        pat6 = (
            rf"(?:in|during|for)\s+{m_name}\b"
            rf"|{m_name}\s+(?:export|shipment|data|figure|trade)"
        )
        for m in re.finditer(pat6, text, re.I):
            key = f"{year_now}{m_num}"
            if key > today_str:
                key = f"{year_now - 1}{m_num}"
            hits.append((6, key))

        # Score 2 — bare month name, but NOT "may" (ambiguous verb) and NOT a
        # dateline ("May 6", "April 3")
        if m_name != "may":
            for m in re.finditer(
                rf"\b{m_name}\b(?!\s*\d{{1,2}}(?:\s|,|$))", text, re.I
            ):
                key = f"{year_now}{m_num}"
                if key > today_str:
                    key = f"{year_now - 1}{m_num}"
                hits.append((2, key))

    if not hits:
        return None
    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return hits[0][1]


def _parse_export_value(text: str) -> float | None:
    """Extract a USD export value in billions from text."""
    patterns = [
        r"\$\s*([\d,]+\.?\d*)\s*(?:billion|bn)\b",
        r"USD\s*([\d,]+\.?\d*)\s*(?:billion|bn)\b",
        r"([\d,]+\.?\d*)\s*(?:billion|bn)\s*(?:USD|dollars?|US dollars?)",
        r"([\d,]+\.?\d*)\s*billion\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                if 0.1 <= v <= 500:  # sanity: between 100M and 500B
                    return v
            except ValueError:
                continue

    m = re.search(r"(?:\$|USD\s*)([\d,]+\.?\d*)\s*(?:million|mn)\b", text, re.I)
    if m:
        try:
            v = float(m.group(1).replace(",", "")) / 1000
            if 0.1 <= v <= 500:
                return round(v, 2)
        except ValueError:
            pass
    return None


def _parse_yoy(text: str) -> float | None:
    """Extract the most prominent YoY % change from text."""
    up_words   = r"(?:up|rose|surged|jumped|gained|increased|grew|expanded|climbed)"
    down_words = r"(?:down|fell|dropped|declined|decreased|slipped|contracted|tumbled)"
    pct        = r"(\d+\.?\d*)\s*(?:%|percent|pct|pp)"

    m = re.search(rf"\b{up_words}\s+{pct}", text, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    m = re.search(rf"\b{down_words}\s+{pct}", text, re.I)
    if m:
        try:
            return -float(m.group(1))
        except ValueError:
            pass

    m = re.search(
        rf"{pct}\s+(?:year.on.year|yoy|y/y|annually).*?(?:increase|growth|rise|gain|jump)",
        text, re.I,
    )
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass

    m = re.search(
        rf"{pct}\s+(?:year.on.year|yoy|y/y|annually).*?(?:decline|fall|drop|decrease|slip)",
        text, re.I,
    )
    if m:
        try:
            return -float(m.group(1))
        except ValueError:
            pass

    return None


def _extract_records_from_text(text: str, country: str) -> list[dict]:
    """
    Parse article plain-text for monthly semiconductor export figures.
    Returns a list of {month, label, value_bn, yoy_pct, mom_pct, source}.
    """
    country_kw = {
        "korea":  ["korea", "korean", "samsung", "hynix", "motie"],
        "taiwan": ["taiwan", "taiwanese", "tsmc", "ministry of finance"],
    }[country]
    export_kw = ["export", "shipment", "trade", "outbound"]

    tl = text.lower()
    if not any(k in tl for k in country_kw):
        return []
    if not any(k in tl for k in export_kw):
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    results: list[dict] = []
    seen: set[str] = set()

    for i, sent in enumerate(sentences):
        if not any(k in sent.lower() for k in export_kw):
            continue
        ctx_start = max(0, i - 2)
        ctx_end   = min(len(sentences), i + 3)
        ctx = " ".join(sentences[ctx_start:ctx_end])

        val = _parse_export_value(ctx)
        yoy = _parse_yoy(ctx)
        mon = _parse_month_from_text(ctx)

        if (val is not None or yoy is not None) and mon and mon not in seen:
            seen.add(mon)
            try:
                label = datetime.strptime(mon, "%Y%m").strftime("%b %Y")
            except ValueError:
                label = mon
            results.append({
                "month":    mon,
                "label":    label,
                "value_bn": val,
                "yoy_pct":  yoy,
                "mom_pct":  None,
                "source":   "web",
            })

    return results


def _scrape_articles_for_data(articles: list[dict], country: str) -> list[dict]:
    """
    Fetch full-text of recent open-access articles and extract export figures.
    Prefers known-open sources; falls back to all articles if none available.
    """
    results: list[dict] = []
    seen_months: set[str] = set()

    # Prefer open-access sources (no paywall); fall back to everything else
    open_arts = [a for a in articles if a.get("source") in _OPEN_SOURCES and a.get("link")]
    candidates = open_arts if open_arts else [a for a in articles if a.get("link")]

    for art in candidates[:5]:
        url = art["link"]
        print(f"    Scraping: {url[:70]}")
        text = _fetch_page_text(url)
        if not text:
            continue

        records = _extract_records_from_text(text, country)
        for r in records:
            if r["month"] not in seen_months:
                seen_months.add(r["month"])
                results.append(r)
                v_str = f"${r['value_bn']:.1f}B" if r["value_bn"] is not None else "n/a"
                y_str = (
                    f"{r['yoy_pct']:+.1f}% YoY" if r["yoy_pct"] is not None else ""
                )
                print(f"      -> {r['label']} {v_str} {y_str}")

    return results


# ---------------------------------------------------------------------------
# RSS helpers
# ---------------------------------------------------------------------------

def _text(el: ET.Element, *tags: str) -> str:
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
    return dt.strftime("%d %b %H:%M") if dt else (raw[:10] if raw else "-")


def _parse_feed(root: ET.Element) -> list[dict]:
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
    Scan all RSS feeds; return articles from the last NEWS_LOOKBACK_DAYS days,
    bucketed as {"korea": [...], "taiwan": [...], "both": [...]}.
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

    _sk = lambda a: (
        _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc)
    )
    for cat in buckets:
        buckets[cat].sort(key=_sk, reverse=True)

    return buckets


# ---------------------------------------------------------------------------
# Korea official data — KOSIS Open API (optional)
# ---------------------------------------------------------------------------

def fetch_korea_official() -> list[dict]:
    if not KOSIS_API_KEY:
        return []
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
            params=params, headers=HEADERS, timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
        if isinstance(raw, dict) and raw.get("err"):
            print(f"  [WARN] KOSIS: {raw}")
            return []
        if not isinstance(raw, list):
            return []
        out = []
        for r in raw:
            period = r.get("PRD_DE", "")
            value  = r.get("DT", "").replace(",", "").strip()
            unit   = r.get("UNIT_NM", "")
            if not period or not value:
                continue
            try:
                val_f = float(value)
            except ValueError:
                continue
            val_bn = val_f / 1000 if "애만" in unit or "million" in unit.lower() else val_f
            try:
                label = datetime.strptime(period, "%Y%m").strftime("%b %Y")
            except ValueError:
                label = period
            out.append({
                "month":    period,
                "label":    label,
                "value_bn": round(val_bn, 2),
                "yoy_pct":  None,
                "mom_pct":  None,
                "source":   "kosis",
            })
        out.sort(key=lambda x: x["month"], reverse=True)
        return out[:12]
    except Exception as exc:
        print(f"  [WARN] KOSIS: {exc}")
        return []


# ---------------------------------------------------------------------------
# Taiwan official data — data.gov.tw (no key)
# ---------------------------------------------------------------------------

def fetch_taiwan_official() -> list[dict]:
    endpoints = [
        "https://data.gov.tw/api/v2/rest/datastore/301000000A-000154-002",
        "https://data.gov.tw/api/v2/rest/datastore/301000000A-000154-001",
        "https://data.gov.tw/api/v2/rest/datastore/6484",
    ]
    for url in endpoints:
        try:
            resp = requests.get(
                url, params={"format": "json", "limit": 100},
                headers=HEADERS, timeout=15,
            )
            resp.raise_for_status()
            body = resp.json()
            records = (body.get("result") or {}).get("records") or []
            if not records:
                continue
            out = _parse_taiwan_records(records)
            if out:
                return out
        except Exception as exc:
            print(f"  [WARN] Taiwan {url}: {exc}")
    return []


def _parse_taiwan_records(records: list) -> list[dict]:
    out = []
    for r in records:
        hs = str(
            r.get("HS", "") or r.get("hs_code", "") or r.get("商品", "") or ""
        )
        if hs and not any(c in hs for c in ("8541", "8542", "85")):
            continue
        period_raw = (
            r.get("年月") or r.get("period") or r.get("date")
            or r.get("Month") or r.get("yearmonth") or ""
        )
        value_raw = (
            r.get("出口値") or r.get("export_value") or r.get("Export")
            or r.get("value") or r.get("Value") or ""
        )
        if not period_raw or not value_raw:
            continue
        period_s = str(period_raw).replace("/", "").replace("-", "").strip()
        if len(period_s) == 5 and period_s.isdigit():
            roc_year  = int(period_s[:3])
            month_num = int(period_s[3:])
            period_s  = f"{roc_year + 1911}{month_num:02d}"
        try:
            label = datetime.strptime(period_s[:6], "%Y%m").strftime("%b %Y")
        except ValueError:
            continue
        try:
            val = float(str(value_raw).replace(",", "").strip())
            val_bn = round(val / 30_000, 2) if val > 10_000 else round(val / 1000, 2)
        except (ValueError, TypeError):
            continue
        out.append({
            "month":    period_s[:6],
            "label":    label,
            "value_bn": val_bn,
            "yoy_pct":  None,
            "mom_pct":  None,
            "source":   "gov.tw",
        })
    out.sort(key=lambda x: x.get("month", ""), reverse=True)
    return [r for r in out if r.get("month")][:12]


# ---------------------------------------------------------------------------
# Email HTML builder
# ---------------------------------------------------------------------------

_TH_BASE = (
    "padding:7px 10px;text-align:left;font-size:12px;font-weight:600;"
    "border-bottom:2px solid #ddd"
)
_TD = "padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top"


def _bar_chart_html(records: list[dict], accent: str, bar_color: str) -> str:
    """
    Render a 3-month CSS bar chart (email-safe, no JS).
    Oldest month is left, newest is right.
    """
    if not records:
        return (
            '<p style="font-size:12px;color:#999;font-style:italic;margin:4px 0 16px">'
            "Figures pending - will populate once monthly export data is scraped.</p>"
        )

    chart_data = records[:3][::-1]  # take 3 newest, reverse to oldest-left

    vals = [r.get("value_bn") for r in chart_data if r.get("value_bn") is not None]
    max_val = max(vals, default=1) or 1
    BAR_H = 72

    cols = []
    for r in chart_data:
        v   = r.get("value_bn")
        yoy = r.get("yoy_pct")
        mom = r.get("mom_pct")
        bar_h = round((v / max_val) * BAR_H) if v else 6
        val_str = f"${v:.1f}B" if v is not None else "n/a"

        yoy_html = ""
        if yoy is not None:
            color = "#16a34a" if yoy >= 0 else "#dc2626"
            sign  = "+" if yoy > 0 else ""
            yoy_html = (
                f'<span style="color:{color};display:block">'
                f"{sign}{yoy:.1f}% YoY</span>"
            )
        mom_html = ""
        if mom is not None:
            color = "#16a34a" if mom >= 0 else "#dc2626"
            sign  = "+" if mom > 0 else ""
            mom_html = (
                f'<span style="color:{color};display:block">'
                f"{sign}{mom:.1f}% MoM</span>"
            )

        cols.append(
            f'<td style="width:33%;text-align:center;padding:0 8px;vertical-align:bottom">'
            f'<div style="font-size:10px;color:#444;margin-bottom:4px;line-height:1.4">'
            f"<strong>{val_str}</strong><br>{yoy_html}{mom_html}"
            f"</div>"
            f'<div style="background:{bar_color};height:{bar_h}px;'
            f'border-radius:3px 3px 0 0;margin:0 auto;width:44px"></div>'
            f'<div style="font-size:11px;font-weight:600;color:#333;margin-top:4px">'
            f"{r['label']}"
            f"</div>"
            f"</td>"
        )

    return (
        f'<table style="width:100%;border-collapse:collapse;margin-bottom:16px">'
        f'<tr style="vertical-align:bottom">{""  .join(cols)}</tr>'
        f'<tr><td colspan="3" style="border-top:2px solid {accent};padding-top:0"></td></tr>'
        f"</table>"
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


def build_html(
    news: dict,
    korea_records: list[dict],
    taiwan_records: list[dict],
) -> str:
    today    = datetime.now().strftime("%A, %d %B %Y")
    gen_ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total    = sum(len(v) for v in news.values())

    korea_articles  = sorted(
        news.get("korea", []) + news.get("both", []),
        key=lambda a: _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    taiwan_articles = sorted(
        news.get("taiwan", []) + news.get("both", []),
        key=lambda a: _parse_dt(a["published"]) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    th_navy = f"{_TH_BASE};background:#eef2f8"
    th_red  = f"{_TH_BASE};background:#fdf0f0"

    k_rec = _compute_mom(korea_records)
    t_rec = _compute_mom(taiwan_records)

    k_chart = _bar_chart_html(k_rec, "#1a3a5c", "#2563eb")
    t_chart = _bar_chart_html(t_rec, "#8b1a1a", "#dc2626")

    k_note = f"Latest: {korea_records[0]['label']}" if korea_records else "No figures yet"
    t_note = f"Latest: {taiwan_records[0]['label']}" if taiwan_records else "No figures yet"

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
      {today} &#183; Korea &amp; Taiwan &#183; {total} headlines this week
    </p>
  </div>

  <!-- Korea section -->
  <div style="background:white;padding:22px 24px;border:1px solid #dce3ec;border-top:none">
    <h2 style="margin:0 0 4px;font-size:16px;color:#1a3a5c">
      &#127472;&#127479; Korea Semiconductor Exports
    </h2>
    <p style="margin:0 0 14px;font-size:12px;color:#888">{k_note} &#183; 3-month trend</p>

    {k_chart}

    <h3 style="font-size:12px;color:#555;margin:0 0 6px;
               text-transform:uppercase;letter-spacing:.6px">This week's headlines</h3>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr>
        <th style="{th_navy};width:80px">Date</th>
        <th style="{th_navy};width:130px">Source</th>
        <th style="{th_navy}">Headline</th>
      </tr></thead>
      <tbody>{_article_rows(korea_articles)}</tbody>
    </table>
  </div>

  <div style="height:8px;background:#f0f4f8"></div>

  <!-- Taiwan section -->
  <div style="background:white;padding:22px 24px;border:1px solid #dce3ec">
    <h2 style="margin:0 0 4px;font-size:16px;color:#8b1a1a">
      &#127481;&#127484; Taiwan Semiconductor Exports
    </h2>
    <p style="margin:0 0 14px;font-size:12px;color:#888">{t_note} &#183; 3-month trend</p>

    {t_chart}

    <h3 style="font-size:12px;color:#555;margin:0 0 6px;
               text-transform:uppercase;letter-spacing:.6px">This week's headlines</h3>
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
        raise ValueError("RESEND_API_KEY is not set. Get a free key at https://resend.com")

    today   = datetime.now().strftime("%d %b %Y")
    subject = f"Semiconductor Export Digest - {today}"

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
                f"Semiconductor Export Digest - {today}\n\n"
                f"Korea & Taiwan semiconductor export summary.\n"
                f"{article_count} headlines compiled this week.\n\n"
                f"- Finance Digest Bot"
            ),
        },
        timeout=15,
    )

    if resp.status_code in (200, 201):
        print(f"  Sent to {RECIPIENT_EMAIL}")
    else:
        raise RuntimeError(f"Resend API error {resp.status_code}: {resp.text}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{'='*60}")
    print(f"  Weekly Semiconductor Export Digest")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    history = load_history()
    print(
        f"[history] Korea: {len(history['korea'])} months  "
        f"Taiwan: {len(history['taiwan'])} months\n"
    )

    print("[1/4] Fetching semiconductor headlines from RSS feeds ...")
    news  = fetch_news()
    total = sum(len(v) for v in news.values())
    print(
        f"\n  Korea: {len(news['korea'])}"
        f"  |  Taiwan: {len(news['taiwan'])}"
        f"  |  Both: {len(news['both'])}"
        f"  |  Total: {total}\n"
    )

    print("[2/4] Trying official data APIs ...")
    fresh_korea  = fetch_korea_official()
    fresh_taiwan = fetch_taiwan_official()
    print(f"  KOSIS (Korea):     {len(fresh_korea)} records")
    print(f"  data.gov.tw (TW):  {len(fresh_taiwan)} records\n")

    print("[3/4] Scraping export figures from news articles ...")
    all_korea_articles  = news.get("korea", []) + news.get("both", [])
    all_taiwan_articles = news.get("taiwan", []) + news.get("both", [])
    scraped_korea  = _scrape_articles_for_data(all_korea_articles,  "korea")
    scraped_taiwan = _scrape_articles_for_data(all_taiwan_articles, "taiwan")
    print(f"  Scraped Korea:   {len(scraped_korea)} new records")
    print(f"  Scraped Taiwan:  {len(scraped_taiwan)} new records\n")

    all_korea_fresh  = fresh_korea  + scraped_korea
    all_taiwan_fresh = fresh_taiwan + scraped_taiwan

    history["korea"],  k_changed = merge_records(history["korea"],  all_korea_fresh)
    history["taiwan"], t_changed = merge_records(history["taiwan"], all_taiwan_fresh)

    if k_changed or t_changed:
        history["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_history(history)
        print("  History updated and saved.\n")
    else:
        print("  No new export figures - history unchanged.\n")

    print("[4/4] Building and sending digest email ...")
    html = build_html(news, history["korea"], history["taiwan"])
    send_email(html, total)

    print("\nDone.\n")


if __name__ == "__main__":
    main()
