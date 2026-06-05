"""
Networking Intelligence Brief — focused 2-page PDF.
"""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

NAVY      = colors.HexColor("#0d1b3e")
NAVY_MID  = colors.HexColor("#162d5e")
GOLD      = colors.HexColor("#c9a84c")
OFF_WHITE = colors.HexColor("#f8fafc")
L_GRAY    = colors.HexColor("#e5e7eb")
GRAY      = colors.HexColor("#6b7280")
RED_BG    = colors.HexColor("#fee2e2")
RED_TC    = colors.HexColor("#b91c1c")
AMB_BG    = colors.HexColor("#fef3c7")
AMB_TC    = colors.HexColor("#92400e")
GRN_BG    = colors.HexColor("#dcfce7")
GRN_TC    = colors.HexColor("#15803d")
PUR_BG    = colors.HexColor("#ede9fe")
PUR_TC    = colors.HexColor("#6d28d9")
W         = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 1.4 * cm
CW = PAGE_W - 2 * MARGIN   # usable content width


def _s(v) -> str:
    return str(v or "").strip()


def _p(text, **kw) -> Paragraph:
    kw.setdefault("fontName", "Helvetica")
    kw.setdefault("fontSize", 9)
    kw.setdefault("leading", 13)
    kw.setdefault("textColor", NAVY)
    return Paragraph(text, ParagraphStyle("_", **kw))


def _badge(text, bg, tc, w=1.5*cm):
    t = Table([[_p(text, fontSize=6, fontName="Helvetica-Bold",
                   textColor=tc, alignment=TA_CENTER, leading=8)]],
              colWidths=[w])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), bg),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 3),
        ("RIGHTPADDING",  (0,0), (-1,-1), 3),
    ]))
    return t


def _banner(title):
    t = Table([[_p(title, fontSize=8, fontName="Helvetica-Bold",
                   textColor=W, leading=10, alignment=TA_LEFT)]],
              colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
    ]))
    return t


# ── Page 1 ─────────────────────────────────────────────────────────────────

def _build_page1(context, intel):
    story = []
    score  = intel.get("network_score", 0)
    s_hex  = "#22c55e" if score >= 70 else ("#f97316" if score >= 45 else "#ef4444")
    today  = date.today().strftime("%-d %B %Y")

    total  = context["total_contacts"]
    n_act  = len(context["never_met"]) + len(context["overdue"])
    n_over = len(context["overdue"])
    n_actv = sum(1 for c in context["overdue"] + context["on_track"]
                 if (c.get("_days_since") or 999) <= 30)

    # ── Header block (full-width navy table)
    left = [
        _p("NETWORKING INTELLIGENCE BRIEF",
           fontSize=7, fontName="Helvetica-Bold", textColor=GOLD, leading=10),
        _p("London Restructuring &amp; Credit",
           fontSize=14, fontName="Helvetica-Bold", textColor=W, leading=17),
        _p(today, fontSize=8, textColor=colors.HexColor("#8ba8d4"), leading=11),
    ]
    right = [
        _p(f'<font color="{s_hex}">{score}</font>',
           fontSize=36, fontName="Helvetica-Bold", textColor=W,
           alignment=TA_CENTER, leading=40),
        _p("NETWORK SCORE", fontSize=7, textColor=GOLD,
           alignment=TA_CENTER, leading=9),
    ]
    hdr = Table([[left, right]], colWidths=[CW * 0.72, CW * 0.28])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LEFTPADDING",   (0,0), (0,-1),  12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(hdr)

    # ── Stats strip
    def stat(n, lbl): return [
        _p(str(n), fontSize=18, fontName="Helvetica-Bold", textColor=W,
           alignment=TA_CENTER, leading=22),
        _p(lbl, fontSize=6.5, textColor=colors.HexColor("#8ba8d4"),
           alignment=TA_CENTER, leading=9),
    ]
    srow1 = [stat(total, "TOTAL CONTACTS"), stat(n_act, "NEED ACTION"),
             stat(n_over, "OVERDUE"),       stat(n_actv, "ACTIVE 30D")]
    st = Table([[c[0] for c in srow1], [c[1] for c in srow1]],
               colWidths=[CW/4]*4)
    st.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY_MID),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LINEAFTER",     (0,0), (2,-1),  0.5, colors.HexColor("#253d6e")),
    ]))
    story.append(st)

    # Score rationale
    rat = _s(intel.get("score_rationale"))
    if rat:
        rt = Table([[_p(rat, fontSize=7.5, fontName="Helvetica-Oblique",
                        textColor=colors.HexColor("#374151"), leading=11)]],
                   colWidths=[CW])
        rt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#f1f5f9")),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ]))
        story.append(rt)

    story.append(Spacer(1, 0.25*cm))

    # ── Targets table
    story.append(_banner("YOUR TARGETS  ·  LONDON"))
    story.append(Spacer(1, 0.08*cm))

    actions = intel.get("top_actions", [])[:20]
    rot_w   = intel.get("relationship_of_the_week", {})

    # Column widths: # | Name + Fund | Talking point
    num_w  = 0.55*cm
    name_w = 4.5*cm
    tp_w   = CW - num_w - name_w

    # Header row
    hdr_style = dict(fontSize=7, fontName="Helvetica-Bold", textColor=W, leading=9)
    header = [
        _p("#",            **hdr_style, alignment=TA_CENTER),
        _p("NAME / FUND",  **hdr_style),
        _p("WHY REACH OUT  ·  TALKING POINT", **hdr_style),
    ]

    rows = [header]
    for i, a in enumerate(actions, 1):
        is_rw   = _s(a.get("contact")) == _s(rot_w.get("contact"))
        star    = "  ★" if is_rw else ""
        name    = _p(f"<b>{_s(a.get('contact'))}{star}</b>", fontSize=8,
                     fontName="Helvetica-Bold", textColor=NAVY, leading=11)
        fund    = _p(_s(a.get("fund")), fontSize=7, textColor=GOLD,
                     fontName="Helvetica-Bold", leading=10)
        reason  = _p(_s(a.get("reason")), fontSize=7.5,
                     textColor=colors.HexColor("#1e293b"), leading=11)
        tp      = _p(f"<i>{_s(a.get('talking_point'))}</i>", fontSize=7.5,
                     fontName="Helvetica-Oblique",
                     textColor=colors.HexColor("#374151"), leading=11)
        rows.append([
            _p(f"<b>{i}</b>", fontSize=8, fontName="Helvetica-Bold",
               textColor=GRAY, alignment=TA_CENTER, leading=11),
            [name, fund],
            [reason, Spacer(1, 2), tp],
        ])

    if len(rows) > 1:
        tgt = Table(rows, colWidths=[num_w, name_w, tp_w], repeatRows=1)
        bg_cmds = [
            ("BACKGROUND", (0, i), (-1, i), OFF_WHITE if i % 2 == 0 else W)
            for i in range(1, len(rows))
        ]
        tgt.setStyle(TableStyle([
            # Header
            ("BACKGROUND",    (0,0), (-1,0),  NAVY),
            ("TOPPADDING",    (0,0), (-1,0),  6),
            ("BOTTOMPADDING", (0,0), (-1,0),  6),
            ("LEFTPADDING",   (0,0), (-1,0),  6),
            # Body
            ("VALIGN",        (0,1), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,1), (-1,-1), 6),
            ("BOTTOMPADDING", (0,1), (-1,-1), 6),
            ("LEFTPADDING",   (0,1), (-1,-1), 6),
            ("LINEBELOW",     (0,0), (-1,-1), 0.4, L_GRAY),
            ("LINEAFTER",     (0,0), (1,-1),  0.4, L_GRAY),
            *bg_cmds,
        ]))
        story.append(tgt)
    else:
        story.append(_p("No London targets identified.", textColor=GRAY))


    story.append(PageBreak())
    return story


# ── Page 2 ─────────────────────────────────────────────────────────────────

def _build_page2(context, intel):
    story = []

    # ── Network by theme
    # Group contacts into strategy buckets, names + fund only
    by_theme = intel.get("network_by_theme", {})
    if by_theme:
        story.append(_banner("NETWORK BY THEME  ·  LONDON"))
        story.append(Spacer(1, 0.1*cm))

        THEME_COLORS = {
            "Deep Distress / Special Sits": colors.HexColor("#b91c1c"),
            "High Yield / Leveraged Credit": colors.HexColor("#0369a1"),
            "Direct Lending / Private Credit": colors.HexColor("#15803d"),
            "CLOs / Structured Credit": colors.HexColor("#7c3aed"),
            "Multi-Strategy / Opportunistic": colors.HexColor("#92400e"),
        }

        for theme, contacts in by_theme.items():
            tc = THEME_COLORS.get(theme, NAVY)
            # Theme label
            theme_row = Table(
                [[_p(theme.upper(), fontSize=7, fontName="Helvetica-Bold",
                     textColor=W, leading=9)]],
                colWidths=[CW],
            )
            theme_row.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), tc),
                ("TOPPADDING",    (0,0), (-1,-1), 4),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING",   (0,0), (-1,-1), 8),
            ]))
            story.append(theme_row)

            # One row per person, showing real background when available
            rows = []
            for c in contacts:
                role = c.get("role", "")
                bg   = c.get("background", "")

                name_cell = [
                    _p(f"<b>{c['name']}</b>", fontSize=8, fontName="Helvetica-Bold",
                       textColor=NAVY, leading=11),
                ]
                if role:
                    name_cell.append(_p(role, fontSize=7, textColor=GRAY, leading=10))

                if bg:
                    detail = _p(bg[:160], fontSize=7.5,
                                textColor=colors.HexColor("#374151"), leading=11)
                else:
                    detail = _p(c["fund"], fontSize=7.5, textColor=GRAY, leading=11)

                rows.append([name_cell, detail])

            if rows:
                t = Table(rows, colWidths=[3.8*cm, CW - 3.8*cm])
                bg_cmds = [("BACKGROUND", (0,i), (-1,i), OFF_WHITE if i%2==0 else W)
                           for i in range(len(rows))]
                t.setStyle(TableStyle([
                    ("VALIGN",        (0,0), (-1,-1), "TOP"),
                    ("TOPPADDING",    (0,0), (-1,-1), 5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                    ("LEFTPADDING",   (0,0), (-1,-1), 6),
                    ("LINEAFTER",     (0,0), (0,-1),  0.4, L_GRAY),
                    ("LINEBELOW",     (0,0), (-1,-1), 0.3, L_GRAY),
                    *bg_cmds,
                ]))
                story.append(t)
            story.append(Spacer(1, 0.2*cm))

    # ── Meetings
    mtgs = [m for m in context.get("recent_meetings", [])
            if _s(m.get("Contact Name"))][:12]
    if mtgs:
        story.append(_banner("MEETINGS"))
        story.append(Spacer(1, 0.1*cm))
        mcw   = [1.7*cm, 3.2*cm, 3*cm, CW - 1.7*cm - 3.2*cm - 3*cm]
        mrows = [["Date", "Contact", "Fund", "Notes"]]
        for m in mtgs:
            notes = _s(m.get("Notes"))
            action = _s(m.get("Action Items"))
            combined = notes + (f"  · {action}" if action else "")
            mrows.append([
                _s(m.get("Date")),
                _s(m.get("Contact Name")),
                _s(m.get("Fund")),
                combined[:100],
            ])
        mt = Table(mrows, colWidths=mcw, repeatRows=1)
        mt.setStyle(TableStyle([
            ("BACKGROUND",     (0,0),  (-1,0),  NAVY),
            ("TEXTCOLOR",      (0,0),  (-1,0),  W),
            ("FONTNAME",       (0,0),  (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",       (0,0),  (-1,-1), 7.5),
            ("ROWBACKGROUNDS", (0,1),  (-1,-1), [W, OFF_WHITE]),
            ("LINEBELOW",      (0,0),  (-1,-1), 0.5, L_GRAY),
            ("TOPPADDING",     (0,0),  (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0),  (-1,-1), 4),
            ("LEFTPADDING",    (0,0),  (-1,-1), 5),
            ("VALIGN",         (0,0),  (-1,-1), "TOP"),
        ]))
        story.append(mt)

    return story


# ── Entry point ────────────────────────────────────────────────────────────

def build_pdf(context: dict, intel: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )
    story = _build_page1(context, intel) + _build_page2(context, intel)
    doc.build(story)
    return buf.getvalue()
