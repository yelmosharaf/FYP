"""
PDF networking intelligence report — professional financial briefing style.
"""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

# ── Palette ────────────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0d1b3e")
NAVY_MID   = colors.HexColor("#1a3a6b")
GOLD       = colors.HexColor("#c9a84c")
LIGHT_BLUE = colors.HexColor("#dbeafe")
OFF_WHITE  = colors.HexColor("#f8fafc")
GRAY       = colors.HexColor("#6b7280")
LIGHT_GRAY = colors.HexColor("#e5e7eb")
RED        = colors.HexColor("#ef4444")
ORANGE     = colors.HexColor("#f97316")
GREEN      = colors.HexColor("#22c55e")
GREEN_BG   = colors.HexColor("#dcfce7")
RED_BG     = colors.HexColor("#fee2e2")
ORANGE_BG  = colors.HexColor("#ffedd5")
PURPLE_BG  = colors.HexColor("#ede9fe")
W          = colors.white
PAGE_W, PAGE_H = A4


# ── Styles ─────────────────────────────────────────────────────────────────

def _styles():
    s = getSampleStyleSheet()
    base = dict(fontName="Helvetica", leading=14)

    def sty(name, **kw):
        return ParagraphStyle(name, **{**base, **kw})

    return {
        "cover_title":   sty("ct", fontSize=26, textColor=W, fontName="Helvetica-Bold", leading=32, alignment=TA_CENTER),
        "cover_sub":     sty("cs", fontSize=13, textColor=GOLD, alignment=TA_CENTER, leading=18),
        "cover_label":   sty("cl", fontSize=9,  textColor=colors.HexColor("#8ba8d4"), alignment=TA_CENTER, leading=12),
        "cover_stat":    sty("cst", fontSize=28, textColor=W, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=32),
        "section_head":  sty("sh", fontSize=11, textColor=W, fontName="Helvetica-Bold", leading=14),
        "body":          sty("b",  fontSize=9,  textColor=NAVY, leading=13),
        "body_light":    sty("bl", fontSize=8,  textColor=GRAY, leading=12),
        "insight":       sty("ins", fontSize=9, textColor=NAVY, leading=14, leftIndent=8),
        "action_name":   sty("an", fontSize=10, textColor=NAVY, fontName="Helvetica-Bold", leading=13),
        "action_fund":   sty("af", fontSize=8,  textColor=GRAY, leading=11),
        "action_text":   sty("at", fontSize=8,  textColor=colors.HexColor("#374151"), leading=12),
        "score_big":     sty("sb", fontSize=48, textColor=NAVY, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=52),
        "score_label":   sty("sl", fontSize=10, textColor=GRAY, alignment=TA_CENTER),
        "theme":         sty("th", fontSize=9,  textColor=NAVY_MID, leading=13, leftIndent=10),
        "gap":           sty("gp", fontSize=9,  textColor=colors.HexColor("#7c3aed"), leading=13, leftIndent=10),
    }


# ── Page frames ────────────────────────────────────────────────────────────

def _make_doc(buf):
    margin = 1.5 * cm
    content_frame = Frame(margin, margin, PAGE_W - 2*margin, PAGE_H - 2*margin, id="content")
    cover_frame   = Frame(0, 0, PAGE_W, PAGE_H, id="cover", leftPadding=0, rightPadding=0,
                          topPadding=0, bottomPadding=0)

    def _header_footer(canvas, doc):
        if doc.page == 1:
            return
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_H - 1.2*cm, PAGE_W, 1.2*cm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(W)
        canvas.drawString(margin, PAGE_H - 0.75*cm, "NETWORKING INTELLIGENCE REPORT  ·  CONFIDENTIAL")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(PAGE_W - margin, PAGE_H - 0.75*cm,
                               f"Week of {date.today().strftime('%d %B %Y')}")
        canvas.setFillColor(LIGHT_GRAY)
        canvas.rect(0, 0, PAGE_W, 0.7*cm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GRAY)
        canvas.drawCentredString(PAGE_W / 2, 0.22*cm, f"Page {doc.page}  ·  Restructuring & Credit  ·  London")
        canvas.restoreState()

    cover_tpl   = PageTemplate(id="Cover",   frames=[cover_frame])
    content_tpl = PageTemplate(id="Content", frames=[content_frame], onPage=_header_footer)
    doc = BaseDocTemplate(buf, pagesize=A4, pageTemplates=[cover_tpl, content_tpl], topMargin=1.8*cm)
    return doc


# ── Section banner ─────────────────────────────────────────────────────────

def _section(title: str, sty) -> list:
    banner = Table([[Paragraph(title, sty["section_head"])]],
                   colWidths=[PAGE_W - 3*cm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("ROWPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
    ]))
    return [Spacer(1, 0.4*cm), banner, Spacer(1, 0.25*cm)]


# ── Cover page ─────────────────────────────────────────────────────────────

def _cover(story, context, intel, sty):
    W_pt = PAGE_W

    # Full navy background
    from reportlab.platypus import FrameBreak
    from reportlab.platypus.flowables import Flowable

    class ColorRect(Flowable):
        def __init__(self, w, h, color):
            self.w, self.h, self.color = w, h, color
        def draw(self):
            self.canv.setFillColor(self.color)
            self.canv.rect(-1*cm, -self.h, self.w+2*cm, self.h+1*cm, fill=1, stroke=0)
        def wrap(self, aw, ah):
            return (self.w, self.h)

    story.append(ColorRect(PAGE_W, PAGE_H, NAVY))

    # Gold rule at top
    story.append(Spacer(1, 2.5*cm))
    story.append(HRFlowable(width="85%", thickness=2, color=GOLD, spaceAfter=6, hAlign="CENTER"))

    story.append(Paragraph("NETWORKING INTELLIGENCE", sty["cover_sub"]))
    story.append(Paragraph("WEEKLY BRIEFING", sty["cover_title"]))
    story.append(Paragraph(f"Week of {date.today().strftime('%d %B %Y')}", sty["cover_sub"]))
    story.append(HRFlowable(width="85%", thickness=2, color=GOLD, spaceBefore=6, hAlign="CENTER"))

    story.append(Spacer(1, 1.2*cm))

    # Score
    score = intel.get("network_score", 0)
    score_color = GREEN if score >= 70 else (ORANGE if score >= 45 else RED)
    story.append(Paragraph(f'<font color="{score_color.hexval()}">{score}</font>', sty["score_big"]))
    story.append(Paragraph("NETWORK SCORE", sty["score_label"]))
    story.append(Spacer(1, 0.8*cm))

    # Key stats row
    stats = [
        (str(context["total_contacts"]), "CONTACTS"),
        (str(context["action_count"]),   "NEED ACTION"),
        (str(len(context["fund_rows"])), "FUNDS"),
        (str(len(context["on_track"])),  "ON TRACK"),
    ]
    stat_data = [[Paragraph(v, sty["cover_stat"]) for v, _ in stats],
                 [Paragraph(l, sty["cover_label"]) for _, l in stats]]
    stat_table = Table(stat_data, colWidths=[PAGE_W/4]*4)
    stat_table.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER"), ("TOPPADDING", (0,0), (-1,-1), 4)]))
    story.append(stat_table)

    story.append(Spacer(1, 0.8*cm))
    story.append(HRFlowable(width="75%", thickness=0.5, color=colors.HexColor("#1e3a6e"), hAlign="CENTER"))
    story.append(Spacer(1, 0.4*cm))

    # Executive summary
    summary = intel.get("executive_summary", "")
    story.append(Paragraph(summary, ParagraphStyle("es", fontName="Helvetica", fontSize=9,
                                                    textColor=colors.HexColor("#cbd5e1"),
                                                    alignment=TA_CENTER, leading=15,
                                                    leftIndent=2*cm, rightIndent=2*cm)))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Restructuring &amp; Credit  ·  London  ·  CONFIDENTIAL",
                            sty["cover_label"]))

    story.append(NextPageTemplate("Content"))
    story.append(PageBreak())


# ── Priority Actions ────────────────────────────────────────────────────────

def _priority_actions(story, intel, sty):
    story += _section("01  PRIORITY ACTIONS THIS WEEK", sty)

    actions = intel.get("top_actions", [])
    if not actions:
        story.append(Paragraph("No priority actions identified.", sty["body"]))
        return

    rel_of_week = intel.get("relationship_of_the_week", {})

    for i, a in enumerate(actions, 1):
        urgency = a.get("urgency", "Medium")
        urg_color = RED_BG if urgency == "High" else ORANGE_BG
        urg_text_color = colors.HexColor("#b91c1c") if urgency == "High" else colors.HexColor("#c2410c")
        badge = Table([[Paragraph(urgency.upper(), ParagraphStyle("u", fontSize=7, fontName="Helvetica-Bold",
                                                                   textColor=urg_text_color, alignment=TA_CENTER))]],
                      colWidths=[1.6*cm])
        badge.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), urg_color),
                                   ("ROWPADDING",(0,0),(-1,-1),3)]))
        rot_badge = Table([[Paragraph(f"RELATIONSHIP OF THE WEEK", ParagraphStyle("rotw", fontSize=6.5,
                                      fontName="Helvetica-Bold", textColor=colors.HexColor("#7c3aed"),
                                      alignment=TA_CENTER))]],
                          colWidths=[3.5*cm]) if a.get("contact") == rel_of_week.get("contact") else None

        name_cell = [Paragraph(f"{i}. {a.get('contact','')}", sty["action_name"]),
                     Paragraph(a.get("fund",""), sty["action_fund"])]
        reason_cell = [Paragraph(f"<b>Why now:</b> {a.get('reason','')}", sty["action_text"]),
                       Spacer(1,3),
                       Paragraph(f"<b>Talking point:</b> {a.get('talking_point','')}", sty["action_text"])]
        if rot_badge:
            reason_cell.insert(0, rot_badge)
            reason_cell.insert(1, Spacer(1,3))

        row = Table([[name_cell, badge, reason_cell]],
                    colWidths=[3.8*cm, 1.8*cm, PAGE_W - 3*cm - 3.8*cm - 1.8*cm - 0.8*cm])
        row.setStyle(TableStyle([
            ("BACKGROUND",  (0,0), (-1,-1), OFF_WHITE if i % 2 == 0 else W),
            ("ROWPADDING",  (0,0), (-1,-1), 8),
            ("LEFTPADDING", (0,0), (0,-1), 10),
            ("VALIGN",      (0,0), (-1,-1), "TOP"),
            ("LINEBELOW",   (0,0), (-1,-1), 0.5, LIGHT_GRAY),
        ]))
        story.append(row)

    story.append(PageBreak())


# ── Fund Coverage ───────────────────────────────────────────────────────────

def _fund_coverage(story, context, sty):
    story += _section("02  FUND COVERAGE MAP", sty)

    headers = ["Fund", "Strategy", "Contacts", "Last Touch", "Status"]
    rows = [headers]

    for fr in context["fund_rows"]:
        f = fr.get("fund", {})
        n_contacts = len(fr.get("contacts", []))
        lt = fr.get("last_touch_days")
        if lt is None:
            lt_str, status = "Never", "COLD"
        elif lt <= 14:
            lt_str, status = f"{lt}d ago", "HOT"
        elif lt <= 45:
            lt_str, status = f"{lt}d ago", "WARM"
        else:
            lt_str, status = f"{lt}d ago", "COLD"
        rows.append([
            f.get("Fund Name", ""),
            f.get("Strategy", "")[:45] if f.get("Strategy") else "—",
            str(n_contacts),
            lt_str,
            status,
        ])

    col_w = [5*cm, 6.5*cm, 1.8*cm, 2*cm, 1.8*cm]
    t = Table(rows, colWidths=col_w, repeatRows=1)

    style = [
        ("BACKGROUND",  (0,0), (-1,0),  NAVY),
        ("TEXTCOLOR",   (0,0), (-1,0),  W),
        ("FONTNAME",    (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [W, OFF_WHITE]),
        ("LINEBELOW",   (0,0), (-1,-1), 0.5, LIGHT_GRAY),
        ("TOPPADDING",  (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]
    for i, row in enumerate(rows[1:], 1):
        status = row[4]
        bg = GREEN_BG if status == "HOT" else (ORANGE_BG if status == "WARM" else RED_BG)
        tc = colors.HexColor("#15803d") if status == "HOT" else \
             (colors.HexColor("#c2410c") if status == "WARM" else colors.HexColor("#b91c1c"))
        style += [("BACKGROUND", (4,i), (4,i), bg), ("TEXTCOLOR", (4,i), (4,i), tc),
                  ("FONTNAME", (4,i), (4,i), "Helvetica-Bold")]

    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(PageBreak())


# ── Strategic Intelligence ──────────────────────────────────────────────────

def _strategic_intel(story, intel, sty):
    story += _section("03  STRATEGIC INTELLIGENCE", sty)

    # Score rationale
    story.append(Paragraph(
        f"<b>Score rationale:</b> {intel.get('score_rationale','')}",
        sty["body"]
    ))
    story.append(Spacer(1, 0.4*cm))

    # Insights
    story.append(Paragraph("<b>Network observations</b>", sty["body"]))
    story.append(Spacer(1, 0.15*cm))
    for ins in intel.get("strategic_insights", []):
        story.append(Paragraph(f"→  {ins}", sty["insight"]))
        story.append(Spacer(1, 0.15*cm))

    story.append(Spacer(1, 0.4*cm))

    # Market themes
    story.append(Paragraph("<b>Market themes for conversation</b>", sty["body"]))
    story.append(Spacer(1, 0.15*cm))
    for t in intel.get("market_themes", []):
        story.append(Paragraph(f"◆  {t}", sty["theme"]))
        story.append(Spacer(1, 0.15*cm))

    story.append(Spacer(1, 0.4*cm))

    # Coverage gaps
    story.append(Paragraph("<b>Coverage gaps to address</b>", sty["body"]))
    story.append(Spacer(1, 0.15*cm))
    for g in intel.get("coverage_gaps", []):
        story.append(Paragraph(f"⚑  {g}", sty["gap"]))
        story.append(Spacer(1, 0.15*cm))

    story.append(PageBreak())


# ── Recent Meetings ──────────────────────────────────────────────────────────

def _recent_meetings(story, context, sty):
    story += _section("04  RECENT MEETINGS", sty)

    meetings = context.get("recent_meetings", [])
    if not meetings:
        story.append(Paragraph("No meetings logged in the last 14 days.", sty["body"]))
        return

    headers = ["Date", "Contact", "Fund", "Type", "Notes / Action Items"]
    rows = [headers]
    for m in meetings:
        notes = m.get("Notes", "")
        actions = m.get("Action Items", "")
        combined = notes
        if actions:
            combined += f"  •  Action: {actions}"
        rows.append([
            m.get("Date", ""),
            m.get("Contact Name", ""),
            m.get("Fund", ""),
            m.get("Type", ""),
            combined[:120],
        ])

    col_w = [1.8*cm, 3.5*cm, 4*cm, 1.6*cm, PAGE_W - 3*cm - 1.8 - 3.5 - 4 - 1.6]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (-1,0),  NAVY),
        ("TEXTCOLOR",      (0,0), (-1,0),  W),
        ("FONTNAME",       (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0,0), (-1,-1), 8),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [W, OFF_WHITE]),
        ("LINEBELOW",      (0,0), (-1,-1), 0.5, LIGHT_GRAY),
        ("TOPPADDING",     (0,0), (-1,-1), 5),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 5),
        ("LEFTPADDING",    (0,0), (-1,-1), 5),
        ("VALIGN",         (0,0), (-1,-1), "TOP"),
    ]))
    story.append(t)


# ── Main entry point ────────────────────────────────────────────────────────

def build_pdf(context: dict, intel: dict) -> bytes:
    buf = io.BytesIO()
    doc = _make_doc(buf)
    sty = _styles()
    story = []

    _cover(story, context, intel, sty)
    _priority_actions(story, intel, sty)
    _fund_coverage(story, context, sty)
    _strategic_intel(story, intel, sty)
    _recent_meetings(story, context, sty)

    doc.build(story)
    return buf.getvalue()
