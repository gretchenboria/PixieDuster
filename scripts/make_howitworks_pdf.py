"""A visual explainer: the flow, the science, and the stack.

    .venv-cli/bin/python scripts/make_howitworks_pdf.py

Every example quoted on the science page is real output, taken from the persona
PixieDuster generated for "a friendly desktop robot with great humor".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_simple_pdfs import (  # noqa: E402
    CW, DEEP, DIM_GOLD, DOCS, FAINT, GOLD, GREEN, LILAC, LOGO, MARGIN,
    MAUVE, PAGE_W, PANEL, PURPLE, ROSE, Doc, down_arrow, mono, panel,
    sparkles, text,
)

BLUE = (137, 180, 250)


def arrow_right(d: Doc, x1, y, x2, *, color=DIM_GOLD) -> None:
    d.set_draw_color(*color)
    d.set_fill_color(*color)
    d.set_line_width(0.6)
    d.line(x1, y, x2 - 2.2, y)
    d.polygon([(x2 - 2.6, y - 2.0), (x2 - 2.6, y + 2.0), (x2, y)], style="F")


def heading(d: Doc, y: float, title: str, sub: str) -> float:
    text(d, MARGIN, y, CW, title, size=19, style="B", color=GOLD, lh=9)
    text(d, MARGIN, y + 10, CW, sub, size=9.6, color=LILAC, lh=5)
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.4)
    d.line(MARGIN, y + 19, PAGE_W - MARGIN, y + 19)
    return y + 25


# ---------------------------------------------------------------------------
# page 1 - the flow
# ---------------------------------------------------------------------------

def page_flow(d: Doc) -> None:
    d.add_page()
    d.bg()
    sparkles(d, 3, 70, 0, 0, PAGE_W, 297)

    if LOGO.exists():
        d.image(str(LOGO), x=PAGE_W - MARGIN - 16, y=14, w=16)

    y = heading(d, 20, "How it works",
                "One sentence, or a folder of writing, becomes a specification of a voice.")

    # --- stage 1: three inputs -------------------------------------------
    text(d, MARGIN, y, CW, "1.  EVIDENCE", size=9, style="B", color=GOLD, lh=5)
    y += 6
    bw = (CW - 8) / 3
    inputs = [
        ("A description", "--describe", '"a friendly desktop\nrobot with great humor"', ROSE),
        ("Writing samples", "--from", "essays, chat logs, PDFs,\nscreenshots of handwriting", BLUE),
        ("A git repo", "--repo", "commit bodies, README,\ndocstrings, PR text", GREEN),
    ]
    for i, (label, flag, detail, tint) in enumerate(inputs):
        bx = MARGIN + i * (bw + 4)
        panel(d, bx, y, bw, 28, fill=PURPLE, edge=tint, lw=0.45)
        text(d, bx + 3, y + 3.5, bw - 6, label, size=9.4, style="B", color=tint,
             align="C", lh=4.6)
        mono(d, bx + 3, y + 9, bw - 6, flag, size=7.4, color=GOLD, align="C")
        text(d, bx + 3, y + 15, bw - 6, detail, size=7.2, color=MAUVE, align="C", lh=3.6)

    y += 28
    down_arrow(d, PAGE_W / 2, y + 1.5, y + 8)
    y += 9.5

    # --- stage 2: local processing ----------------------------------------
    panel(d, MARGIN, y, CW, 26, fill=(24, 16, 42), edge=DIM_GOLD)
    text(d, MARGIN + 5, y + 3, CW - 10, "2.  LOCAL PROCESSING    (nothing has left your machine yet)",
         size=9, style="B", color=GOLD, lh=4.6)
    steps = [
        "filter noise", "balance sources", "scan for secrets", "estimate cost", "ask you",
    ]
    sw = (CW - 10 - 4 * 3) / 5
    for i, label in enumerate(steps):
        bx = MARGIN + 5 + i * (sw + 3)
        panel(d, bx, y + 10, sw, 11, fill=PURPLE, edge=DIM_GOLD, radius=1.5, lw=0.3)
        text(d, bx, y + 13.5, sw, label, size=6.8, color=LILAC, align="C", lh=3.4)

    y += 26
    # the trust boundary
    d.set_draw_color(*ROSE)
    d.set_line_width(0.4)
    d.set_dash_pattern(dash=1.5, gap=1.5)
    d.line(MARGIN, y + 4.5, PAGE_W - MARGIN, y + 4.5)
    d.set_dash_pattern()
    text(d, MARGIN, y + 5.5, CW, "network boundary - --dry-run stops here",
         size=6.6, color=ROSE, align="R", lh=3.4)
    down_arrow(d, PAGE_W / 2, y + 1, y + 12)
    y += 13

    # --- stage 3: the analysis --------------------------------------------
    panel(d, MARGIN, y, CW, 44, fill=(28, 18, 48), edge=GOLD, lw=0.7)
    text(d, MARGIN + 5, y + 3.5, CW - 10,
         "3.  ANALYSIS    Gemini, run against four empirical rubrics plus a humor model",
         size=9, style="B", color=GOLD, lh=4.6)

    crit = [
        ("LIWC", "pronouns, affect,\ncognition, time"),
        ("Big Five", "OCEAN traits from\nlexical evidence"),
        ("Cognitive\nstyle", "analytical vs\nnarrative"),
        ("Socio-\nlinguistics", "register, rhythm,\npunctuation"),
        ("Benign\nViolation", "how it is\nfunny"),
    ]
    cw2 = (CW - 10 - 4 * 3) / 5
    for i, (label, detail) in enumerate(crit):
        bx = MARGIN + 5 + i * (cw2 + 3)
        panel(d, bx, y + 11, cw2, 28, fill=PURPLE, edge=DIM_GOLD, radius=1.8, lw=0.35)
        text(d, bx + 1, y + 13.5, cw2 - 2, label, size=7.6, style="B", color=GOLD,
             align="C", lh=3.6)
        text(d, bx + 1, y + 24, cw2 - 2, detail, size=6.4, color=MAUVE, align="C", lh=3.2)

    y += 44
    down_arrow(d, PAGE_W / 2, y + 1.5, y + 8)
    y += 9.5

    # --- stage 4: output ---------------------------------------------------
    panel(d, MARGIN, y, CW, 24, fill=(26, 40, 34), edge=GREEN, lw=0.6)
    text(d, MARGIN + 5, y + 3.5, CW - 10, "4.  ONE FILE", size=9, style="B",
         color=GREEN, lh=4.6)
    mono(d, MARGIN + 5, y + 9, CW - 10, "persona.md", size=11, color=GOLD)
    text(d, MARGIN + 5, y + 15.5, CW - 10,
         "A full specification of that identity's voice. Paste it into any AI as a system "
         "prompt. With --repo it writes AGENTS.md, which Claude Code and Cursor read on their own.",
         size=7.6, color=MAUVE, lh=3.7)

    y += 30
    text(d, MARGIN, y, CW, "What the persona file actually controls",
         size=10, style="B", color=LILAC, lh=5.5)
    y += 7
    controls = [
        "which pronouns it reaches for", "how certain it sounds",
        "its sentence rhythm", "words it will never use",
        "what it finds funny", "how it behaves when wrong",
    ]
    for i, item in enumerate(controls):
        bx = MARGIN + (i % 3) * (CW / 3)
        by = y + (i // 3) * 6
        d.set_fill_color(*GOLD)
        d.ellipse(bx + 1, by + 1.6, 1.3, 1.3, style="F")
        text(d, bx + 5, by, CW / 3 - 6, item, size=8, color=MAUVE, lh=4)

    text(d, 0, 283, PAGE_W, "PixieDuster - how it works - 1 of 3", size=7,
         color=FAINT, align="C", lh=4)


# ---------------------------------------------------------------------------
# page 2 - the science
# ---------------------------------------------------------------------------

def page_science(d: Doc) -> None:
    d.add_page()
    d.bg()
    sparkles(d, 11, 60, 0, 0, PAGE_W, 297)

    y = heading(d, 20, "The criteria it uses",
                "Four empirical rubrics and one humor model. Every quote below is real output.")

    blocks = [
        ("LIWC", "Linguistic Inquiry and Word Count - Pennebaker",
         "Counts function words rather than topic words. Pronoun orientation (I / we / you), "
         "affective processes, cognitive processes (certainty vs hedging), and temporal "
         "orientation. Function words are near-impossible to fake, which is why they are used "
         "in forensic authorship work.",
         'Bolt: 2nd person 50%, 1st plural 30%, 1st singular 20%.\n'
         'Tentativeness near zero - never hedges with "maybe".', ROSE),

        ("The Big Five (OCEAN)", "Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism",
         "Maps language onto the standard five-factor personality model: lexical richness for "
         "Openness, structure for Conscientiousness, social words for Extraversion, hedging and "
         "self-doubt for Neuroticism.",
         'Bolt: Neuroticism 1.0 / 5 - "Well, that\'s officially on fire. Fun!"\n'
         'Agreeableness 3.5 / 5 - warm, but wrapped in teasing.', BLUE),

        ("Cognitive style & epistemic stance", "How the mind behind the words moves",
         "Analytical or narrative? Does it argue from evidence, from anecdote, or from "
         "conviction? Dialectical thinking or binary? This is what stops a persona being a "
         "vocabulary list and makes it think in character.",
         'Bolt: narrative wrapped in micro-analytical logic. Dialectical\n'
         'in perspective, binary in execution.', GREEN),

        ("Sociolinguistics", "The fingerprint in the mechanics",
         "Register (academic vs colloquial), specific jargon, syntactic rhythm - staccato or "
         "winding - and punctuation habits. The small involuntary tells that make prose "
         "recognizable.",
         'Bolt: casual-technical register, staccato rhythm, tech metaphor\n'
         '(buffer overflow, cold boot, bandwidth).', (200, 160, 230)),

        ("Benign Violation Theory", "McGraw - what the humor slider actually sets",
         "Something is funny when it violates a norm AND stays benign, simultaneously. Violation "
         "alone is just cruelty; benign alone is just pleasant. The 0-10 slider sets how hard it "
         "pushes the violation while holding the benign frame.",
         'Bolt at 8 / 10: "That schedule isn\'t a calendar, it\'s a crime\n'
         'scene. Let\'s fix it before your sanity hits 1%."', GOLD),
    ]

    for title, sub, body, example, tint in blocks:
        h = 44.0
        panel(d, MARGIN, y, CW, h, fill=(26, 16, 44), edge=tint, lw=0.45)
        text(d, MARGIN + 5, y + 3.5, CW - 10, title, size=10.4, style="B", color=tint, lh=5)
        text(d, MARGIN + 5, y + 9.5, CW - 10, sub, size=7.2, color=FAINT, lh=3.6)
        text(d, MARGIN + 5, y + 14.5, CW - 10, body, size=8.2, color=MAUVE, lh=4.1)

        panel(d, MARGIN + 5, y + 30, CW - 10, 11, fill=(18, 11, 32), edge=tint,
              radius=1.5, lw=0.25)
        mono(d, MARGIN + 8, y + 32, CW - 16, example, size=6.6, color=LILAC)

        y += h + 4

    text(d, 0, 283, PAGE_W, "PixieDuster - the criteria - 2 of 3", size=7,
         color=FAINT, align="C", lh=4)


# ---------------------------------------------------------------------------
# page 3 - the stack
# ---------------------------------------------------------------------------

def page_stack(d: Doc) -> None:
    d.add_page()
    d.bg()
    sparkles(d, 17, 60, 0, 0, PAGE_W, 297)

    y = heading(d, 20, "The tech stack",
                "Four runtime dependencies. No server, no database, no account.")

    rows = [
        ("Language", "Python 3.11+", "Runs anywhere; the web app is already Python."),
        ("Commands", "Typer", "clone / chat / diff / config, with proper --help."),
        ("Terminal UI", "Rich", "Gradient banner, pixie dust, arrow-key menus, the certificate."),
        ("HTTP", "requests", "Gemini REST v1beta called directly - no SDK to go stale."),
        ("Key loading", "python-dotenv", "Reads .env without putting the key in os.environ."),
        ("Repo reading", "git + gh", "Subprocess only, and only when you pass --repo."),
        ("Documents", "Gemini native", "PDFs and images go up as-is; no local parser needed."),
        ("Packaging", "hatchling + uvx", "uvx pixieduster clone runs with nothing installed."),
        ("Tests", "pytest", "431 tests, all offline, no API key required."),
    ]
    widths = [0.20, 0.24, 0.56]
    panel(d, MARGIN, y, CW, 12 + len(rows) * 9.4, fill=(24, 15, 42), edge=DIM_GOLD)
    hy = y + 4
    xs = [MARGIN + 5]
    for w in widths[:-1]:
        xs.append(xs[-1] + (CW - 10) * w)
    for i, head in enumerate(("Layer", "Choice", "Why")):
        text(d, xs[i], hy, (CW - 10) * widths[i] - 3, head, size=7.4, style="B",
             color=GOLD, lh=4)
    hy += 6
    d.set_draw_color(*DIM_GOLD)
    d.set_line_width(0.25)
    d.line(MARGIN + 5, hy - 1, PAGE_W - MARGIN - 5, hy - 1)
    for layer, choice, why in rows:
        text(d, xs[0], hy + 1.5, (CW - 10) * widths[0] - 3, layer, size=8, color=LILAC, lh=4)
        d.set_font("Courier", "", 7.8)
        d.set_text_color(*GOLD)
        d.set_xy(xs[1], hy + 1.5)
        d.multi_cell((CW - 10) * widths[1] - 3, 4, choice)
        text(d, xs[2], hy + 1.5, (CW - 10) * widths[2] - 3, why, size=8, color=MAUVE, lh=4)
        hy += 9.4

    y += 12 + len(rows) * 9.4 + 8

    # --- what it does NOT do ----------------------------------------------
    text(d, MARGIN, y, CW, "Deliberately absent", size=10.4, style="B", color=LILAC, lh=5.5)
    y += 7
    absent = [
        ("No server", "It runs on your machine. There is nothing to sign up for."),
        ("No database", "The only stored state is one 0600 config file with your API key."),
        ("No SDK", "Two REST endpoints called with requests. Fewer moving parts to break."),
        ("No telemetry", "Nothing is reported anywhere. The only outbound call is to Gemini."),
    ]
    for title, body in absent:
        panel(d, MARGIN, y, CW, 13, fill=PANEL, edge=DIM_GOLD, radius=2, lw=0.3)
        text(d, MARGIN + 5, y + 2.5, CW - 10, title, size=8.6, style="B", color=GREEN, lh=4.2)
        text(d, MARGIN + 5, y + 7.2, CW - 10, body, size=7.8, color=MAUVE, lh=3.8)
        y += 15

    y += 4
    panel(d, MARGIN, y, CW, 26, fill=(40, 24, 30), edge=ROSE, lw=0.45)
    text(d, MARGIN + 5, y + 3, CW - 10, "The one thing that leaves your machine",
         size=8.6, style="B", color=ROSE, lh=4.2)
    text(d, MARGIN + 5, y + 8, CW - 10,
         "Your writing goes to Google's Gemini API to be analyzed. That is the product, not a "
         "side effect. Before every send it is scanned against 22 secret-detection rules, priced, "
         "and shown to you. --dry-run prints the exact payload and sends nothing.",
         size=7.8, color=MAUVE, lh=3.9)

    text(d, 0, 283, PAGE_W, "PixieDuster - the stack - 3 of 3", size=7,
         color=FAINT, align="C", lh=4)


def build() -> Path:
    d = Doc()
    page_flow(d)
    page_science(d)
    page_stack(d)
    out = DOCS / "PixieDuster-HowItWorks.pdf"
    DOCS.mkdir(parents=True, exist_ok=True)
    d.output(str(out))
    return out


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}  ({path.stat().st_size:,} bytes)")
