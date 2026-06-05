"""
Network intelligence: uses Claude to generate bespoke analysis for a
restructuring banker covering London distressed / HY / opportunistic credit.
"""

import json
import os
import re
from datetime import date

import anthropic


SYSTEM_PROMPT = """You are a senior relationship strategist embedded with a restructuring and leveraged credit banker in London.

Your job: produce sharp, actionable network intelligence — not generic advice.
You know the market: distressed debt, high yield bonds, leveraged loans, CLOs, special situations,
opportunistic credit, direct lending, restructuring advisory, liability management.

CRITICAL RULE: Every entry in top_actions and relationship_of_the_week MUST reference a REAL PERSON
from the CONTACTS AT KEY FUNDS list provided. Use their exact name and fund. Never invent names.
If a contact has no Background, infer from their Role what they likely focus on.

When giving talking points, make them specific and timely — reference current themes:
rising default cycles, LBO overhang, stressed European credits, liability management exercises,
distressed-for-control plays, secondary CLO market, direct lending competition, etc.

Return ONLY valid JSON. No markdown fences."""

TARGET_FUNDS = {
    "ares", "apollo", "oaktree", "carlyle", "kkr", "blackstone", "cerberus",
    "elliott", "anchorage", "sculptor", "davidson kempner", "marathon", "attestor",
    "aurelius", "goldentree", "hps", "intermediate capital", "icg", "permira",
    "bc partners", "tikehau", "alcentra", "barings", "m&g", "napier park",
    "chenavari", "cvc credit", "cvc", "hayfin", "park square", "octagon",
    "benefit street", "bsp", "golub", "blue owl", "owl rock", "sixth street",
    "bain capital credit", "pimco", "varde", "canyon", "king street",
    "silver point", "gso", "brigade", "whitebox", "post advisory",
    "restructuring", "distressed", "credit", "leveraged", "high yield",
    "direct lending", "special situations", "private credit",
}

THEME_MAP = [
    ("Deep Distress / Special Sits", [
        "elliott", "cerberus", "anchorage", "aurelius", "marathon", "attestor",
        "davidson kempner", "sculptor", "king street", "silver point", "whitebox",
        "varde", "canyon", "brigade", "post advisory", "cyrus",
    ]),
    ("High Yield / Leveraged Credit", [
        "oaktree", "goldentree", "barings", "m&g", "alcentra", "bluebay",
        "apollo", "carlyle", "man glenwood", "man group", "pimco",
    ]),
    ("Direct Lending / Private Credit", [
        "ares", "hps", "intermediate capital", "icg", "hayfin", "park square",
        "benefit street", "blue owl", "owl rock", "golub", "sixth street",
        "permira", "bc partners", "tikehau", "bain capital credit",
    ]),
    ("CLOs / Structured Credit", [
        "octagon", "napier park", "chenavari", "cvc credit", "nuveen", "pgim",
        "blackstone credit",
    ]),
    ("Multi-Strategy / Opportunistic", [
        "kkr", "blackstone", "bain capital", "apollo global",
    ]),
]

LONDON_KEYWORDS = [
    "london", "uk", "united kingdom", "england", "city of london",
    "canary wharf", "mayfair", "belgravia",
]

LONDON_FUNDS = {
    "ares", "apollo", "oaktree", "carlyle", "kkr", "blackstone", "cerberus",
    "elliott", "davidson kempner", "attestor", "aurelius", "goldentree", "hps",
    "intermediate capital", "icg", "permira", "bc partners", "tikehau", "alcentra",
    "barings", "m&g", "napier park", "chenavari", "cvc credit", "hayfin",
    "park square", "benefit street", "bluebay", "man glenwood", "man group",
    "distressed", "credit", "restructuring",
}

MID_LEVEL_KEYWORDS = [
    "vice president", "vp ", " vp", "director", "principal", "managing director",
    "md ", " md", "portfolio manager", "investment manager", "credit manager",
    "associate director", "senior associate", "senior analyst", "associate partner",
    "partner", "head of", "senior vice president", "svp",
]

JUNIOR_KEYWORDS = ["analyst", "intern", "graduate", "junior", "trainee", "assistant"]

USER_TEMPLATE = """
Today: {today}
Banker profile: Restructuring & Leveraged Credit, London

NETWORK SNAPSHOT
Total contacts: {total_contacts}
Never met: {never_met_count}
Overdue relationships: {overdue_count}
Active (met in 30d): {active_count}

CONTACTS AT KEY FUNDS (use these real people for top_actions)
{key_contacts_block}

RECENT MEETINGS (last 30 days)
{meetings_block}

OVERDUE PRIORITY CONTACTS
{overdue_block}

TOP FUNDS COVERAGE
{funds_block}

Produce a JSON object with exactly these keys:
{{
  "network_score": <integer 0-100>,
  "score_rationale": "<one sentence>",
  "top_actions": [
    {{
      "contact": "<REAL person name from CONTACTS AT KEY FUNDS list above>",
      "fund": "<their fund>",
      "urgency": "<High|Medium>",
      "reason": "<ONE line about THIS PERSON specifically — their seniority, what they decide on, why they matter to you right now. Do NOT describe the fund. The banker already knows what every fund does.>",
      "talking_point": "<the exact opening line you would send them — specific, timely, no fluff>"
    }}
  ],
  "relationship_of_the_week": {{
    "contact": "<REAL person name from the list>",
    "fund": "<their fund>",
    "rationale": "<why this person is most worth investing time in this week>"
  }}
}}

top_actions: exactly 20 entries. MUST be real people from CONTACTS AT KEY FUNDS.
LONDON ONLY — skip anyone without a [London confirmed] or [London likely] tag.
Prioritise VPs, Directors, Principals, MDs, Portfolio Managers — mid-to-senior level.
Exclude analysts and interns. Each talking_point must be one punchy sentence.
"""


def _s(val) -> str:
    return str(val or "").strip()


def _seniority_score(role: str) -> int:
    r = role.lower()
    if any(kw in r for kw in JUNIOR_KEYWORDS):
        return 0
    if any(kw in r for kw in MID_LEVEL_KEYWORDS):
        return 2
    return 1


def _london_score(contact: dict) -> int:
    text = (_s(contact.get("Background")) + " " + _s(contact.get("Role")) +
            " " + _s(contact.get("Tags"))).lower()
    if any(kw in text for kw in LONDON_KEYWORDS):
        return 2
    fund = _s(contact.get("Fund")).lower()
    if any(kw in fund for kw in LONDON_FUNDS):
        return 1
    return 0


def _is_target_fund(fund_name: str) -> bool:
    fn = fund_name.lower()
    return any(kw in fn for kw in TARGET_FUNDS)


def _theme_for_fund(fund_name: str) -> str | None:
    fn = fund_name.lower()
    for theme, keywords in THEME_MAP:
        if any(kw in fn for kw in keywords):
            return theme
    return None


def group_contacts_by_theme(contacts: list[dict]) -> dict:
    buckets: dict[str, list] = {t: [] for t, _ in THEME_MAP}
    seen: set = set()
    for c in contacts:
        name = _s(c.get("Name"))
        fund = _s(c.get("Fund"))
        role = _s(c.get("Role"))
        if not name or not fund:
            continue
        if _london_score(c) < 1:
            continue
        theme = _theme_for_fund(fund)
        if theme is None:
            continue
        key = (name.lower(), fund.lower())
        if key in seen:
            continue
        seen.add(key)
        buckets[theme].append({
            "name": name,
            "fund": fund,
            "role": role,
            "background": _s(c.get("Background")),
        })
    for theme in buckets:
        buckets[theme].sort(key=lambda x: (x["fund"].lower(), x["name"].lower()))
    return {t: v for t, v in buckets.items() if v}


def _fmt_meetings(meetings: list[dict]) -> str:
    if not meetings:
        return "  (none logged)"
    lines = []
    for m in meetings[:15]:
        notes = _s(m.get("Notes"))[:120]
        lines.append(f"  {_s(m.get('Date'))}  {_s(m.get('Contact Name'))} ({_s(m.get('Fund'))})  {_s(m.get('Type'))}  {notes}")
    return "\n".join(lines)


def _fmt_overdue(contacts: list[dict]) -> str:
    if not contacts:
        return "  (none)"
    lines = []
    for c in contacts[:8]:
        lines.append(
            f"  {_s(c.get('Name'))} | {_s(c.get('Fund'))} | {_s(c.get('Role'))} | "
            f"last met {c.get('_days_since','?')}d ago | overdue {c.get('_days_overdue','?')}d"
        )
    return "\n".join(lines)


def _fmt_funds(funds: list[dict]) -> str:
    top = sorted(funds, key=lambda f: f.get("last_touch_days") or 9999)[:30]
    lines = []
    for f in top:
        lines.append(
            f"  {_s(f.get('fund',{}).get('Fund Name'))} — "
            f"{len(f.get('contacts',[]))} contacts — "
            f"last touch: {f.get('last_touch_days','never')}d ago"
        )
    return "\n".join(lines) or "  (none)"


def _fmt_key_contacts(contacts: list[dict]) -> str:
    relevant = [
        c for c in contacts
        if _is_target_fund(_s(c.get("Fund"))) and _s(c.get("Name"))
        and _london_score(c) >= 1
    ]
    relevant.sort(key=lambda c: (
        -_london_score(c),
        -_seniority_score(_s(c.get("Role"))),
        0 if c.get("_days_since") is None else 1,
        -(c.get("_days_overdue") or 0),
    ))
    lines = []
    for c in relevant[:60]:
        bg     = _s(c.get("Background"))
        role   = _s(c.get("Role"))
        since  = c.get("_days_since")
        status = "never met" if since is None else f"last met {since}d ago"
        loc    = "[London confirmed]" if _london_score(c) == 2 else "[London likely]"
        extra  = f" | {bg[:80]}" if bg else ""
        lines.append(
            f"  {_s(c.get('Name'))} | {_s(c.get('Fund'))} | {role} | {loc} | {status}{extra}"
        )
    return "\n".join(lines) or "  (no London contacts at target funds found)"


def generate_insights(context: dict) -> dict:
    contacts  = context["never_met"] + context["overdue"] + context["on_track"]
    overdue   = context["overdue"]
    meetings  = context["recent_meetings"]
    fund_rows = context["fund_rows"]

    active_count = sum(
        1 for c in contacts
        if c.get("_days_since") is not None and c["_days_since"] <= 30
    )

    prompt = USER_TEMPLATE.format(
        today=date.today().strftime("%d %B %Y"),
        total_contacts=context["total_contacts"],
        never_met_count=len(context["never_met"]),
        overdue_count=len(overdue),
        active_count=active_count,
        key_contacts_block=_fmt_key_contacts(contacts),
        funds_block=_fmt_funds(fund_rows),
        meetings_block=_fmt_meetings(meetings),
        overdue_block=_fmt_overdue(overdue),
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        intel = json.loads(raw)
    except json.JSONDecodeError:
        raw = raw.rstrip().rstrip(",")
        open_brackets = raw.count("[") - raw.count("]")
        open_braces   = raw.count("{") - raw.count("}")
        raw += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
        intel = json.loads(raw)

    intel["network_by_theme"] = group_contacts_by_theme(contacts)
    return intel
