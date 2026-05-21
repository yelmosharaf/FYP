"""
Networking Intelligence Brief — 2-page PDF focused on targets and analytics.
"""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

# ── Palette ────────────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0d1b3e")
NAVY_MID   = colors.HexColor("#1a3a6b")
GOLD       = colors.HexColor("#c9a84c")
OFF_WHITE  = colors.HexColor("#f8fafc")
LIGHT_GRAY = colors.HexColor("#e5e7eb")
GRAY       = colors.HexColor("#6b7280")
RED_BG     = colors.HexColor("#fee2e2")
RED_TC     = colors.HexColor("#b91c1c")
AMBER_BG   = colors.HexColor("#fef3c7")
AMBER_TC   = colors.HexColor("#92400e")
GREEN_BG   = colors.HexColor("#dcfce7")
GREEN_TC   = colors.HexColor("#15803d")
BLUE_BG    = colors.HexColor("#dbeafe")
BLUE_TC    = colors.HexColor("#1e40af")
PURPLE_BG  = colors.HexColor("#ede9fe")
PURPLE_TC  = colors.HexColor("#6d28d9")
W          = colors.white
PAGE_W, PAGE_H = A4
MARGIN     = 1.5 * cm
CONTENT_W  = PAGE_W - 2 * MARGIN


def _s(val) -> str:
    return str(val or "").strip()


# ── Styles ─────────────────────────────────────────────────────────────────

def _styles():
    def sty(name, **kw):
        defaults = dict(fontName="Helvetica", fontSize=9, leading=13, textColor=NAVY)
        return ParagraphStyle(name, **{**defaults, **kw})

    return {
        "h1":         sty("h1", fontSize=18, fontName="Helvetica-Bold", textColor=W, leading=22),
        "h2":         sty("h2", fontSize=10, fontName="Helvetica-Bold", textColor=W, leading=13),
        "sub":        sty("sub", fontSize=9, textColor=GOLD, leading=12),
        "section":    sty("sec", fontSize=8, fontName="Helvetica-Bold", textColor=W,
                          leading=11, alignment=TA_CENTER),
        "score_big":  sty("sb", fontSize=42, fontName="Helvetica-Bold", textColor=W,
                          alignment=TA_CENTER, leading=46),
        "stat_num":   sty("sn", fontSize=20, fontName="Helvetica-Bold", textColor=W,
                          alignment=TA_CENTER, leading=24),
        "stat_lbl":   sty("sl", fontSize=7, textColor=colors.HexColor("#8ba8d4"),
                          alignment=TA_CENTER, leading=9),
        "body":       sty("b",  fontSize=8, textColor=NAVY, leading=12),
        "body_gray":  sty("bg", fontSize=7, textColor=GRAY, leading=11),
        "bold":       sty("bd", fontSize=8, fontName="Helvetica-Bold", textColor=NAVY, leading=12),
        "italic":     sty("it", fontSize=8, fontName="Helvetica-Oblique", textColor=GRAY, leading=12),
        "badge":      sty("bad", fontSize=6, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=9),
        "bullet":     sty("bul", fontSize=8, textColor=NAVY, leading=13, leftIndent=8),
        "rotw_name":  sty("rn", fontSize=10, fontName="Helvetica-Bold", textColor=NAVY, leading=13),
        "rotw_body":  sty("rb", fontSize=8, textColor=GRAY, leading=12),
    }


# ── Helpers ────────────────────────────────────────────────────────────────

def _section_banner(title: str, sty) -> list:
    t = Table([[Paragraph(title, sty["section"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ]))
    return [Spacer(1, 0.3*cm), t, Spacer(1, 0.2*cm)]


def _badge(text: str, bg, tc, sty, width=1.4*cm) -> Table:
    t = Table([[Paragraph(text, ParagraphStyle("_b", fontSize=6, fontName="Helvetica-Bold",
                                               textColor=tc, alignment=TA_CENTER, leading=8))]],
              colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), bg),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 2),
        ("RIGHTPADDING",  (0,0), (-1,-1), 2),
    ]))
    return t


def _header_footer(canvas, doc):
    if doc.page == 1:
        return
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_H - 1*cm, PAGE_W, 1*cm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(W)
    canvas.drawString(MARGIN, PAGE_H - 0.65*cm, "NETWORKING INTELLIGENCE BRIEF  ·  CONFIDENTIAL")
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.65*cm,
                           f"{date.today().strftime('%d %B %Y')}  ·  Page {doc.page}")
    canvas.restoreState()


# ── Page 1: Target Brief ────────────────────────────────────────────────────

def _page1(story, context, intel, sty):
    # ── Full navy header block
    score = intel.get("network_score", 0)
    score_hex = "#22c55e" if score >= 70 else ("#f97316" if score >= 45 else "#ef4444")

    # Header table: title left | score right
    title_cell = [
        Paragraph("NETWORKING", sty["sub"]),
        Paragraph("Intelligence Brief", sty["h1"]),
        Paragraph(f"Week of {date.today().strftime('%d %B %Y')} · London Credit", sty["sub"]),
    ]
    score_cell = [
        Paragraph(f'<font color="{score_hex}">{score}</font>', sty["score_big"]),
        Paragraph("NETWORK SCORE", ParagraphStyle("_sl", fontSize=7, textColor=GOLD,
                                                   alignment=TA_CENTER, leading=9)),
    ]
    header_t = Table([[title_cell, score_cell]], colWidths=[CONTENT_W * 0.68, CONTENT_W * 0.32])
    header_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (0, -1), 14),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(header_t)

    # ── Stats strip (4 numbers)
    total   = context["total_contacts"]
    overdue = len(context["overdue"])
    never   = len(context["never_met"])
    active  = sum(1 for c in context["overdue"] + context["on_track"]
                  if (c.get("_days_since") or 999) <= 30)
    stats = [
        (str(total),              "TOTAL CONTACTS"),
        (str(never + overdue),    "NEED ACTION"),
        (str(overdue),            "OVERDUE"),
        (str(active),             "ACTIVE (30D)"),
    ]
    stat_vals = [Paragraph(v, sty["stat_num"]) for v, _ in stats]
    stat_lbls = [Paragraph(l, sty["stat_lbl"]) for _, l in stats]
    stats_t = Table([stat_vals, stat_lbls], colWidths=[CONTENT_W / 4] * 4)
    stats_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY_MID),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LINEAFTER",     (0,0), (2,-1),  0.5, colors.HexColor("#2a4a8e")),
    ]))
    story.append(stats_t)
    story.append(Spacer(1, 0.15*cm))

    # Score rationale strip
    rationale = intel.get("score_rationale", "")
    if rationale:
        r_t = Table([[Paragraph(rationale, ParagraphStyle("_sr", fontSize=7.5,
                                textColor=colors.HexColor("#374151"), leading=11,
                                fontName="Helvetica-Oblique"))]],
                    colWidths=[CONTENT_W])
        r_t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#f1f5f9")),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ]))
        story.append(r_t)

    story.append(Spacer(1, 0.1*cm))

    # ── Top Targets
    story += _section_banner("YOUR TARGETS THIS WEEK", sty)

    actions = intel.get("top_actions", [])[:5]
    rot_w = intel.get("relationship_of_the_week", {})

    col_w = [0.55*cm, 4.2*cm, 1.5*cm, CONTENT_W - 0.55*cm - 4.2*cm - 1.5*cm]
    rows = []
    for i, a in enumerate(actions, 1):
        urgency = _s(a.get("urgency", "Medium"))
        is_high = urgency == "High"
        is_rotw = _s(a.get("contact")) == _s(rot_w.get("contact"))

        urg_badge = _badge("HIGH" if is_high else "MED",
                           RED_BG if is_high else AMBER_BG,
                           RED_TC if is_high else AMBER_TC, sty)

        name_para   = [Paragraph(f"<b>{_s(a.get('contact'))}</b>", sty["body"]),
                       Paragraph(_s(a.get("fund")), sty["body_gray"])]
        if is_rotw:
            name_para.append(_badge("★ OF WEEK", PURPLE_BG, PURPLE_TC, sty, width=2.2*cm))

        detail_para = [
            Paragraph(f"<b>Why:</b> {_s(a.get('reason'))}", sty["body"]),
            Spacer(1, 2),
            Paragraph(f"<i>{_s(a.get('talking_point'))}</i>", sty["italic"]),
        ]

        rows.append([Paragraph(f"<b>{i}</b>", ParagraphStyle("_n", fontSize=9,
                               fontName="Helvetica-Bold", textColor=GRAY, alignment=TA_CENTER,
                               leading=12)),
                     name_para, urg_badge, detail_para])

    if rows:
        t = Table(rows, colWidths=col_w, repeatRows=0)
        bg_colors = [
            ("BACKGROUND", (0,i), (-1,i), OFF_WHITE if i%2==0 else W)
            for i in range(len(rows))
        ]
        t.setStyle(TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 7),
            ("BOTTOMPADDING", (0,0), (-1,-1), 7),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("LINEBELOW",     (0,0), (-1,-1), 0.5, LIGHT_GRAY),
            *bg_colors,
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No priority actions this week.", sty["body"]))

    # ── Executive Summary (compact)
    summary = intel.get("executive_summary", "")
    if summary:
        story.append(Spacer(1, 0.2*cm))
        story += _section_banner("NETWORK SNAPSHOT", sty)
        story.append(Paragraph(summary, sty["body"]))

    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())


# ── Page 2: Analytics ──────────────────────────────────────────────────────

def _page2(story, context, intel, sty):
    # ── Fund Coverage (top 20 only, sorted by last touch)
    story += _section_banner("FUND COVERAGE  ·  TOP 20 BY LAST CONTACT", sty)

    fund_rows = context["fund_rows"][:20]  # cap at 20

    STATUS_MAP = {
        "HOT":  (GREEN_BG, GREEN_TC),
        "WARM": (AMBER_BG, AMBER_TC),
        "COLD": (RED_BG,   RED_TC),
        "—":    (LIGHT_GRAY, GRAY),
    }

    header = ["Fund", "Contacts", "Last Touch", "Status"]
    cw = [CONTENT_W - 1.8*cm - 2.5*cm - 2*cm, 1.8*cm, 2.5*cm, 2*cm]

    def fund_status(lt):
        if lt is None:  return "—"
        if lt <= 14:    return "HOT"
        if lt <= 45:    return "WARM"
        return "COLD"

    rows = [header]
    for fr in fund_rows:
        lt   = fr.get("last_touch_days")
        stat = fund_status(lt)
        lt_s = f"{lt}d ago" if lt is not None else "Never"
        rows.append([
            _s(fr.get("fund", {}).get("Fund Name")),
            str(len(fr.get("contacts", []))),
            lt_s,
            stat,
        ])

    t = Table(rows, colWidths=cw, repeatRows=1)
    style = [
        ("BACKGROUND",     (0,0),  (-1,0),  NAVY),
        ("TEXTCOLOR",      (0,0),  (-1,0),  W),
        ("FONTNAME",       (0,0),  (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0,0),  (-1,-1), 8),
        ("ALIGN",          (1,0),  (-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1),  (-1,-1), [W, OFF_WHITE]),
        ("LINEBELOW",      (0,0),  (-1,-1), 0.5, LIGHT_GRAY),
        ("TOPPADDING",     (0,0),  (-1,-1), 4),
        ("BOTTOMPADDING",  (0,0),  (-1,-1), 4),
        ("LEFTPADDING",    (0,0),  (-1,-1), 6),
    ]
    for i, row in enumerate(rows[1:], 1):
        bg, tc = STATUS_MAP.get(row[3], (LIGHT_GRAY, GRAY))
        style += [
            ("BACKGROUND", (3,i), (3,i), bg),
            ("TEXTCOLOR",  (3,i), (3,i), tc),
            ("FONTNAME",   (3,i), (3,i), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 0.3*cm))

    # ── Two-column layout: Gaps + Themes
    gaps   = intel.get("coverage_gaps", [])[:4]
    themes = intel.get("market_themes", [])[:3]
    insights = intel.get("strategic_insights", [])[:3]

    def bullet_list(items, icon="▸"):
        els = []
        for item in items:
            els.append(Paragraph(f"{icon}  {_s(item)}", sty["bullet"]))
            els.append(Spacer(1, 3))
        return els

    gap_cell = (
        [Paragraph("<b>Coverage Gaps</b>", sty["bold"]), Spacer(1, 4)]
        + bullet_list(gaps, "⚑")
    )
    theme_cell = (
        [Paragraph("<b>Market Themes</b>", sty["bold"]), Spacer(1, 4)]
        + bullet_list(themes, "◆")
    )

    two_col = Table([[gap_cell, Spacer(0.3*cm, 1), theme_cell]],
                    colWidths=[(CONTENT_W - 0.3*cm) / 2, 0.3*cm, (CONTENT_W - 0.3*cm) / 2])
    two_col.setStyle(TableStyle([
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 0),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 0.3*cm))

    # ── Strategic Observations
    if insights:
        story += _section_banner("STRATEGIC OBSERVATIONS", sty)
        for obs in insights:
            story.append(Paragraph(f"→  {_s(obs)}", sty["bullet"]))
            story.append(Spacer(1, 3))

    # ── Recent Meetings
    meetings = [m for m in context.get("recent_meetings", []) if _s(m.get("Contact Name"))][:8]
    if meetings:
        story.append(Spacer(1, 0.3*cm))
        story += _section_banner("RECENT MEETINGS", sty)
        m_cw = [1.6*cm, 3.2*cm, 3.5*cm, CONTENT_W - 1.6*cm - 3.2*cm - 3.5*cm]
        m_rows = [["Date", "Contact", "Fund", "Notes"]]
        for m in meetings:
            notes = _s(m.get("Notes"))[:80]
            m_rows.append([
                _s(m.get("Date")),
                _s(m.get("Contact Name")),
                _s(m.get("Fund")),
                notes,
            ])
        mt = Table(m_rows, colWidths=m_cw, repeatRows=1)
        mt.setStyle(TableStyle([
            ("BACKGROUND",     (0,0),  (-1,0),  NAVY),
            ("TEXTCOLOR",      (0,0),  (-1,0),  W),
            ("FONTNAME",       (0,0),  (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0,0),  (-1,-1), 7.5),
            ("ROWBACKGROUNDS", (0,1),  (-1,-1), [W, OFF_WHITE]),
            ("LINEBELOW",      (0,0),  (-1,-1), 0.5, LIGHT_GRAY),
            ("TOPPADDING",     (0,0),  (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0),  (-1,-1), 4),
            ("LEFTPADDING",    (0,0),  (-1,-1), 5),
            ("VALIGN",         (0,0),  (-1,-1), "TOP"),
        ]))
        story.append(mt)


# ── Entry point ────────────────────────────────────────────────────────────

def build_pdf(context: dict, intel: dict) -> bytes:
    buf = io.BytesIO()
    margin = MARGIN

    cover_frame   = Frame(0, 0, PAGE_W, PAGE_H, leftPadding=0, rightPadding=0,
                          topPadding=0, bottomPadding=0, id="cover")
    content_frame = Frame(margin, margin, PAGE_W - 2*margin, PAGE_H - 2*margin - 1*cm,
                          id="content")

    cover_tpl   = PageTemplate(id="Cover",   frames=[cover_frame])
    content_tpl = PageTemplate(id="Content", frames=[content_frame], onPage=_header_footer)

    doc = BaseDocTemplate(buf, pagesize=A4, pageTemplates=[cover_tpl, content_tpl],
                          leftMargin=0, rightMargin=0, topMargin=0, bottomMargin=0)

    sty   = _styles()
    story = []
    _page1(story, context, intel, sty)
    _page2(story, context, intel, sty)

    doc.build(story)
    return buf.getvalue()
