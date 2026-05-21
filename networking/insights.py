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

Funds that matter in this universe: Ares, Apollo, Oaktree, Carlyle, KKR Credit, Blackstone Credit,
Cerberus, Elliott, Anchorage, Sculptor, Davidson Kempner, Marathon, Attestor, Aurelius,
GoldenTree, HPS, Intermediate Capital, Permira Credit, BC Partners Credit, Tikehau, Alcentra,
Barings, M&G, Napier Park, Chenavari, CVC Credit, Hayfin, Park Square, Octagon, Benefit Street.

When giving talking points, make them specific and timely — reference current themes:
rising default cycles, LBO overhang, stressed European credits, liability management exercises,
distressed-for-control plays, secondary CLO market, direct lending competition, etc.

Return ONLY valid JSON. No markdown fences."""

USER_TEMPLATE = """
Today: {today}
Banker profile: Restructuring & Leveraged Credit, London

NETWORK SNAPSHOT
Total contacts: {total_contacts}
Never met: {never_met_count}
Overdue relationships: {overdue_count}
Active (met in 30d): {active_count}

FUNDS COVERED
{funds_block}

RECENT MEETINGS (last 30 days)
{meetings_block}

OVERDUE PRIORITY CONTACTS
{overdue_block}

CONTACT BACKGROUNDS (sample)
{backgrounds_block}

Produce a JSON object with exactly these keys:
{{
  "network_score": <integer 0-100>,
  "score_rationale": "<one sentence>",
  "executive_summary": "<3-4 sentences of sharp narrative — what does this network look like, what are the gaps, what is the opportunity>",
  "top_actions": [
    {{
      "contact": "<name>",
      "fund": "<fund>",
      "urgency": "<High|Medium>",
      "reason": "<why now — be specific>",
      "talking_point": "<one sharp, specific conversation opener relevant to distressed/credit markets>"
    }}
  ],
  "strategic_insights": [
    "<insight 1 — specific observation about network health or gaps>",
    "<insight 2>",
    "<insight 3>"
  ],
  "coverage_gaps": [
    "<fund or fund type you should target and why>"
  ],
  "market_themes": [
    "<current theme 1 relevant to distressed/HY/credit that is good for networking conversations>",
    "<current theme 2>",
    "<current theme 3>"
  ],
  "relationship_of_the_week": {{
    "contact": "<name>",
    "fund": "<fund>",
    "rationale": "<why this person is most worth investing in this week>"
  }}
}}

top_actions: include up to 5 entries, prioritised by urgency and market relevance.
coverage_gaps: up to 4 entries.
"""


def _s(val) -> str:
    """Coerce any gspread value (including float NaN) to a clean string."""
    return str(val or "").strip()


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
    lines = []
    for f in funds:
        lines.append(
            f"  {_s(f.get('fund',{}).get('Fund Name'))} — "
            f"{len(f.get('contacts',[]))} contacts — "
            f"last touch: {f.get('last_touch_days','never')}d ago"
        )
    return "\n".join(lines) or "  (none)"


def _fmt_backgrounds(contacts: list[dict]) -> str:
    lines = []
    for c in contacts[:20]:
        bg = _s(c.get("Background"))
        if bg:
            lines.append(f"  {_s(c.get('Name'))} ({_s(c.get('Fund'))}): {bg[:150]}")
    return "\n".join(lines) or "  (none)"


def generate_insights(context: dict) -> dict:
    contacts   = context["never_met"] + context["overdue"] + context["on_track"]
    overdue    = context["overdue"]
    meetings   = context["recent_meetings"]
    fund_rows  = context["fund_rows"]

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
        funds_block=_fmt_funds(fund_rows),
        meetings_block=_fmt_meetings(meetings),
        overdue_block=_fmt_overdue(overdue),
        backgrounds_block=_fmt_backgrounds(contacts),
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)
