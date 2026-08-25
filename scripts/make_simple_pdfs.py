"""Two plain documents: a one-page picture, and a quick start.

    .venv-cli/bin/python scripts/make_simple_pdfs.py

Deliberately separate from make_pdf.py, which builds the long reference doc.
These two are meant to be readable by someone who has never seen the tool.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LOGO = ROOT / "logo.png"

# Palette, lifted from the app.py CSS block.
GOLD = (255, 215, 0)
DIM_GOLD = (218, 165, 32)
LILAC = (226, 209, 249)
MAUVE = (209, 196, 233)
PURPLE = (43, 24, 69)
DEEP = (15, 8, 28)
PANEL = (33, 19, 55)
FAINT = (138, 125, 163)
GREEN = (126, 217, 160)
ROSE = (233, 140, 160)

PAGE_W, PAGE_H = 210.0, 297.0
MARGIN = 18.0
CW = PAGE_W - 2 * MARGIN


def T(text: str) -> str:
    """Core PDF fonts are latin-1 only. Replace what we actually use."""
    for bad, good in (
        ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
        ("-", "-"), ("-", "-"), ("…", "..."), ("→", "->"),
        (" ", " "),
    ):
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


class Doc(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(False)
        self.set_margins(MARGIN, MARGIN, MARGIN)

    def bg(self) -> None:
        """Paint the deep purple ground over the whole page."""
        self.set_fill_color(*DEEP)
        self.rect(0, 0, PAGE_W, PAGE_H, style="F")


def panel(d: Doc, x, y, w, h, *, fill=PANEL, edge=DIM_GOLD, radius=2.5, lw=0.4) -> None:
    d.set_fill_color(*fill)
    d.set_draw_color(*edge)
    d.set_line_width(lw)
    d.rect(x, y, w, h, style="DF", round_corners=True, corner_radius=radius)


def text(d: Doc, x, y, w, s, *, size=10, style="", color=MAUVE, align="L", lh=5.0) -> float:
    d.set_font("Helvetica", style, size)
    d.set_text_color(*color)
    d.set_xy(x, y)
    d.multi_cell(w, lh, T(s), align=align)
    return d.get_y()


def mono(d: Doc, x, y, w, s, *, size=9.5, color=GOLD, align="L") -> None:
    d.set_font("Courier", "", size)
    d.set_text_color(*color)
    d.set_xy(x, y)
    d.multi_cell(w, 4.8, T(s), align=align)


def down_arrow(d: Doc, x, y1, y2, *, color=DIM_GOLD) -> None:
    d.set_draw_color(*color)
    d.set_fill_color(*color)
    d.set_line_width(0.6)
    d.line(x, y1, x, y2 - 2.2)
    d.polygon([(x - 2.0, y2 - 2.6), (x + 2.0, y2 - 2.6), (x, y2)], style="F")


def sparkles(d: Doc, seed: int, count: int, x0, y0, w, h) -> None:
    import random

    r = random.Random(seed)
    for _ in range(count):
        x, y = x0 + r.random() * w, y0 + r.random() * h
        size = r.choice([0.35, 0.5, 0.7])
        d.set_fill_color(*(GOLD if r.random() < 0.6 else LILAC))
        d.ellipse(x, y, size, size, style="F")


# ---------------------------------------------------------------------------
# 1. The picture
# ---------------------------------------------------------------------------

def diagram() -> Path:
    d = Doc()
    d.add_page()
    d.bg()
    sparkles(d, 7, 90, 0, 0, PAGE_W, PAGE_H)

    if LOGO.exists():
        d.image(str(LOGO), x=PAGE_W / 2 - 11, y=12, w=22)

    text(d, 0, 38, PAGE_W, "What PixieDuster does", size=22, style="B",
         color=GOLD, align="C", lh=9)
    text(d, MARGIN, 50, CW,
         "Give an AI a real identity to be - a character you invent, or your own voice.",
         size=11.5, color=LILAC, align="C", lh=6)

    cx = PAGE_W / 2
    y = 66.0

    # --- step 1 -----------------------------------------------------------
    h1 = 45.0
    panel(d, MARGIN, y, CW, h1)
    text(d, MARGIN + 8, y + 6, CW - 16, "1.  Tell it who to be. Three ways.",
         size=12, style="B", color=GOLD, lh=6)
    text(d, MARGIN + 8, y + 14.5, CW - 16,
         "Any identity you need to be true to. Mix them if you like.",
         size=9.5, color=FAINT, lh=4.6)

    ways = [
        ("Invent a character", '--describe "a friendly desktop\nrobot with great humor"'),
        ("From writing samples", "--from ./essays\n(text, PDFs, screenshots)"),
        ("From a git repo", "--repo .\n(clone your own voice)"),
    ]
    bw = (CW - 16 - 6) / 3
    for i, (label, how) in enumerate(ways):
        bx = MARGIN + 8 + i * (bw + 3)
        panel(d, bx, y + 22, bw, 17, fill=PURPLE, edge=DIM_GOLD, radius=1.8, lw=0.3)
        text(d, bx, y + 24.5, bw, label, size=8.2, style="B", color=LILAC,
             align="C", lh=3.8)
        mono(d, bx + 2, y + 29.5, bw - 4, how, size=5.6, color=GOLD, align="C")

    y += h1
    down_arrow(d, cx, y + 2, y + 9)
    y += 10

    # --- step 2 -----------------------------------------------------------
    h2 = 30.0
    panel(d, MARGIN, y, CW, h2)
    text(d, MARGIN + 8, y + 6, CW - 16, "2.  It asks you three quick questions",
         size=12, style="B", color=GOLD, lh=6)
    text(d, MARGIN + 8, y + 15, CW - 16,
         "Things your writing cannot reveal on its own. You answer with the arrow keys, "
         "and set how funny it should be with a slider.",
         size=9.5, color=MAUVE, lh=4.6)

    y += h2
    down_arrow(d, cx, y + 2, y + 9)
    y += 10

    # --- step 3 -----------------------------------------------------------
    h3 = 30.0
    panel(d, MARGIN, y, CW, h3, edge=GOLD, lw=0.7)
    text(d, MARGIN + 8, y + 6, CW - 16, "3.  It writes one file",
         size=12, style="B", color=GOLD, lh=6)
    text(d, MARGIN + 8, y + 15, CW - 16,
         "persona.md - a full specification of that identity's voice: how it talks, what "
         "it finds funny, words it would never use. For a repo it writes AGENTS.md instead.",
         size=9.5, color=MAUVE, lh=4.6)

    y += h3
    down_arrow(d, cx, y + 2, y + 9)
    y += 10

    # --- step 4 -----------------------------------------------------------
    h4 = 26.0
    panel(d, MARGIN, y, CW, h4)
    text(d, MARGIN + 8, y + 6, CW - 16, "4.  Any AI reads that file and becomes it",
         size=12, style="B", color=GOLD, lh=6)
    text(d, MARGIN + 8, y + 15, CW - 16,
         "Paste it into a chatbot, a robot's voice, a game character. Claude Code and "
         "Cursor pick up AGENTS.md on their own.",
         size=9.5, color=MAUVE, lh=4.6)

    y += h4 + 10

    # --- before / after ---------------------------------------------------
    text(d, MARGIN, y, CW, "The difference it makes", size=11, style="B",
         color=LILAC, lh=5.5)
    y += 7
    half = (CW - 6) / 2

    panel(d, MARGIN, y, half, 30, fill=(46, 26, 34), edge=ROSE, lw=0.4)
    text(d, MARGIN + 5, y + 4.5, half - 10, "GENERIC AI", size=7.5, style="B",
         color=ROSE, lh=4)
    text(d, MARGIN + 5, y + 11, half - 10,
         '"Let\'s delve into this crucial tapestry of features that serve as a '
         'testament to..."', size=9, color=MAUVE, lh=4.6)

    panel(d, MARGIN + half + 6, y, half, 30, fill=(26, 46, 36), edge=GREEN, lw=0.4)
    text(d, MARGIN + half + 11, y + 4.5, half - 10, "A REAL IDENTITY", size=7.5, style="B",
         color=GREEN, lh=4)
    text(d, MARGIN + half + 11, y + 11, half - 10,
         '"Well, that\'s officially on fire. Fun! Give me a second, partner."'
         "   - Bolt, a desktop robot, humor set to 8.", size=9, color=MAUVE, lh=4.6)

    # --- footer -----------------------------------------------------------
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.4)
    d.line(MARGIN + 45, 275, PAGE_W - MARGIN - 45, 275)
    text(d, 0, 279, PAGE_W, "One command does all of it:", size=9, color=FAINT,
         align="C", lh=4.5)
    mono(d, 0, 284, PAGE_W, "pixieduster clone", size=12, color=GOLD, align="C")

    out = DOCS / "PixieDuster-Diagram.pdf"
    DOCS.mkdir(parents=True, exist_ok=True)
    d.output(str(out))
    return out


# ---------------------------------------------------------------------------
# 2. The quick start
# ---------------------------------------------------------------------------

def step(d: Doc, y: float, n: str, title: str, body: str, cmd: str | None = None,
         *, note: str | None = None) -> float:
    """One numbered step. Returns the y after it."""
    h = 24.0 + (11.0 if cmd else 0.0) + (7.0 if note else 0.0)
    panel(d, MARGIN, y, CW, h)

    d.set_fill_color(*GOLD)
    d.ellipse(MARGIN + 6, y + 6, 8, 8, style="F")
    d.set_font("Helvetica", "B", 10)
    d.set_text_color(*DEEP)
    d.set_xy(MARGIN + 6, y + 7.4)
    d.cell(8, 5, T(n), align="C")

    text(d, MARGIN + 18, y + 5.5, CW - 26, title, size=11.5, style="B", color=GOLD, lh=5.5)
    inner = text(d, MARGIN + 18, y + 13, CW - 26, body, size=9.4, color=MAUVE, lh=4.7)

    if cmd:
        cy = inner + 1.5
        panel(d, MARGIN + 18, cy, CW - 26, 9, fill=(24, 14, 40), edge=DIM_GOLD,
              radius=1.5, lw=0.3)
        mono(d, MARGIN + 22, cy + 2.6, CW - 34, cmd, size=9.5)
        inner = cy + 10

    if note:
        text(d, MARGIN + 18, inner + 0.5, CW - 26, note, size=8.4, color=FAINT, lh=4.2)

    return y + h + 5


def quickstart() -> Path:
    d = Doc()

    # ---- page 1 ----------------------------------------------------------
    d.add_page()
    d.bg()
    sparkles(d, 21, 70, 0, 0, PAGE_W, PAGE_H)

    if LOGO.exists():
        d.image(str(LOGO), x=PAGE_W / 2 - 9, y=11, w=18)

    text(d, 0, 33, PAGE_W, "Quick start", size=22, style="B", color=GOLD,
         align="C", lh=9)
    text(d, MARGIN, 45, CW, "Five minutes, start to finish.", size=11,
         color=LILAC, align="C", lh=5.5)

    y = 58.0
    y = step(d, y, "1", "Install it",
             "You only do this once. It runs without installing anything permanently.",
             "uv tool install pixieduster")
    y = step(d, y, "2", "Decide who the persona is",
             "Invent a character, or clone a real voice from writing. Pick one:",
             'pixieduster clone -d "a friendly desktop robot with great humor"\n'
             "pixieduster clone --from ./my-essays\n"
             "pixieduster clone --repo .",
             note="--from takes text files, PDFs, even screenshots of handwriting.")
    y = step(d, y, "3", "Look before you send",
             "Add --dry-run to any of those. It shows exactly what would go to Google "
             "and sends nothing at all.",
             "pixieduster clone -d \"a grumpy lighthouse keeper\" --dry-run")
    y = step(d, y, "4", "Run it for real",
             "Answer three questions with the arrow keys, set the humor slider, wait "
             "about thirty seconds.")
    y = step(d, y, "5", "You are done",
             "You get persona.md - the full voice specification. Paste it into any AI as "
             "a system prompt. With --repo it writes AGENTS.md, which Claude Code and "
             "Cursor pick up on their own.")

    text(d, 0, 278, PAGE_W, "PixieDuster - Quick start - page 1 of 2", size=7.5,
         color=FAINT, align="C", lh=4)

    # ---- page 2 ----------------------------------------------------------
    d.add_page()
    d.bg()
    sparkles(d, 22, 60, 0, 0, PAGE_W, PAGE_H)

    text(d, MARGIN, 22, CW, "What you will see", size=16, style="B", color=GOLD, lh=8)
    y = 34.0
    panel(d, MARGIN, y, CW, 40)
    seen = [
        "A gold PixieDuster logo across the top of your terminal.",
        "A list of what it will send, and what it will cost.",
        "Three questions, one at a time. Arrow keys to move, enter to pick.",
        "A slider for how funny the persona should be.",
        "A gold certificate showing the persona it made.",
    ]
    yy = y + 6
    for line in seen:
        d.set_fill_color(*GOLD)
        d.ellipse(MARGIN + 8, yy + 1.4, 1.4, 1.4, style="F")
        text(d, MARGIN + 13, yy, CW - 22, line, size=9.4, color=MAUVE, lh=4.6)
        yy += 6.4

    y = 84.0
    text(d, MARGIN, y, CW, "The other two commands", size=16, style="B", color=GOLD, lh=8)
    y += 12
    for cmd, what in (
        ("pixieduster chat", "Talk to your persona and hear how it sounds."),
        ("pixieduster diff draft.md", "Ask whether something you wrote sounds like you."),
    ):
        panel(d, MARGIN, y, CW, 17)
        mono(d, MARGIN + 6, y + 4, CW - 12, cmd, size=9.5)
        text(d, MARGIN + 6, y + 10, CW - 12, what, size=9, color=FAINT, lh=4.4)
        y += 21

    y += 4
    text(d, MARGIN, y, CW, "If something goes wrong", size=16, style="B", color=GOLD, lh=8)
    y += 12
    trouble = [
        ("It says no API key found",
         "Run  pixieduster config set-key  and paste your key. Once only."),
        ("It says the key is not valid",
         "Something else may be overriding it. Run  pixieduster config show  to see "
         "which of the four places your key is coming from."),
        ("It found no writing samples",
         "Nothing to learn from. Either point --from at some writing, or skip samples "
         "entirely and invent a character with --describe."),
        ("It found a possible password",
         "It stops and shows you. Add --scrub to blank them out, or look at what it "
         "found and decide."),
    ]
    for title, body in trouble:
        h = 17.0
        panel(d, MARGIN, y, CW, h, fill=(38, 22, 58), edge=DIM_GOLD, lw=0.3)
        text(d, MARGIN + 6, y + 3.5, CW - 12, title, size=9.4, style="B", color=LILAC, lh=4.6)
        text(d, MARGIN + 6, y + 9, CW - 12, body, size=8.8, color=MAUVE, lh=4.3)
        y += h + 4

    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.4)
    d.line(MARGIN + 50, 268, PAGE_W - MARGIN - 50, 268)
    text(d, 0, 273, PAGE_W,
         "Your writing is sent to Google to be analyzed. Use --dry-run to see exactly "
         "what would go, before it goes.", size=8.6, color=FAINT, align="C", lh=4.3)
    text(d, 0, 285, PAGE_W, "PixieDuster - Quick start - page 2 of 2", size=7.5,
         color=FAINT, align="C", lh=4)

    out = DOCS / "PixieDuster-QuickStart.pdf"
    DOCS.mkdir(parents=True, exist_ok=True)
    d.output(str(out))
    return out


if __name__ == "__main__":
    for path in (diagram(), quickstart()):
        print(f"wrote {path}  ({path.stat().st_size:,} bytes)")
