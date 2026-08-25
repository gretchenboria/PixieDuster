#!/usr/bin/env python3
"""Render docs/PixieDuster-Architecture.pdf.

A standalone, re-runnable, deterministic build of the PixieDuster CLI
architecture document. fpdf2 core fonts only (Helvetica + Courier); every
diagram is drawn with primitives.

    .venv-cli/bin/python scripts/make_pdf.py
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# --------------------------------------------------------------------------
# palette + geometry
# --------------------------------------------------------------------------

DEEP = (15, 8, 28)        # #0f081c
PURPLE = (43, 24, 69)     # #2b1845
PANEL = (32, 18, 52)      # between the two, for code panels
PANEL_EDGE = (66, 42, 96)
GOLD = (255, 215, 0)      # #ffd700
DIM_GOLD = (218, 165, 32) # #daa520
LILAC = (226, 209, 249)   # #e2d1f9
MAUVE = (209, 196, 233)   # #d1c4e9
FAINT = (140, 124, 168)
ROSE = (232, 138, 138)    # for the honest-caveat accents

PAGE_W, PAGE_H = 210.0, 297.0
MARGIN = 19.0
TOP = 24.0
BOTTOM = 20.0
CW = PAGE_W - 2 * MARGIN

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "logo.png"
OUT = ROOT / "docs" / "PixieDuster-Architecture.pdf"

BUILD_DATE = "24 August 2026"

# Core fonts are cp1252. Everything that leaves this module goes through here,
# which also enforces the no-emoji rule the hard way.
_SUBS = {
    "—": " - ", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...", "→": "->",
    "←": "<-", "•": "-", "✓": "v", " ": " ",
    "─": "-", "●": "o", "×": "x",
}


def T(text: str) -> str:
    """Make a string safe for the cp1252 core fonts."""
    out = str(text)
    for bad, good in _SUBS.items():
        out = out.replace(bad, good)
    return out.encode("cp1252", "replace").decode("cp1252")


class Doc(FPDF):
    """A dark-page document with a gold rule and a running footer."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(MARGIN, TOP, MARGIN)
        self.set_auto_page_break(True, margin=BOTTOM)
        self.set_creation_date(_dt.datetime(2026, 8, 24, 12, 0, 0, tzinfo=_dt.timezone.utc))
        self.set_title(T("PixieDuster CLI - Architecture and Implementation"))
        self.set_author(T("PixieDuster swarm build"))
        self.set_subject(T("How the PixieDuster CLI works, and what it is built from"))
        self.section = ""
        self.cover = False

    # -- chrome ------------------------------------------------------------

    def header(self) -> None:
        self.set_fill_color(*DEEP)
        self.rect(0, 0, PAGE_W, PAGE_H, style="F")
        if self.cover or self.page_no() == 1:
            return
        self.set_draw_color(*DIM_GOLD)
        self.set_line_width(0.25)
        self.line(MARGIN, 15.0, PAGE_W - MARGIN, 15.0)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*DIM_GOLD)
        self.set_xy(MARGIN, 9.6)
        self.cell(CW / 2, 4, T("PIXIEDUSTER CLI"), align="L")
        self.set_text_color(*FAINT)
        self.set_xy(MARGIN + CW / 2, 9.6)
        self.cell(CW / 2, 4, T(self.section.upper()), align="R")
        self.set_xy(MARGIN, TOP)

    def footer(self) -> None:
        if self.cover or self.page_no() == 1:
            return
        self.set_y(-14.0)
        self.set_draw_color(*PANEL_EDGE)
        self.set_line_width(0.2)
        self.line(MARGIN, self.get_y() - 1.5, PAGE_W - MARGIN, self.get_y() - 1.5)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*FAINT)
        self.cell(CW / 2, 5, T("Architecture and Implementation  -  v0.1.0"), align="L")
        self.set_text_color(*DIM_GOLD)
        self.cell(CW / 2, 5, T(str(self.page_no())), align="R")


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------


def need(d: Doc, mm: float) -> None:
    """Start a new page unless ``mm`` of vertical space remains."""
    if d.get_y() + mm > PAGE_H - BOTTOM:
        d.add_page()


def para(d: Doc, *segments, size: float = 9.4, lh: float = 5.1, gap: float = 3.4) -> None:
    """Flow a paragraph of mixed styles.

    Each segment is a str (body colour, regular) or ``(text, style, colour)``.
    """
    need(d, lh * 2)
    d.set_x(MARGIN)
    for seg in segments:
        if isinstance(seg, str):
            text, style, colour = seg, "", MAUVE
        else:
            text = seg[0]
            style = seg[1] if len(seg) > 1 else ""
            colour = seg[2] if len(seg) > 2 else MAUVE
        font = "Courier" if "C" in style else "Helvetica"
        d.set_font(font, style.replace("C", ""), size if font == "Helvetica" else size - 0.7)
        d.set_text_color(*colour)
        d.write(lh, T(text))
    d.ln(lh)
    d.ln(gap)


def bullets(d: Doc, items, size: float = 9.4, lh: float = 5.0, gap: float = 2.4) -> None:
    """A dash-marked list; each item is a paragraph-style segment tuple/str."""
    for item in items:
        segs = item if isinstance(item, (list, tuple)) else [item]
        need(d, lh * 2)
        y0 = d.get_y()
        d.set_draw_color(*DIM_GOLD)
        d.set_line_width(0.4)
        d.line(MARGIN + 1.4, y0 + 2.5, MARGIN + 4.2, y0 + 2.5)
        d.set_left_margin(MARGIN + 7.0)
        d.set_xy(MARGIN + 7.0, y0)
        for seg in segs:
            if isinstance(seg, str):
                text, style, colour = seg, "", MAUVE
            else:
                text = seg[0]
                style = seg[1] if len(seg) > 1 else ""
                colour = seg[2] if len(seg) > 2 else MAUVE
            font = "Courier" if "C" in style else "Helvetica"
            d.set_font(font, style.replace("C", ""), size if font == "Helvetica" else size - 0.7)
            d.set_text_color(*colour)
            d.write(lh, T(text))
        d.ln(lh)
        d.set_left_margin(MARGIN)
        d.ln(gap)
    d.ln(1.6)


def h1(d: Doc, number: str, title: str, *, new_page: bool = True) -> None:
    d.section = title
    if new_page:
        d.add_page()
    need(d, 26)
    y = d.get_y()
    d.set_font("Helvetica", "B", 26)
    d.set_text_color(*PURPLE)
    # ghost numeral, set behind the title in deep purple
    d.set_text_color(58, 34, 90)
    d.set_xy(MARGIN, y - 1)
    d.cell(20, 12, T(number))
    d.set_font("Helvetica", "B", 15.5)
    d.set_text_color(*GOLD)
    d.set_xy(MARGIN + 16, y + 1.2)
    d.cell(CW - 16, 9, T(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.5)
    d.line(MARGIN, d.get_y() + 1.5, MARGIN + 34, d.get_y() + 1.5)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.3)
    d.line(MARGIN + 36, d.get_y() + 1.5, PAGE_W - MARGIN, d.get_y() + 1.5)
    d.set_y(d.get_y() + 7.0)


def h2(d: Doc, title: str) -> None:
    need(d, 20)
    d.ln(1.0)
    d.set_font("Helvetica", "B", 10.4)
    d.set_text_color(*LILAC)
    d.set_x(MARGIN)
    d.cell(CW, 6, T(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    d.ln(1.6)


def code(d: Doc, lines, *, caption: str | None = None, size: float = 8.0) -> None:
    """A Courier block on a subtly lighter panel."""
    lh = size * 0.47
    pad = 3.2
    height = pad * 2 + lh * len(lines) + (4.6 if caption else 0)
    need(d, height + 4)
    y0 = d.get_y()
    d.set_fill_color(*PANEL)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.2)
    d.rect(MARGIN, y0, CW, height, style="DF")
    d.set_fill_color(*DIM_GOLD)
    d.rect(MARGIN, y0, 0.9, height, style="F")
    y = y0 + pad
    if caption:
        d.set_font("Helvetica", "B", 7.2)
        d.set_text_color(*DIM_GOLD)
        d.set_xy(MARGIN + 5, y)
        d.cell(CW - 8, 4, T(caption.upper()))
        y += 4.6
    d.set_font("Courier", "", size)
    for line in lines:
        colour = FAINT if line.strip().startswith("#") else LILAC
        d.set_text_color(*colour)
        d.set_xy(MARGIN + 5, y)
        d.cell(CW - 8, lh, T(line))
        y += lh
    d.set_y(y0 + height + 4.0)


def callout(d: Doc, title: str, *segments, tint=GOLD) -> None:
    """A boxed aside in the accent colour."""
    d.ln(2.6)
    need(d, 30)
    y0 = d.get_y()
    d.set_xy(MARGIN + 6, y0 + 4.6)
    d.set_left_margin(MARGIN + 6)
    d.set_right_margin(MARGIN + 6)
    for seg in segments:
        if isinstance(seg, str):
            text, style, colour = seg, "", MAUVE
        else:
            text = seg[0]
            style = seg[1] if len(seg) > 1 else ""
            colour = seg[2] if len(seg) > 2 else MAUVE
        font = "Courier" if "C" in style else "Helvetica"
        d.set_font(font, style.replace("C", ""), 8.9 if font == "Helvetica" else 8.2)
        d.set_text_color(*colour)
        d.write(4.8, T(text))
    d.ln(4.8)
    y1 = d.get_y()
    d.set_left_margin(MARGIN)
    d.set_right_margin(MARGIN)
    # frame it (drawn after, so it must be stroke-only over the text)
    d.set_draw_color(*tint)
    d.set_line_width(0.3)
    d.rect(MARGIN, y0, CW, y1 - y0 + 3.4, style="D")
    d.set_font("Helvetica", "B", 7.4)
    label = T(title.upper())
    d.set_fill_color(*DEEP)
    d.rect(MARGIN + 5, y0 - 1.7, d.get_string_width(label) + 4.0, 3.4, style="F")
    d.set_text_color(*tint)
    d.set_xy(MARGIN + 7, y0 - 3.1)
    d.cell(80, 4, label)
    d.set_y(y1 + 7.0)


def table(d: Doc, headers, rows, widths, *, size: float = 8.4, align=None) -> None:
    """A rule-separated table. ``widths`` are fractions of the content width."""
    cols = [CW * w for w in widths]
    align = align or ["L"] * len(headers)
    lh = 5.0
    need(d, lh * 3)
    d.set_font("Helvetica", "B", size - 0.4)
    d.set_text_color(*DIM_GOLD)
    y = d.get_y()
    x = MARGIN
    for i, head in enumerate(headers):
        d.set_xy(x, y)
        d.cell(cols[i], lh, T(head), align=align[i])
        x += cols[i]
    d.set_y(y + lh)
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.3)
    d.line(MARGIN, d.get_y() + 0.4, PAGE_W - MARGIN, d.get_y() + 0.4)
    d.set_y(d.get_y() + 1.8)

    for row in rows:
        # height = tallest wrapped cell
        heights = []
        for i, cell_text in enumerate(row):
            mono = cell_text.startswith("`")
            text = cell_text.strip("`")
            d.set_font("Courier" if mono else "Helvetica", "", size - (0.6 if mono else 0))
            words = T(text).split()
            line, count = "", 1
            for word in words:
                trial = (line + " " + word).strip()
                if d.get_string_width(trial) > cols[i] - 3:
                    line, count = word, count + 1
                else:
                    line = trial
            heights.append(count * (lh - 0.4))
        h = max(heights) + 1.6
        need(d, h + 2)
        y = d.get_y()
        x = MARGIN
        for i, cell_text in enumerate(row):
            mono = cell_text.startswith("`")
            text = cell_text.strip("`")
            d.set_font("Courier" if mono else "Helvetica", "", size - (0.6 if mono else 0))
            d.set_text_color(*(LILAC if (mono or i == 0) else MAUVE))
            d.set_xy(x, y)
            d.multi_cell(cols[i], lh - 0.4, T(text), align=align[i],
                         new_x=XPos.RIGHT, new_y=YPos.TOP)
            x += cols[i]
        d.set_y(y + h)
        d.set_draw_color(*PANEL_EDGE)
        d.set_line_width(0.15)
        d.line(MARGIN, d.get_y() - 0.8, PAGE_W - MARGIN, d.get_y() - 0.8)
    d.ln(3.0)


# --------------------------------------------------------------------------
# drawing primitives for the diagrams
# --------------------------------------------------------------------------


def box(d: Doc, x, y, w, h, label, *, sub=None, edge=DIM_GOLD, fill=PURPLE,
        text=LILAC, size=7.6, radius=1.6) -> None:
    d.set_fill_color(*fill)
    d.set_draw_color(*edge)
    d.set_line_width(0.35)
    d.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=radius)
    d.set_font("Helvetica", "B", size)
    d.set_text_color(*text)
    d.set_xy(x, y + (h / 2 - (5.4 if sub else 2.6)))
    d.multi_cell(w, 3.4, T(label), align="C")
    if sub:
        d.set_font("Helvetica", "", size - 1.4)
        d.set_text_color(*FAINT)
        d.set_xy(x, y + h / 2 + 0.6)
        d.multi_cell(w, 3.1, T(sub), align="C")


def arrow(d: Doc, x1, y1, x2, y2, *, colour=GOLD, head=1.7, width=0.35, dashed=False) -> None:
    d.set_draw_color(*colour)
    d.set_line_width(width)
    if dashed:
        d.set_dash_pattern(dash=1.2, gap=1.2)
    d.line(x1, y1, x2, y2)
    if dashed:
        d.set_dash_pattern()
    # arrowhead
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    d.set_fill_color(*colour)
    p1 = (x2, y2)
    p2 = (x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p3 = (x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    with d.new_path(p1[0], p1[1]) as path:
        path.style.fill_color = "#%02x%02x%02x" % colour
        path.style.stroke_color = "#%02x%02x%02x" % colour
        path.line_to(p2[0], p2[1])
        path.line_to(p3[0], p3[1])
        path.close()


def caption(d: Doc, text: str) -> None:
    d.set_font("Helvetica", "I", 7.6)
    d.set_text_color(*FAINT)
    d.set_x(MARGIN)
    d.multi_cell(CW, 4.2, T(text), align="C")
    d.ln(3.0)


def sparkles(d: Doc, seed: int, count: int, x0, y0, w, h, *, big=False) -> None:
    """Deterministic scatter of pixie dust (an LCG, so no random module)."""
    state = seed
    for _ in range(count):
        state = (1103515245 * state + 12345) % 2147483648
        fx = (state >> 8) % 10000 / 10000
        state = (1103515245 * state + 12345) % 2147483648
        fy = (state >> 8) % 10000 / 10000
        state = (1103515245 * state + 12345) % 2147483648
        pick = (state >> 8) % 100
        x = x0 + fx * w
        y = y0 + fy * h
        r = (0.35 if pick < 55 else 0.7) * (1.5 if big else 1.0)
        colour = GOLD if pick % 3 == 0 else (DIM_GOLD if pick % 3 == 1 else (110, 88, 150))
        d.set_fill_color(*colour)
        d.ellipse(x - r / 2, y - r / 2, r, r, style="F")


def budget_diagram(d: Doc) -> None:
    """Two segmented bars: the nominal shares, and the same budget with no PRs."""
    need(d, 54)
    y0 = d.get_y()
    d.set_fill_color(*PURPLE)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.2)
    d.rect(MARGIN, y0, CW, 48, style="DF", round_corners=True, corner_radius=2)
    sparkles(d, 313, 40, MARGIN, y0, CW, 48)

    bar_x = MARGIN + 8
    bar_w = CW - 16
    kinds = ["commit", "doc", "comment", "pr"]
    tints = {"commit": (255, 215, 0), "doc": (214, 168, 74),
             "comment": (166, 120, 214), "pr": (110, 88, 150)}

    def bar(y: float, shares, label: str, note: str) -> None:
        d.set_font("Helvetica", "B", 7.0)
        d.set_text_color(*LILAC)
        d.set_xy(bar_x, y - 5.2)
        d.cell(60, 4, T(label))
        d.set_font("Helvetica", "", 6.4)
        d.set_text_color(*FAINT)
        d.set_xy(bar_x + bar_w - 80, y - 5.2)
        d.cell(80, 4, T(note), align="R")
        x = bar_x
        for kind in kinds:
            share = shares.get(kind, 0.0)
            if share <= 0:
                continue
            w = bar_w * share
            d.set_fill_color(*tints[kind])
            d.rect(x, y, w, 8.0, style="F")
            d.set_font("Helvetica", "B", 6.4)
            d.set_text_color(*DEEP)
            d.set_xy(x, y + 2.0)
            d.cell(w, 4, T(f"{kind} {share * 100:.0f}%"), align="C")
            x += w

    bar(y0 + 12, {"commit": 0.40, "doc": 0.25, "comment": 0.20, "pr": 0.15},
        "default", "180,000 characters, split four ways")
    bar(y0 + 33, {"commit": 0.471, "doc": 0.294, "comment": 0.235},
        "--no-pr, or no gh installed",
        "the PR share is redistributed, not wasted")
    d.set_y(y0 + 52)
    caption(d, "A source that is absent or small hands its unused share to the groups that are still short.")


def scan_diagram(d: Doc) -> None:
    """One _collect() pass feeding both scan() and redact()."""
    need(d, 62)
    y0 = d.get_y()
    d.set_fill_color(*PURPLE)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.2)
    d.rect(MARGIN, y0, CW, 56, style="DF", round_corners=True, corner_radius=2)
    sparkles(d, 5150, 40, MARGIN, y0, CW, 56)

    bh = 15.0
    y_mid = y0 + 8
    w1, w2, w3 = 36.0, 44.0, 40.0
    x1 = MARGIN + 6
    x2 = x1 + w1 + 8
    x3 = x2 + w2 + 8

    box(d, x1, y_mid, w1, bh, "outbound text", sub="every Sample")
    arrow(d, x1 + w1 + 0.6, y_mid + bh / 2, x2 - 0.8, y_mid + bh / 2)
    box(d, x2, y_mid, w2, bh, "22 rules, in order", sub="first claim wins")
    arrow(d, x2 + w2 + 0.6, y_mid + bh / 2, x3 - 0.8, y_mid + bh / 2)
    box(d, x3, y_mid, w3, bh, "validators", sub="placeholder / shape / entropy")

    # the single collect pass
    y_hits = y_mid + bh + 9
    hw = 48.0
    hx = MARGIN + (CW - hw) / 2
    box(d, hx, y_hits, hw, 11.0, "_collect() -> accepted hits", edge=GOLD, size=7.4)
    d.set_draw_color(*GOLD)
    d.set_line_width(0.35)
    d.line(x3 + w3 / 2, y_mid + bh, x3 + w3 / 2, y_hits + 5.5)
    arrow(d, x3 + w3 / 2, y_hits + 5.5, hx + hw + 0.8, y_hits + 5.5)

    # two consumers
    y_out = y_hits + 11 + 9
    ow = 62.0
    ox1 = MARGIN + 14
    ox2 = PAGE_W - MARGIN - 14 - ow
    box(d, ox1, y_out, ow, 13.0, "scan() -> Findings",
        sub="excerpt redacted, then _leaks() checked")
    box(d, ox2, y_out, ow, 13.0, "redact() -> <REDACTED:rule>",
        sub="the same spans, the same answer")
    d.set_draw_color(*GOLD)
    d.line(hx + hw / 2, y_hits + 11, hx + hw / 2, y_hits + 15.5)
    d.line(ox1 + ow / 2, y_hits + 15.5, ox2 + ow / 2, y_hits + 15.5)
    arrow(d, ox1 + ow / 2, y_hits + 15.5, ox1 + ow / 2, y_out - 0.8)
    arrow(d, ox2 + ow / 2, y_hits + 15.5, ox2 + ow / 2, y_out - 0.8)

    d.set_y(y0 + 60)
    caption(d, "One pass, two consumers. They cannot disagree, because there is only one answer to disagree about.")


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


def cover(d: Doc) -> None:
    d.cover = True
    d.add_page()
    d.set_fill_color(*PURPLE)
    d.rect(0, 0, PAGE_W, 132, style="F")
    d.set_fill_color(*DEEP)
    d.rect(0, 118, PAGE_W, PAGE_H - 118, style="F")
    sparkles(d, 20260824, 150, 0, 0, PAGE_W, 140, big=True)

    if LOGO.exists():
        d.image(str(LOGO), x=(PAGE_W - 168) / 2, y=6, w=168)

    d.set_draw_color(*GOLD)
    d.set_line_width(0.6)
    d.line(MARGIN + 34, 140, PAGE_W - MARGIN - 34, 140)
    d.set_fill_color(*GOLD)
    d.ellipse(PAGE_W / 2 - 0.9, 139.1, 1.8, 1.8, style="F")

    d.set_xy(0, 150)
    d.set_font("Helvetica", "B", 30)
    d.set_text_color(*GOLD)
    d.cell(PAGE_W, 14, T("PixieDuster CLI"), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    d.set_font("Helvetica", "", 13)
    d.set_text_color(*LILAC)
    d.set_xy(0, 167)
    d.cell(PAGE_W, 8, T("Architecture and Implementation"), align="C",
           new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    d.set_font("Helvetica", "I", 10)
    d.set_text_color(*FAINT)
    d.set_xy(0, 178)
    d.cell(PAGE_W, 6, T("Your Fairy Prompt-Mother, at the command line"), align="C")

    # stat strip
    stats = [("4,435", "lines of module code"), ("412", "tests, all offline"),
             ("22", "secret rules"), ("0", "network calls in mining or safety")]
    y = 202
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.25)
    d.line(MARGIN, y - 8, PAGE_W - MARGIN, y - 8)
    colw = CW / 4
    for i, (value, label) in enumerate(stats):
        x = MARGIN + i * colw
        d.set_font("Helvetica", "B", 17)
        d.set_text_color(*GOLD)
        d.set_xy(x, y)
        d.cell(colw, 8, T(value), align="C")
        d.set_font("Helvetica", "", 7.2)
        d.set_text_color(*FAINT)
        d.set_xy(x, y + 8.5)
        d.multi_cell(colw, 3.4, T(label), align="C")
    d.line(MARGIN, y + 22, PAGE_W - MARGIN, y + 22)

    d.set_font("Helvetica", "", 7.6)
    d.set_text_color(*DIM_GOLD)
    d.set_xy(0, 272)
    d.cell(PAGE_W, 5, T("PixieDuster 0.1.0   -   " + BUILD_DATE), align="C")
    d.cover = False


def start_here(d: Doc) -> None:
    """A plain-language page, before any of the technical material."""
    h1(d, "", "Start here")

    para(d,
         ("In one sentence.", "B", GOLD),
         (" It reads the writing you have already done in a project - your commit "
          "messages, your README, the notes you leave in your code - and works out how "
          "you write. Then it writes that down as instructions an AI can follow, so the "
          "AI sounds like you instead of sounding like a robot.", "", MAUVE))

    h2(d, "Why you would want it")
    para(d,
         ("Your web app does this already, but you have to find writing samples and upload "
          "them. This version skips that. Your repository is already full of your writing, "
          "so it just reads it.", "", MAUVE))

    h2(d, "How to use it")
    para(d, ("There is really only one command. Type this inside any project folder:",
             "", MAUVE))
    code(d, ["pixieduster clone"])
    para(d,
         ("It then walks you through everything. You will see a gold PixieDuster logo, it "
          "will read the project, ask you three questions you answer with the arrow keys, "
          "and let you set how funny the persona should be with a slider. At the end it "
          "saves a file called ", "", MAUVE), ("AGENTS.md", "C", LILAC),
         (" and shows you a certificate.", "", MAUVE))
    para(d, ("Two others, once you have that file:", "", MAUVE))
    code(d, [
        "pixieduster chat            # talk to it, hear how it sounds",
        "pixieduster diff draft.md   # ask: does this sound like me?",
    ])

    h2(d, "The one thing to be careful about")
    para(d,
         ("Your writing gets sent to Google to be analysed. That is how it works, and there "
          "is no way around it. So before it sends anything, you can look at exactly what "
          "would go:", "", MAUVE))
    code(d, ["pixieduster clone --dry-run"])
    para(d,
         ("That prints the full list and sends nothing at all. It also checks for passwords "
          "and keys hiding in your text and refuses to send quietly if it finds any.",
          "", MAUVE))

    callout(
        d, "If you read nothing else",
        ("Run ", "", MAUVE), ("pixieduster clone --dry-run", "C", LILAC),
        (" first to see what it would send. Then run ", "", MAUVE),
        ("pixieduster clone", "C", LILAC),
        (" and answer the questions. Everything after this page is detail you only need "
         "when something breaks.", "", MAUVE),
        tint=GOLD,
    )


def contents(d: Doc) -> None:
    d.section = "Contents"
    d.add_page()
    d.set_font("Helvetica", "B", 20)
    d.set_text_color(*GOLD)
    d.cell(CW, 12, T("Contents"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.5)
    d.line(MARGIN, d.get_y() + 1, MARGIN + 34, d.get_y() + 1)
    d.ln(9)

    entries = [
        ("1", "What it is", "The same brain as the web app, fed from a git repo"),
        ("2", "The pipeline", "Nine steps from a repo to an AGENTS.md"),
        ("3", "Module map", "Eight modules, who owns what, who calls whom"),
        ("4", "Mining", "Four sources, and why each is filtered the way it is"),
        ("5", "Safety", "What stands between a private repo and Google"),
        ("6", "API key handling", "Bring your own key, and why it has to be that way"),
        ("7", "The TUI", "Rich, one Live region, and two bugs worth remembering"),
        ("8", "Tech stack", "Everything the wheel depends on"),
        ("9", "Open items", "What is resolved, and what to keep in mind"),
    ]
    for num, title, blurb in entries:
        y = d.get_y()
        d.set_font("Helvetica", "B", 12)
        d.set_text_color(*DIM_GOLD)
        d.set_xy(MARGIN, y)
        d.cell(12, 7, T(num), align="R")
        d.set_font("Helvetica", "B", 11.4)
        d.set_text_color(*LILAC)
        d.set_xy(MARGIN + 17, y)
        d.cell(CW - 17, 7, T(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        d.set_font("Helvetica", "", 8.6)
        d.set_text_color(*FAINT)
        d.set_xy(MARGIN + 17, d.get_y() - 0.6)
        d.cell(CW - 17, 5, T(blurb), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        d.set_draw_color(*PANEL_EDGE)
        d.set_line_width(0.15)
        d.line(MARGIN + 17, d.get_y() + 2.4, PAGE_W - MARGIN, d.get_y() + 2.4)
        d.ln(6.4)

    d.ln(4)
    callout(
        d, "About this document",
        ("Every technical claim here was checked against the code in ", "", MAUVE),
        ("pixieduster/", "C", LILAC),
        (" on 24 August 2026, and the measurements were re-run rather than quoted. "
         "Where the code and the brief disagreed, the code won.", "", MAUVE),
        tint=DIM_GOLD,
    )


def section_1(d: Doc) -> None:
    h1(d, "1", "What it is")

    para(d,
         ("PixieDuster clones a writing voice. ", "B", LILAC),
         "The Streamlit app you built does it from uploaded samples: you hand it essays, "
         "it profiles the author behind them, and it hands back a persona prompt. The CLI is "
         "the same brain with a different mouth and a different diet. It takes a git repo "
         "instead of an upload, and it writes ")
    para(d,
         ("AGENTS.md", "C", GOLD), (" or ", "", MAUVE), ("CLAUDE.md", "C", GOLD),
         (" instead of a download button, so the coding agent working in that repo writes "
          "prose in your voice rather than generic LLM house style.", "", MAUVE))

    para(d,
         "The insight it runs on is that most developers have already written a great deal "
         "in their own voice, and it is sitting in the repo: commit bodies, the README, "
         "docstrings, PR descriptions. Nobody has to upload anything. The material is "
         "already there, and it is more honest than an essay written to be sampled.")

    h2(d, "Web app and CLI, side by side")
    table(
        d,
        ["", "Streamlit app (app.py)", "PixieDuster CLI"],
        [
            ["Input", "Uploaded files (PDF, DOCX, TXT)", "A git repo: commits, docs, comments, PRs"],
            ["Interface", "Browser, HF Spaces", "Terminal, Rich TUI"],
            ["Interview", "Multiple-choice, in-page", "Arrow-key select, in-terminal"],
            ["Output", "A downloadable persona document", "AGENTS.md / CLAUDE.md written into the repo"],
            ["Shared", "prompts.py and core.py", "prompts.py and core.py"],
            ["Distribution", "A hosted Space", "uvx pixieduster clone, no install"],
        ],
        [0.14, 0.40, 0.46],
    )

    para(d,
         ("The sharing is real, not aspirational. ", "B", LILAC),
         ("app.py", "C", LILAC),
         (" was rewired to import from ", "", MAUVE), ("pixieduster.core", "C", LILAC),
         (" and ", "", MAUVE), ("pixieduster.prompts", "C", LILAC),
         (", so the rubric, the anti-AI template, the Benign Violation humour block and the "
          "Gemini call itself exist in exactly one place. A fix to the persona rubric lands "
          "in both products at once.", "", MAUVE))

    h2(d, "The four commands")
    table(
        d,
        ["Command", "What it does"],
        [
            ["`clone`", "Mine a repo, interview you, write the persona file. The main event."],
            ["`chat`", "A REPL against a persona file, so you can hear how it sounds before trusting it."],
            ["`diff <file>`", "Score a draft against the persona and list where the voice drifts."],
            ["`config`", "set-key, show, models, set-model. Key display is always masked."],
        ],
        [0.20, 0.80],
    )
    para(d,
         ("Both ", "", MAUVE), ("pixieduster", "C", LILAC), (" and the shorter ", "", MAUVE),
         ("pxd", "C", LILAC), (" are installed as entry points, and a fifth command, ", "", MAUVE),
         ("version", "C", LILAC), (", prints the version.", "", MAUVE))


def section_2(d: Doc) -> None:
    h1(d, "2", "The pipeline")

    para(d,
         ("clone", "CB", GOLD),
         (" runs nine steps. Everything before the safety gate is local; nothing has left the "
          "machine yet. The gate is the only door out, and ", "", MAUVE),
         ("--dry-run", "C", LILAC),
         (" ends the run right in front of it.", "", MAUVE))

    # ---- diagram ----------------------------------------------------------
    need(d, 108)
    y0 = d.get_y() + 2
    d.set_fill_color(*PURPLE)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.2)
    d.rect(MARGIN, y0, CW, 104, style="DF", round_corners=True, corner_radius=2)
    sparkles(d, 77, 70, MARGIN, y0, CW, 104)

    bw, bh = 33.0, 15.0
    gap = 4.2
    left = MARGIN + 6.0

    row1 = [
        ("resolve repo", "is_git_repo"),
        ("pick author", "git log %aE"),
        ("mine", "4 sources"),
        ("safety gate", "scan + cost"),
    ]
    row2 = [
        ("questions", "Gemini, JSON"),
        ("interview", "arrow-key"),
        ("humor slider", "0-10"),
        ("persona", "the rubric"),
    ]

    y_r1 = y0 + 12
    for i, (label, sub) in enumerate(row1):
        x = left + i * (bw + gap)
        edge = GOLD if label == "safety gate" else DIM_GOLD
        box(d, x, y_r1, bw, bh, label, sub=sub, edge=edge)
        if i:
            arrow(d, x - gap + 0.4, y_r1 + bh / 2, x - 0.8, y_r1 + bh / 2)

    # local / remote divider
    d.set_draw_color(*ROSE)
    d.set_line_width(0.3)
    d.set_dash_pattern(dash=1.4, gap=1.4)
    xdiv = left + 3 * (bw + gap) - gap / 2
    d.line(xdiv, y0 + 5, xdiv, y0 + 99)
    d.set_dash_pattern()
    d.set_font("Helvetica", "B", 6.2)
    d.set_text_color(*ROSE)
    d.set_xy(xdiv - 34, y0 + 1.4)
    d.cell(32, 3.4, T("ALL LOCAL"), align="R")
    d.set_xy(xdiv + 2, y0 + 1.4)
    d.cell(32, 3.4, T("NETWORK BEYOND HERE"), align="L")

    # elbow from gate down to row 2
    x_gate = left + 3 * (bw + gap) + bw / 2
    y_r2 = y_r1 + bh + 20
    d.set_draw_color(*GOLD)
    d.set_line_width(0.35)
    d.line(x_gate, y_r1 + bh, x_gate, y_r1 + bh + 9)
    d.line(x_gate, y_r1 + bh + 9, left + bw / 2, y_r1 + bh + 9)
    arrow(d, left + bw / 2, y_r1 + bh + 9, left + bw / 2, y_r2 - 0.8)

    for i, (label, sub) in enumerate(row2):
        x = left + i * (bw + gap)
        box(d, x, y_r2, bw, bh, label, sub=sub)
        if i:
            arrow(d, x - gap + 0.4, y_r2 + bh / 2, x - 0.8, y_r2 + bh / 2)

    # dry-run exit
    d.set_draw_color(*ROSE)
    arrow(d, x_gate - bw / 2 - 1.0, y_r1 + bh - 3.5, x_gate - bw / 2 - 12.0, y_r1 + bh + 4.0,
          colour=ROSE, dashed=True)
    d.set_font("Helvetica", "B", 6.2)
    d.set_text_color(*ROSE)
    d.set_xy(x_gate - bw / 2 - 54.0, y_r1 + bh + 3.0)
    d.cell(41.0, 3.4, T("--dry-run exits here"), align="R")

    # final row
    y_r3 = y_r2 + bh + 20
    x_last = left + 3 * (bw + gap) + bw / 2
    d.set_draw_color(*GOLD)
    d.line(x_last, y_r2 + bh, x_last, y_r2 + bh + 9)
    d.line(x_last, y_r2 + bh + 9, left + bw / 2, y_r2 + bh + 9)
    arrow(d, left + bw / 2, y_r2 + bh + 9, left + bw / 2, y_r3 - 0.8)

    box(d, left, y_r3, bw * 2 + gap, bh, "write AGENTS.md",
        sub="only cli.py touches your repo", edge=GOLD)
    arrow(d, left + bw * 2 + gap + 0.4, y_r3 + bh / 2, left + bw * 2 + gap + gap - 0.8, y_r3 + bh / 2)
    box(d, left + bw * 2 + gap * 2, y_r3, bw * 2 + gap, bh, "print certificate",
        sub="CERTIFICATE OF PERSONA", edge=GOLD)

    d.set_y(y0 + 108)
    caption(d, "clone: nine steps. The dashed rule is the trust boundary; the gate is the only crossing.")

    h2(d, "What each gate can stop")
    bullets(d, [
        [("No samples. ", "B", LILAC),
         "A repo of one-line 'fix' commits has nothing to clone, and the CLI says so and exits "
         "rather than sending an empty prompt."],
        [("No key. ", "B", LILAC),
         "If nothing resolves a key it offers a one-time save, and refuses non-interactively "
         "with exit code 2."],
        [("Model not available. ", "B", LILAC),
         ("_verify_model()", "C", LILAC),
         " checks the id against the live model list before anything expensive happens."],
        [("Findings. ", "B", LILAC),
         "Any secret found means an explicit confirmation, a redaction, or a stop."],
        [("Output exists. ", "B", LILAC),
         "An existing AGENTS.md is never silently overwritten; declining writes "
         "AGENTS-pixiedust.md instead."],
    ])


def section_3(d: Doc) -> None:
    h1(d, "3", "Module map")

    para(d,
         "Eight modules, 4,435 lines, plus 2,676 lines of tests. The shape is deliberate: one "
         "module knows about the network, one module knows about the filesystem of your repo, "
         "one module knows about your terminal, and none of them knows about the others.")

    table(
        d,
        ["Module", "Lines", "Job"],
        [
            ["`types.py`", "53", "Three dataclasses: Sample, Question, Finding. Imports nothing, so everyone can import it."],
            ["`prompts.py`", "139", "The rubric, the anti-AI template, the humour block, the question schema, the AGENTS.md header, the diff instruction. Text only."],
            ["`config.py`", "280", "Key resolution and the TOML config file. Hand-rolled TOML writing, because tomllib is read-only."],
            ["`core.py`", "462", "Everything that speaks to Gemini: call, chat, list models, generate questions, generate persona."],
            ["`cli.py`", "467", "Typer commands, the flow control, and the only writes to your repo."],
            ["`safety.py`", "795", "Secret detection, redaction, token and cost estimates, the dry-run report. Entirely offline."],
            ["`ui.py`", "1061", "Rich presentation: banner, dust, stages, arrow-key select, slider, certificate, tables."],
            ["`mining.py`", "1171", "Four miners, author attribution via blame, and the budget balancer."],
        ],
        [0.19, 0.10, 0.71],
        align=["L", "R", "L"],
    )

    # ---- dependency graph -------------------------------------------------
    need(d, 100)
    y0 = d.get_y()
    d.set_fill_color(*PURPLE)
    d.set_draw_color(*PANEL_EDGE)
    d.set_line_width(0.2)
    d.rect(MARGIN, y0, CW, 92, style="DF", round_corners=True, corner_radius=2)
    sparkles(d, 999, 55, MARGIN, y0, CW, 92)

    cx = PAGE_W / 2
    bw, bh = 36.0, 13.0

    # cli at the top
    box(d, cx - bw / 2, y0 + 7, bw, bh, "cli.py", sub="typer, flow control", edge=GOLD)

    mid_y = y0 + 40
    mids = [("mining.py", "reads the repo"), ("safety.py", "guards the send"),
            ("core.py", "talks to Gemini"), ("ui.py", "owns the terminal")]
    span = CW - 16
    step = span / 4
    for i, (label, sub) in enumerate(mids):
        x = MARGIN + 8 + i * step + (step - bw) / 2
        box(d, x, mid_y, bw, bh, label, sub=sub)
        arrow(d, cx, y0 + 7 + bh, x + bw / 2, mid_y - 0.8, colour=DIM_GOLD, width=0.3)

    low_y = y0 + 70
    lows = [("config.py", "key + settings"), ("prompts.py", "the text"), ("types.py", "the shapes")]
    lspan = CW - 40
    lstep = lspan / 3
    positions = {}
    for i, (label, sub) in enumerate(lows):
        x = MARGIN + 20 + i * lstep + (lstep - bw) / 2
        positions[label] = x + bw / 2
        box(d, x, low_y, bw, bh, label, sub=sub, edge=(120, 96, 160), text=MAUVE)

    # core -> prompts, everyone -> types, cli -> config
    core_x = MARGIN + 8 + 2 * step + step / 2
    arrow(d, core_x, mid_y + bh, positions["prompts.py"], low_y - 0.8, colour=(150, 122, 190), width=0.28)
    mining_x = MARGIN + 8 + 0 * step + step / 2
    safety_x = MARGIN + 8 + 1 * step + step / 2
    for sx in (mining_x, safety_x, core_x):
        arrow(d, sx, mid_y + bh, positions["types.py"], low_y - 0.8, colour=(150, 122, 190), width=0.28)
    gutter = MARGIN + 7.0
    d.set_draw_color(150, 122, 190)
    d.set_line_width(0.28)
    d.set_dash_pattern(dash=1.2, gap=1.2)
    d.line(cx - bw / 2, y0 + 7 + bh / 2, gutter, y0 + 7 + bh / 2)
    d.line(gutter, y0 + 7 + bh / 2, gutter, low_y + bh / 2)
    d.set_dash_pattern()
    arrow(d, gutter, low_y + bh / 2, positions["config.py"] - bw / 2 - 0.8, low_y + bh / 2,
          colour=(150, 122, 190), width=0.28, dashed=True)

    d.set_y(y0 + 96)
    caption(d, "Dependencies point downward only. Nothing in the middle row imports anything else in it.")

    h2(d, "Two invariants worth knowing")
    bullets(d, [
        [("cli.py is the only module that writes to your repo. ", "B", LILAC),
         "Every other module reads, computes, or prints. If a file appeared in your working "
         "tree, one line in cli.py put it there."],
        [("mining.py and safety.py make no network calls at all. ", "B", LILAC),
         ("mining.py", "C", LILAC),
         " shells out to git, and optionally to gh, which is the only subprocess with a socket "
         "behind it and is skipped entirely by --no-pr. safety.py touches nothing but strings."],
    ])


def section_4(d: Doc) -> None:
    h1(d, "4", "Mining")

    para(d,
         "Four sources, each with its own idea of what counts as your writing. All of them run "
         "over ", ("git ls-files", "C", LILAC),
         (", which means .gitignore is respected for free and no path outside the repository "
          "root is ever read.", "", MAUVE))

    table(
        d,
        ["Source", "How", "Share"],
        [
            ["commits", "git log --format=%B: full bodies, not subjects. Merges, bots, dependency bumps and version noise dropped; anything under 40 characters after cleaning dropped.", "40%"],
            ["docs", "Tracked .md / .rst / .txt. README, CONTRIBUTING and docs/** first. Code fences, badges, link-reference blocks and HTML stripped; CHANGELOG and LICENSE skipped.", "25%"],
            ["comments", "Docstrings via ast, plus comment runs of two or more lines. Licence headers, shebangs, pragmas, type stubs and generated files skipped.", "20%"],
            ["PRs", "gh pr list --json for bodies and review comments. If gh is missing or unauthenticated it returns an empty list silently, and never blocks.", "15%"],
        ],
        [0.16, 0.72, 0.12],
        align=["L", "L", "R"],
    )

    h2(d, "Why commit bodies, not subjects")
    para(d,
         "A subject line is a label. A body is prose: it argues, it hedges, it explains why. "
         "That is where a voice lives, so ", ("mine_commits", "C", LILAC),
         (" reads full bodies and throws away anything too short to be prose.", "", MAUVE))

    h2(d, "Stripping the co-author")
    para(d,
         "Commit messages written with a coding agent carry trailers: ",
         ("Co-Authored-By", "C", LILAC), (", ", "", MAUVE), ("Claude-Session", "C", LILAC),
         (", and a 'Generated with Claude Code' line. Left in, they are the loudest, most "
          "repetitive text in the corpus, and the model would dutifully learn them. You would "
          "clone Claude instead of yourself. So they are stripped, along with the usual "
          "Signed-off-by / Reviewed-by family and a generic ", "", MAUVE),
         ("<Something>-by:", "C", LILAC), (" trailer pattern.", "", MAUVE))

    h2(d, "Comments via tokenize, not regex")
    para(d,
         "This one is your repo's fault, and it is a good bug. ", ("app.py", "C", LILAC),
         (" contains a triple-quoted prompt string with ", "", MAUVE),
         ("## Core Directives", "C", LILAC),
         (" inside it. A naive line scan for lines starting with # would harvest that as your "
          "own prose - you would be cloning the voice of a prompt you wrote for the model, not "
          "the voice you write in. Running the source through ", "", MAUVE),
         ("tokenize", "C", LILAC),
         (" means only real COMMENT tokens are seen, and string contents are invisible by "
          "construction. The naive scanner survives only as a fallback for files that do not "
          "tokenize.", "", MAUVE))

    code(d, [
        "# _python_comment_runs: only real COMMENT tokens count",
        "for tok in tokenize.generate_tokens(io.StringIO(source).readline):",
        "    if tok.type != tokenize.COMMENT:",
        "        continue",
        "    row, col = tok.start",
        "    if lines[row - 1][:col].strip():",
        "        continue        # trailing comment on a code line, not prose",
    ], caption="pixieduster/mining.py")

    h2(d, "Sharing out a limited budget")
    para(d,
         ("You cannot send a whole repository to the AI - too much text, and you pay for "
          "every word of it. So ", "", MAUVE), ("mine_all", "C", LILAC),
         (" takes about 180,000 characters, roughly 45 pages, and stops.", "", MAUVE))
    para(d,
         ("The catch is which 45 pages. If it simply took the first 180,000 characters and "
          "you had 400 commits, the commits would eat all of it, and the AI would only ever "
          "see commit messages - short, technical, typed in a hurry. You would get a persona "
          "that sounds like a changelog. So room is reserved in advance: 40% commits, 25% "
          "docs, 20% code comments, 15% pull requests. Four different moods of the same "
          "person.", "", MAUVE))
    para(d, ("Two adjustments then keep it from wasting space:", "", MAUVE))
    bullets(d, [
        [("Leftovers get handed on. ", "B", LILAC),
         ("If a group does not need all its space, the rest is split among the groups that "
          "are still short. This repository has no pull requests, so that 15% would sit "
          "empty - instead it goes to the commits and the README.", "", MAUVE)],
        [("Biggest goes first. ", "B", LILAC),
         ("If a group has too much, the longest items are dropped before the short ones. "
          "Five ordinary pieces show your range better than one enormous document.",
          "", MAUVE)],
    ])

    budget_diagram(d)

    h2(d, "Working out who wrote what")
    para(d,
         ("This only matters on a repository with several people on it. Git records who "
          "wrote each commit, so filtering those by author is easy. A README is different - "
          "it is just a file sitting there, with nothing on it saying who wrote which part. "
          "Left alone, you would get your commits blended with everybody's README.",
          "", MAUVE))
    para(d,
         ("So it uses ", "", MAUVE), ("git blame", "C", LILAC),
         (", which reports who wrote each individual line, and keeps only the target's "
          "lines. Blame is slow, so it is bounded: at most 40 files, and 15 seconds for the "
          "whole phase. A cheaper ", "", MAUVE), ("git log --follow", "C", LILAC),
         (" pass runs first to drop files the person never touched at all, and if blame "
          "fails or runs out of time the code falls back to that cheaper answer instead of "
          "hanging. A block of comments has to be at least 60% theirs to count.",
          "", MAUVE))

    callout(
        d, "Measured on this repository",
        ("14 commits in history, 11 survive filtering. ", "B", LILAC),
        ("The three that were dropped - ", "", MAUVE),
        ("'Fix NameError: add missing time import'", "C", MAUVE),
        (", ", "", MAUVE), ("'Fix Pyodide import error for fpdf2'", "C", MAUVE),
        (" and ", "", MAUVE), ("'Initial commit (Secrets redacted)'", "C", MAUVE),
        (" - were all under the 40-character floor, not noise-matched. Filtered to "
         "me@gretchenboria.com the full mine returns 13 samples: 11 commits, 1 doc, "
         "1 comment, 0 PRs. Every commit in this repo is yours, so the author filter "
         "changes nothing here.", "", MAUVE),
    )


def section_5(d: Doc) -> None:
    h1(d, "5", "Safety")

    para(d,
         ("This is the section that matters. ", "B", GOLD),
         ("The whole point of the tool is that your repository's text goes to a third party. "
          "Google sees your commit bodies, your README and your docstrings. That is a "
          "reasonable trade for what you get back, but it is only reasonable if it is visible "
          "and if credentials do not go with it. ", "", MAUVE),
         ("safety.py", "C", LILAC),
         (" is the last thing standing in that doorway, and it makes no network calls of any "
          "kind.", "", MAUVE))

    h2(d, "22 rules, priority-ordered")
    para(d,
         "The rules are a list, not a set, and the order is load-bearing. Rules are tried in "
         "sequence and the first to claim a span of text wins, so a vendor-specific rule "
         "always beats a generic one and each secret is reported exactly once. A Google key "
         "inside ", ("GOOGLE_KEY=AIza...", "C", LILAC),
         (" is reported as google-api-key, not as a generic .env value.", "", MAUVE))

    table(
        d,
        ["Rule", "Shape", "Sev"],
        [
            ["private-key-pem-block", "The whole BEGIN/END block, so the body is scrubbed and not just the header. A second rule catches a truncated header-only paste.", "high"],
            ["aws-access-key-id", "The fixed 4-char type prefixes (AKIA, ASIA, AROA, ...) plus 16 base32 chars.", "high"],
            ["aws-secret-access-key", "40 base64 chars, but only next to an AWS-ish key name. Matching bare 40-char base64 would flag every git hash.", "high"],
            ["google-api-key", "AIza + 35. This is the key the CLI itself uses, so it must never travel back out inside a sample.", "high"],
            ["anthropic-api-key", "sk-ant-... Listed before the OpenAI rule.", "high"],
            ["openai-api-key", "sk- with a negative lookahead for ant-, so Anthropic keys are not swallowed here.", "high"],
            ["github-token", "ghp_ / gho_ / ghu_ / ghs_ / ghr_, plus github_pat_ for fine-grained PATs.", "high"],
            ["slack-token", "xox[baprse]- prefixes, plus a separate rule for hooks.slack.com webhook URLs.", "high"],
            ["stripe-secret-key", "sk_live_ and rk_live_ only. sk_test_ is not worth alarming over.", "high"],
            ["jwt", "Two base64url segments that both start eyJ, plus a signature that may be empty for alg=none.", "high"],
            ["connection-string-credentials", "postgres:// mysql:// mongodb+srv:// redis:// amqp:// and friends, with user:pass inline.", "high"],
            ["generic-secret-assignment", "password / token / api_key / client_secret = <value>. The workhorse, and the noisy one.", "med"],
            ["dotenv-high-entropy-value", "SCREAMING_SNAKE=<32+ chars of key-ish material> alone on a line.", "med"],
        ],
        [0.26, 0.63, 0.11],
        align=["L", "L", "R"],
    )
    para(d,
         ("Thirteen of the twenty-two are shown; the rest are the same idea applied to Google "
          "OAuth client secrets, npm, PyPI, SendGrid, Hugging Face and Authorization headers. "
          "Twenty are high severity, two are medium.", "", FAINT), size=8.4)

    h2(d, "Keeping false positives survivable")
    para(d,
         "The detector is biased toward recall, because a missed secret is a leak and a false "
         "positive is only an extra confirmation prompt. That bias is what makes the two "
         "generic rules noisy, so they are paired with structural filters that run after the "
         "regex matches:")
    bullets(d, [
        [("Placeholder detection. ", "B", LILAC),
         "your-key-here, changeme, xxxx, TODO - matched as whole tokens inside the value, so a "
         "real key that happens to contain 'fake' as a substring is not excused."],
        [("Code-identifier shape. ", "B", LILAC),
         ("Optional[str]", "C", LILAC), (", ", "", MAUVE), ("get_password()", "C", LILAC),
         (", ", "", MAUVE), ("os.environ['X']", "C", LILAC),
         ", settings.SECRET_KEY. snake_case, camelCase, CONSTANT_CASE and dotted attribute "
         "access are all rejected: a real credential essentially never has that shape."],
        [("Template syntax. ", "B", LILAC),
         ("${...}", "C", LILAC), (", ", "", MAUVE), ("{{...}}", "C", LILAC),
         ", and anything starting with < { $ % & ! @ ? is interpolation, not a literal."],
        [("A Shannon entropy floor. ", "B", LILAC),
         "3.0 bits per character for a generic assignment, 3.5 for a .env value. English words "
         "and identifiers sit below that; random credential material sits above it."],
        [("Paths and URLs. ", "B", LILAC),
         "A value starting with / ./ ~/ http:// is a location, not a secret."],
    ])

    h2(d, "Measured, not asserted")
    callout(
        d, "Benchmarks",
        ("Zero false positives on a curated corpus of 39 innocent strings. ", "B", LILAC),
        ("Scanning 1,243 real .py files - 16.5 MB from the CLI's own virtualenv - produced "
         "exactly 3 findings: two generic-secret-assignment hits inside a numerical library's "
         "test data and one connection-string match in a URL-parsing test. All three are "
         "dismissible at a glance. The scan ran at roughly 5.4 MB/s with no catastrophic "
         "backtracking, which is what you want from a gate that runs before every send.",
         "", MAUVE),
    )

    h2(d, "One pass, two outputs")
    para(d,
         ("scan()", "C", LILAC), (" and ", "", MAUVE), ("redact()", "C", LILAC),
         (" share a single ", "", MAUVE), ("_collect()", "C", LILAC),
         (" pass. That is not an optimisation, it is a correctness property: if they had "
          "separate implementations they could disagree, and the interesting way for them to "
          "disagree is for the report to say 'clean' while the redactor leaves something in. "
          "One pass makes that impossible.", "", MAUVE))
    para(d,
         "On top of that there is a belt-and-braces check. Every excerpt that goes into a "
         "Finding is run through ", ("_leaks()", "C", LILAC),
         (", which slides an 8-character window over the original secret and asks whether any "
          "distinctive run of it survived in the excerpt. If one did, the excerpt is thrown "
          "away and replaced with a bare marker. A Finding is safe to print, log, or paste "
          "into a GitHub issue, even if a rule elsewhere is buggy.", "", MAUVE))

    scan_diagram(d)

    callout(
        d, "If you ever extend this",
        ("SECRET_RULES is not the detector. ", "B", GOLD),
        ("The entropy floor, the placeholder list and the identifier-shape rejection live "
         "outside the rule list in a separate validators table, keyed by rule name. Code that "
         "reads SECRET_RULES and re-implements matching from the regexes gets the recall "
         "without any of the precision, and will flag ", "", MAUVE),
        ("Optional[str]", "C", LILAC),
        (" as a credential. Always go through ", "", MAUVE), ("scan()", "C", LILAC),
        (" and ", "", MAUVE), ("redact()", "C", LILAC), (".", "", MAUVE),
        tint=GOLD,
    )

    h2(d, "The three ways out")
    bullets(d, [
        [("--dry-run", "CB", GOLD),
         " prints the exact payload - every sample with its kind, origin and token count, the "
         "totals, the cost estimate and every finding - then exits. No network request is made. "
         "The report is plain text with no ANSI, so it pipes."],
        [("--scrub", "CB", GOLD),
         " replaces every match with ", ("<REDACTED:rule>", "C", LILAC),
         " and sends the redacted text instead of asking."],
        [("Confirmation. ", "B", LILAC),
         "A cost estimate and an explicit prompt precede every send. With findings present the "
         "prompt defaults to No. ", ("--yes", "C", LILAC), " skips it for scripted use."],
    ])

    code(d, [
        "$ pixieduster clone --dry-run",
        "PIXIEDUSTER DRY RUN",
        "============================================================",
        "Nothing below has been sent anywhere. This is what *would* be sent.",
        "",
        "SAMPLES (13)",
        "    1. [commit] git log 0c7d3f1  (61 tokens)  author=me@gretchenboria.com",
        "",
        "TOTALS",
        "  estimated input tokens:  4812",
        "  estimated cost (gemini-3.6-flash): $0.0036 (input only, estimate)",
        "",
        "SECRET SCAN (0 finding(s))",
        "  No potential secrets detected.",
        "  NOTE: detection is best-effort. Review the sample list above.",
        "",
        "END OF DRY RUN. No network request was made.",
    ], caption="the payload, before any of it leaves")


def section_6(d: Doc) -> None:
    h1(d, "6", "API key handling")

    para(d,
         "PixieDuster is bring-your-own-key, and setup is a one-time thing. The key is "
         "resolved in a fixed order, first hit wins:")

    # resolution chain diagram
    need(d, 40)
    y0 = d.get_y()
    steps = [("--api-key", "the flag"), ("GEMINI_API_KEY", "environment"),
             (".env", "in the cwd"), ("config.toml", "~/.config/pixieduster")]
    bw = (CW - 3 * 6.0) / 4
    for i, (label, sub) in enumerate(steps):
        x = MARGIN + i * (bw + 6.0)
        box(d, x, y0, bw, 15, label, sub=sub, edge=GOLD if i == 0 else DIM_GOLD)
        if i:
            arrow(d, x - 5.6, y0 + 7.5, x - 0.8, y0 + 7.5)
    d.set_y(y0 + 20)
    caption(d, "Falls through left to right. If nothing hits, clone offers a one-time save and then refuses.")

    h2(d, "Why the CLI cannot ship with a key")
    para(d,
         "Two reasons, and neither has a workaround. First, a key embedded in a published CLI "
         "is not secret: the wheel is a zip file, and anyone who runs ",
         ("strings", "C", LILAC),
         (" over it has your credential in about four seconds. Obfuscation only changes how "
          "long the four seconds take. Second, and worse, the spend is uncapped and lands on "
          "your card - every user of the tool, forever, billed to you, with no per-user limit "
          "you could enforce. BYOK is not a cop-out here; it is the only design that does not "
          "end in a surprise invoice.", "", MAUVE))

    h2(d, "Four specifics that are actually load-bearing")
    bullets(d, [
        [("The key goes in a header, never a URL. ", "B", LILAC),
         "It is sent as ", ("x-goog-api-key", "C", LILAC),
         " rather than as a ", ("?key=", "C", LILAC),
         " query parameter. This is a direct fix to something the web app does: an API error "
         "that echoes the request URL back to you puts your key in the error text, in the "
         "traceback, and in whatever issue you paste it into."],
        [("Writes are atomic and never briefly world-readable. ", "B", LILAC),
         ("save_api_key", "C", LILAC), " does mkdir 0700, then ",
         ("os.open(..., 0o600)", "C", LILAC),
         " to a temp file, then ", ("os.replace", "C", LILAC),
         ". There is no window in which the key exists at default permissions, and other "
         "settings already in the file are preserved rather than clobbered."],
        [("The key never enters os.environ. ", "B", LILAC),
         ("resolve_api_key", "C", LILAC), " reads .env with ", ("dotenv_values", "C", LILAC),
         " rather than ", ("load_dotenv", "C", LILAC),
         ". load_dotenv would push the key into the process environment, where any subprocess "
         "inherits it and any crash dump captures it. Because the real environment is checked "
         "first anyway, this is behaviourally identical to load_dotenv(override=False) and "
         "strictly safer."],
        [("Errors are safe to paste. ", "B", LILAC),
         ("GeminiError", "C", LILAC), " passes every message through a sanitizer that strips ",
         ("?key=", "C", LILAC), " and ", ("&api_key=", "C", LILAC),
         " parameters, redacts anything shaped like ", ("AIza...", "C", LILAC),
         ", and - when the live key is known - removes that exact string too. Three "
         "independent nets, because the interesting failure is the one you did not predict."],
    ])

    code(d, [
        "$ pixieduster config show",
        "config file : /Users/you/.config/pixieduster/config.toml",
        "key source  : dotenv",
        "key         : AIza...4f21",
        "model       : gemini-3.6-flash",
    ], caption="config show never prints the middle of the key")

    para(d,
         "The masking helper shows the first four and last four characters and nothing "
         "between, and for a key of eight characters or fewer it degrades to showing almost "
         "nothing rather than most of it.")


def section_7(d: Doc) -> None:
    h1(d, "7", "The TUI")

    para(d,
         "Rich and the standard library. No Textual, no readchar, no questionary. The whole "
         "terminal layer is one module with no dependency beyond what the CLI already needs, "
         "and it carries the web app's identity across: gold on deep purple, the same six "
         "processing stages, the same certificate.")

    bullets(d, [
        [("A gradient ASCII wordmark. ", "B", LILAC),
         "PIXIEDUSTER rendered gold to purple, sized to fit 80 columns."],
        [("Falling pixie dust. ", "B", LILAC),
         "A Rich ", ("Live", "C", LILAC),
         " region updated at 10fps from a daemon thread, drifting the glyphs the web app uses. "
         "Transient, so it leaves no trace when it exits, and torn down cleanly on Ctrl-C."],
        [("A stage list. ", "B", LILAC),
         "The same six steps - inspecting samples, formulating questions, Big Five, LIWC, "
         "cognitive style, sociolinguistics - each with a spinner that ticks to a gold "
         "checkmark as the next one starts."],
        [("Arrow-key select and a gold slider. ", "B", LILAC),
         "Single-select for the interview questions, and a ", ("---o---", "C", LILAC),
         " bar for the humour level, both driven by raw key reads."],
        [("The certificate. ", "B", LILAC),
         "A double-bordered panel: CERTIFICATE OF PERSONA in letter-spaced gold, 'Officially "
         "cloned for: NAME', the rendered markdown body between gold rules, and 'Authorized by "
         "PixieDuster' at the foot. A direct port of the web app's certificate."],
    ])

    h2(d, "Two bugs worth remembering")
    callout(
        d, "1. Buffering ate every arrow key",
        ("Reading raw keys with ", "", MAUVE), ("sys.stdin.read(1)", "C", LILAC),
        (" silently broke all four arrow keys. An arrow arrives as an escape sequence - ESC, "
         "then [, then A - and Python's buffered TextIOWrapper swallows the tail, so the code "
         "saw a bare ESC and interpreted it as 'cancel'. Nothing errored; the arrows simply "
         "did nothing. The fix is a thin unbuffered wrapper around ", "", MAUVE),
        ("os.read(fd, n)", "C", LILAC),
        (", with ", "", MAUVE), ("select", "C", LILAC),
        (" used to decide whether more of the sequence is pending. The decoder itself is a "
         "pure function, so it is tested without a TTY at all.", "", MAUVE),
        tint=ROSE,
    )
    callout(
        d, "2. Rich has exactly one Live region",
        ("dust()", "CB", LILAC),
        (" and ", "", MAUVE), ("stages()", "CB", LILAC),
        (" both need it, so they must never nest. The rule the code follows is simple: dust "
         "runs during ", "", MAUVE), ("chat", "C", LILAC),
         (", stages run during ", "", MAUVE), ("clone", "C", LILAC),
        (". That was a convention in a comment, which is how it would have come back. It is "
         "now enforced: each of the four widgets claims the region through a guard, and "
         "nesting any two raises ", "", MAUVE), ("LiveConflictError", "CB", LILAC),
        (" naming both, instead of silently corrupting the display. Eight tests cover it, "
         "including one that reads the source of ", "", MAUVE), ("clone", "C", LILAC),
        (", ", "", MAUVE), ("chat", "C", LILAC), (" and ", "", MAUVE), ("diff", "C", LILAC),
        (" and fails if any of them ever uses both.", "", MAUVE),
        tint=ROSE,
    )

    h2(d, "Degrading properly")
    para(d,
         "Decoration is suppressed when any of three conditions holds: ",
         ("ui.PLAIN", "C", LILAC), (" is set by ", "", MAUVE), ("--plain", "C", LILAC),
         (", ", "", MAUVE), ("NO_COLOR", "C", LILAC),
         (" is in the environment, or stdout is not a TTY. The third is what makes CI and "
          "piping work without anyone remembering a flag: piping the output produces zero "
          "ANSI bytes, the stage list becomes one plain line per step, arrow-key select "
          "becomes numbered input, and the certificate becomes a rule-and-centre-text block.",
          "", MAUVE))


def section_8(d: Doc) -> None:
    h1(d, "8", "Tech stack")

    table(
        d,
        ["Layer", "Choice", "Why"],
        [
            ["Language", "Python >= 3.11", "tomllib in the stdlib; matches the web app."],
            ["TUI", "rich >= 13.7", "Live regions, panels, tables, markdown rendering. No Textual."],
            ["CLI", "typer >= 0.12", "Type-hint-driven commands and flags."],
            ["HTTP", "requests >= 2.31", "Gemini REST v1beta, called directly."],
            ["Config", "python-dotenv >= 1.0", "Reading .env without polluting os.environ."],
            ["Optional (web)", "streamlit, fpdf2", "The Streamlit app and its PDF export, behind the 'web' extra."],
            ["Dev", "pytest >= 8.0", "412 tests, all offline."],
            ["Build", "hatchling", "The build backend declared in pyproject.toml."],
            ["Entry points", "pixieduster, pxd", "Both installed; pxd is the short alias."],
            ["Distribution", "uvx pixieduster clone", "Runs with no install at all."],
            ["State", "one TOML file", "~/.config/pixieduster/config.toml. Nothing else persists."],
        ],
        [0.19, 0.26, 0.55],
    )

    h2(d, "No SDK")
    para(d,
         "Gemini is called over plain REST with ", ("requests", "C", LILAC),
         (" rather than through google-genai. The API surface actually used is small - "
          "generateContent, and a GET of the model list - and vendoring an SDK for that would "
          "add a dependency tree, a release cadence and a set of transitive pins to a tool "
          "whose entire runtime footprint is currently four packages. Four dependencies is "
          "something a person can audit before pointing the thing at a private repo.",
          "", MAUVE))

    code(d, [
        "# what the whole API surface amounts to",
        "POST {API_BASE}/models/{model}:generateContent",
        "     headers: {'x-goog-api-key': key}",
        "     body:    {'contents': [...], 'generationConfig': {...}}",
        "",
        "GET  {API_BASE}/models          # used only to verify the model id",
    ], caption="pixieduster/core.py")

    h2(d, "Statelessness")
    para(d,
         "There is no database, no cache directory, no history file and no telemetry. The one "
         "piece of persistent state is the TOML config: your key under ",
         ("[auth]", "C", LILAC), (", and a small ", "", MAUVE), ("[settings]", "C", LILAC),
         (" table holding your chosen model and the id of the last model verified against the "
          "live list. Deleting that file returns the tool to first-run.", "", MAUVE))


def section_9(d: Doc) -> None:
    h1(d, "9", "How the swarm built it")

    para(d,
         "Five agents worked in parallel against a single file, ", ("CONTRACT.md", "C", LILAC),
         (", written before any implementation started. The contract pre-declared every module "
          "signature - argument names, return types, and the exact behaviour of the tricky "
          "cases - and assigned disjoint file ownership, so no two agents could write to the "
          "same file. ", "", MAUVE), ("types.py", "C", LILAC),
         (" was written first and alone, because everything else imports it.", "", MAUVE))

    table(
        d,
        ["Agent", "Owns", "Depends on"],
        [
            ["agent-core", "core.py, prompts.py, config.py, types.py", "nothing"],
            ["agent-mining", "mining.py", "types only"],
            ["agent-safety", "safety.py", "types only"],
            ["agent-ui", "ui.py", "nothing"],
            ["integrator", "cli.py, pyproject.toml, __init__.py", "all of the above"],
        ],
        [0.22, 0.48, 0.30],
    )

    para(d,
         "Each agent wrote its own tests, and every test had to pass offline with ",
         ("requests.post", "C", LILAC),
         (" mocked - never against the real API. The result is 412 tests in 2,744 lines, "
          "running in under three seconds.", "", MAUVE))

    callout(
        d, "The contract needed amending in flight",
        ("It is worth being honest that the contract was not perfect. ", "B", LILAC),
        ("As specified, ", "", MAUVE), ("mine_all", "C", LILAC),
        (" took no ", "", MAUVE), ("prs", "C", LILAC),
        (" flag, and only commits were author-filtered - docs and comments were to be taken "
          "wholesale. The mining agent pointed out that this dilutes the persona badly on any "
          "repo with more than one contributor: you ask to clone one person and get the "
          "README of whoever wrote it. Two amendments followed: author threading through "
          "mine_docs and mine_comments with git blame attribution, and a prs flag so --no-pr "
          "could skip the only subprocess with a network behind it. A pre-declared contract "
          "is what made the disagreement cheap - it was a signature change discussed once, "
          "not four modules discovering an incompatibility at integration time.", "", MAUVE),
        tint=DIM_GOLD,
    )

    h2(d, "What the shape bought")
    bullets(d, [
        [("No merge conflicts. ", "B", LILAC),
         "Disjoint ownership meant five agents wrote 4,435 lines concurrently without once "
         "touching the same file."],
        [("Testability by construction. ", "B", LILAC),
         "Because safety and mining were forbidden from making network calls, their tests are "
         "trivially offline and fast."],
        [("An integrator that only wires. ", "B", LILAC),
         "cli.py is 467 lines because the hard parts were already done and tested behind "
         "stable signatures."],
    ])


def section_10(d: Doc) -> None:
    h1(d, "9", "Open items")

    para(d,
         ("Four things to know. ", "B", ROSE),
         ("The model-id question and the key problem are both resolved.", "", MAUVE))

    h2(d, "1. Resolved: the default model is real")
    para(d,
         ("gemini-3.6-flash", "C", GOLD),
         (" was doubted during the build. It is genuine - confirmed against a live model "
          "list of 50 on 24 August 2026. No action needed. ", "", MAUVE),
         ("_verify_model()", "C", LILAC),
         (" still checks the id on first use and falls back to the best available flash "
          "model if a future id goes stale, caching the answer so it costs one GET, once.",
          "", MAUVE))

    h2(d, "2. Resolved: two keys, one dead")
    para(d,
         ("A revoked key exported from ", "", MAUVE), ("~/.zshrc", "C", LILAC),
         (" was shadowing the working key in ", "", MAUVE), (".env", "C", LILAC),
         (", because resolution checks the environment before ", "", MAUVE),
         (".env", "C", LILAC),
         (". The dead export is now commented out and the working key verified. "
          "The general lesson survives the fix: when a key fails, check ", "", MAUVE),
         ("config show", "C", LILAC),
         (" to see which of the four sources actually won.", "", MAUVE))
    callout(
        d, "A gemini key is not always AIza",
        ("Both ", "", MAUVE), ("AIza", "C", LILAC), ("-prefixed keys and longer ", "", MAUVE),
        ("AQ.A", "C", LILAC),
        ("-prefixed keys are valid. Do not judge a key by its prefix.", "", MAUVE),
        tint=DIM_GOLD,
    )

    h2(d, "3. Cost estimates are approximate, and sometimes absent")
    para(d,
         ("estimate_cost", "C", LILAC),
         (" returns None rather than a guess for any unpriced model, so callers must render "
          "'cost unknown' rather than $0.00. Output tokens cannot be known before the call, "
          "so the dry-run figure is input-only, and token counts are a len/4 approximation - "
          "fine for budgeting, wrong for billing. The promotional $0.75 / $3.75 rate for the "
          "3.x flash models doubles after 31 December 2026, which the table does not model, "
          "so later estimates are a floor.", "", MAUVE))

    h2(d, "4. Secret detection is best-effort")
    para(d,
         "It is pattern matching. It will not catch a credential with no recognisable shape, "
         "a secret split across lines, or something encoded before it was committed. The "
         "benchmarks in section 5 measure precision on real code, not recall against a "
         "determined leak. Review the ", ("--dry-run", "C", LILAC),
         (" output before pointing this at a sensitive repository.", "", MAUVE))

    d.ln(2)
    need(d, 34)
    y = d.get_y()
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.4)
    d.line(MARGIN + 40, y, PAGE_W - MARGIN - 40, y)
    sparkles(d, 4242, 30, MARGIN + 30, y + 2, CW - 60, 20)
    d.set_font("Helvetica", "I", 9)
    d.set_text_color(*FAINT)
    d.set_xy(MARGIN, y + 8)
    d.multi_cell(CW, 5, T("Run clone --dry-run once to see what your own repo gives up, "
                          "and then let it write."), align="C")


# --------------------------------------------------------------------------


def build() -> Path:
    d = Doc()
    cover(d)
    start_here(d)
    contents(d)
    section_1(d)
    section_2(d)
    section_3(d)
    section_4(d)
    section_5(d)
    section_6(d)
    section_7(d)
    section_8(d)
    section_10(d)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.output(str(OUT))
    return OUT


if __name__ == "__main__":
    path = build()
    size = path.stat().st_size
    print(f"wrote {path}  ({size:,} bytes)")
