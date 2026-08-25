"""Build the PixieDuster poster as SVG, then rasterize it to PNG.

    .venv-cli/bin/python scripts/make_poster.py

The central metaphor is a prism: writing goes in as one beam, and comes out
split into the five things the analysis actually measures. Every number shown
is real output from the generated "Bolt" persona.
"""

from __future__ import annotations

import base64
import math
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LOGO = ROOT / "logo.png"

W, H = 1600, 2540

GOLD = "#ffd700"
DIM = "#daa520"
LILAC = "#e2d1f9"
MAUVE = "#d1c4e9"
FAINT = "#8a7da3"
DEEP = "#0f081c"

ROSE = "#ff9ecb"
BLUE = "#89b4fa"
GREEN = "#7ed9a0"
VIOLET = "#c9a0ff"

SANS = "Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "Menlo, DejaVu Sans Mono, monospace"

out: list[str] = []


def add(s: str) -> None:
    out.append(s)


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, *, size=20, fill=MAUVE, weight="normal", anchor="start",
         family=SANS, spacing=0, opacity=1.0, style="") -> None:
    add(
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}" '
        f'letter-spacing="{spacing}" opacity="{opacity}" {style}>{esc(s)}</text>'
    )


def card(x, y, w, h, *, stroke=DIM, fill="#1d1233", rx=18, sw=1.6, opacity=1.0) -> None:
    add(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" opacity="{opacity}"/>'
    )


# ---------------------------------------------------------------------------
# defs: gradients, glows, sparkle field
# ---------------------------------------------------------------------------

def defs() -> None:
    add("<defs>")
    add(
        '<radialGradient id="bg" cx="50%" cy="8%" r="95%">'
        '<stop offset="0%" stop-color="#3a2159"/>'
        '<stop offset="55%" stop-color="#1d1133"/>'
        f'<stop offset="100%" stop-color="{DEEP}"/></radialGradient>'
    )
    add(
        '<linearGradient id="goldbar" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{GOLD}"/>'
        f'<stop offset="100%" stop-color="{DIM}"/></linearGradient>'
    )
    add(
        '<linearGradient id="title" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{GOLD}"/>'
        '<stop offset="55%" stop-color="#ffe98a"/>'
        '<stop offset="100%" stop-color="#c9a0ff"/></linearGradient>'
    )
    add(
        '<linearGradient id="beamin" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0%" stop-color="#ffffff" stop-opacity="0.05"/>'
        '<stop offset="100%" stop-color="#ffffff" stop-opacity="0.85"/></linearGradient>'
    )
    # one gradient per outgoing beam
    for name, color in (("b0", ROSE), ("b1", BLUE), ("b2", GREEN),
                         ("b3", VIOLET), ("b4", GOLD)):
        add(
            f'<linearGradient id="{name}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0%" stop-color="{color}" stop-opacity="0.95"/>'
            f'<stop offset="100%" stop-color="{color}" stop-opacity="0.18"/></linearGradient>'
        )
    add(
        '<linearGradient id="prism" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#ffffff" stop-opacity="0.30"/>'
        '<stop offset="50%" stop-color="#c9a0ff" stop-opacity="0.16"/>'
        '<stop offset="100%" stop-color="#ffd700" stop-opacity="0.22"/></linearGradient>'
    )
    add(
        '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%">'
        '<feGaussianBlur stdDeviation="9" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    )
    add(
        '<filter id="soft" x="-40%" y="-40%" width="180%" height="180%">'
        '<feGaussianBlur stdDeviation="3.5" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    )
    add("</defs>")


def background() -> None:
    add(f'<rect width="{W}" height="{H}" fill="url(#bg)"/>')
    rng = random.Random(11)
    for _ in range(260):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        r = rng.choice([0.9, 1.3, 1.8, 2.4])
        o = rng.uniform(0.12, 0.72)
        c = GOLD if rng.random() < 0.62 else "#ffffff"
        add(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{c}" opacity="{o:.2f}"/>')
    # a few four-point sparkles
    for _ in range(14):
        x, y = rng.uniform(40, W - 40), rng.uniform(40, H - 40)
        s = rng.uniform(5, 11)
        add(
            f'<path d="M {x} {y-s} Q {x} {y} {x+s} {y} Q {x} {y} {x} {y+s} '
            f'Q {x} {y} {x-s} {y} Q {x} {y} {x} {y-s} Z" fill="{GOLD}" '
            f'opacity="{rng.uniform(0.25,0.6):.2f}"/>'
        )


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------

def header() -> None:
    if LOGO.is_file():
        b64 = base64.b64encode(LOGO.read_bytes()).decode()
        add(
            f'<image x="{W/2-58}" y="42" width="116" height="116" '
            f'href="data:image/png;base64,{b64}"/>'
        )
    text(W / 2, 232, "PixieDuster", size=76, fill="url(#title)", weight="bold",
         anchor="middle", style='filter="url(#glow)"')
    text(W / 2, 278, "Give an AI a real identity to be", size=25, fill=LILAC,
         anchor="middle")
    text(W / 2, 312, "one sentence, or a folder of your writing, becomes a specification of a voice",
         size=17, fill=FAINT, anchor="middle")
    add(f'<rect x="{W/2-190}" y="336" width="380" height="2.5" fill="url(#goldbar)" opacity="0.85"/>')


def section_label(y, n, title) -> None:
    add(f'<rect x="70" y="{y-26}" width="5" height="34" fill="{GOLD}"/>')
    text(92, y, n, size=17, fill=GOLD, weight="bold", family=MONO)
    text(126, y, title, size=27, fill=LILAC, weight="bold")


# ---------------------------------------------------------------------------
# the prism
# ---------------------------------------------------------------------------

# (title, what you do in the browser, the equivalent CLI flag, color, examples)
INPUTS = [
    ("Invent a character", "type a description", "--describe", ROSE,
     "a friendly desktop robot"),
    ("Your own writing", "upload files", "--from", BLUE,
     "notes, screenshots, photos, emails"),
    ("A git repo", "CLI only", "--repo", GREEN,
     "commits, README, docstrings"),
]

CRITERIA = [
    ("LIWC", "Linguistic Inquiry and Word Count  -  Pennebaker",
     "Counts function words rather than topic words: who the\npronouns point at, certainty against hedging, past against now.",
     ROSE, "b0"),
    ("The Big Five", "Openness  -  Conscientiousness  -  Extraversion  -  Agreeableness  -  Neuroticism",
     "The five-factor model, read off lexical evidence rather\nthan asked about in a questionnaire.",
     BLUE, "b1"),
    ("Cognitive style", "Epistemic stance  -  how the mind behind the words moves",
     "Analytical or narrative? Reasoning from evidence, from\nanecdote, or from conviction? Dialectical or binary?",
     GREEN, "b2"),
    ("Sociolinguistics", "Register, rhythm, and the involuntary tells",
     "Formal or colloquial, the jargon it reaches for, staccato\nor winding sentences, punctuation habits.",
     VIOLET, "b3"),
    ("Benign Violation", "Benign Violation Theory  -  McGraw",
     "Funny is a violation that stays benign, and both at once.\nRead off the evidence, like everything else here.",
     GOLD, "b4"),
]


def liwc_chart(cx, cy) -> None:
    """Donut of Bolt's real pronoun split: 50 / 30 / 20."""
    r, ring = 30, 11
    start = -90.0
    for frac, color in ((0.50, ROSE), (0.30, "#ff7fb3"), (0.20, "#b26b8f")):
        end = start + frac * 360
        a0, a1 = math.radians(start), math.radians(end)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if frac > 0.5 else 0
        add(
            f'<path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 {large} 1 {x1:.1f} {y1:.1f}" '
            f'fill="none" stroke="{color}" stroke-width="{ring}" stroke-linecap="butt"/>'
        )
        start = end
    text(cx, cy + 5, "you", size=13, fill=LILAC, anchor="middle", weight="bold")


def bigfive_chart(x, y) -> None:
    """Bolt's real OCEAN scores."""
    scores = [("O", 4.5), ("C", 4.0), ("E", 4.5), ("A", 3.5), ("N", 1.0)]
    bw, gap, maxw = 9, 6, 92
    for i, (letter, v) in enumerate(scores):
        by = y + i * (bw + gap)
        add(f'<rect x="{x+16}" y="{by}" width="{maxw}" height="{bw}" rx="4" fill="#ffffff" opacity="0.09"/>')
        add(f'<rect x="{x+16}" y="{by}" width="{maxw*v/5:.0f}" height="{bw}" rx="4" fill="{BLUE}" opacity="0.95"/>')
        text(x, by + bw - 1, letter, size=11, fill=FAINT, weight="bold", family=MONO)


def cognitive_chart(cx, cy) -> None:
    """A needle between narrative and analytical."""
    r = 34
    add(
        f'<path d="M {cx-r} {cy} A {r} {r} 0 0 1 {cx+r} {cy}" fill="none" '
        f'stroke="#ffffff" stroke-opacity="0.13" stroke-width="9" stroke-linecap="round"/>'
    )
    ang = math.radians(180 - 62)          # leans analytical
    add(
        f'<line x1="{cx}" y1="{cy}" x2="{cx + r*math.cos(ang):.1f}" '
        f'y2="{cy + -abs(r*math.sin(ang)):.1f}" stroke="{GREEN}" stroke-width="4" '
        'stroke-linecap="round"/>'
    )
    add(f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="{GREEN}"/>')
    text(cx - r - 2, cy + 16, "story", size=10, fill=FAINT, anchor="middle")
    text(cx + r + 2, cy + 16, "logic", size=10, fill=FAINT, anchor="middle")


def socio_chart(x, y) -> None:
    """Staccato vs winding, as a waveform."""
    heights = [10, 26, 8, 30, 14, 6, 22, 34, 9, 18, 7, 28]
    for i, h in enumerate(heights):
        add(
            f'<rect x="{x + i*9}" y="{y + (36-h)}" width="5" height="{h}" rx="2.5" '
            f'fill="{VIOLET}" opacity="{0.45 + 0.045*(h/10):.2f}"/>'
        )


def humor_chart(cx, cy) -> None:
    """The Benign Violation Venn - the overlap is where funny lives."""
    r = 25
    add(f'<circle cx="{cx-14}" cy="{cy}" r="{r}" fill="{ROSE}" fill-opacity="0.28" stroke="{ROSE}" stroke-width="1.6"/>')
    add(f'<circle cx="{cx+14}" cy="{cy}" r="{r}" fill="{GREEN}" fill-opacity="0.28" stroke="{GREEN}" stroke-width="1.6"/>')
    add(f'<circle cx="{cx}" cy="{cy}" r="9" fill="{GOLD}" opacity="0.92"/>')
    text(cx - 40, cy + 42, "violation", size=10, fill=FAINT, anchor="middle")
    text(cx + 42, cy + 42, "benign", size=10, fill=FAINT, anchor="middle")


def flow_output(y: float) -> None:
    """What comes out the other side. Without this the picture stops halfway."""
    add(f'<path d="M {W/2} {y-34} L {W/2} {y-10}" stroke="{GOLD}" stroke-width="3"/>')
    add(f'<path d="M {W/2-6} {y-14} L {W/2+6} {y-14} L {W/2} {y-4} Z" fill="{GOLD}"/>')

    card(80, y, W - 160, 132, stroke=GOLD, fill="#1a2a20", sw=2.2)

    # the document
    add(f'<rect x="118" y="{y+22}" width="86" height="88" rx="6" fill="#ffffff" '
        f'opacity="0.07" stroke="{DIM}" stroke-width="1.2"/>')
    for k in range(5):
        add(f'<rect x="132" y="{y+36+k*13}" width="{58 - (k%3)*14}" height="3.6" '
            f'rx="1.8" fill="{LILAC}" opacity="0.6"/>')
    add(f'<circle cx="206" cy="{y+98}" r="15" fill="{GOLD}" opacity="0.95"/>')
    text(206, y + 103, "PD", size=11, fill="#3a2400", weight="bold",
         anchor="middle", family=MONO)

    text(240, y + 44, "persona.md", size=25, fill=GOLD, family=MONO)
    text(240, y + 72, "One file: how this identity talks, what it finds funny,",
         size=14, fill=MAUVE)
    text(240, y + 94, "the words it would never use. Paste it into any AI as a",
         size=14, fill=MAUVE)
    text(240, y + 116, "system prompt and it becomes that identity.", size=14, fill=MAUVE)

    for i, chip in enumerate(["a chatbot", "a game character", "Claude Code", "Cursor"]):
        cw2 = 15 + len(chip) * 8.2
        cx = W - 100 - cw2 - i * 0  # laid out right to left below
        add("")
    x = W - 96
    for chip in reversed(["a chatbot", "a game character", "Claude Code", "Cursor"]):
        cw2 = 16 + len(chip) * 8.2
        x -= cw2 + 10
        add(f'<rect x="{x:.0f}" y="{y+96}" width="{cw2:.0f}" height="26" rx="13" '
            f'fill="#ffffff" opacity="0.07" stroke="{DIM}" stroke-width="0.8"/>')
        text(x + cw2 / 2, y + 113, chip, size=11.5, fill=MAUVE, anchor="middle")


def flow() -> None:
    section_label(430, "01", "How it works")

    px, py = 640, 790            # prism center
    ph = 132                     # prism half-height

    # --- input cards ---------------------------------------------------
    for i, (label, web, flag, color, detail) in enumerate(INPUTS):
        y = 500 + i * 178
        card(80, y, 300, 146, stroke=color)
        add(f'<rect x="80" y="{y}" width="6" height="146" rx="3" fill="{color}"/>')
        text(108, y + 38, label, size=20, fill=color, weight="bold")
        text(108, y + 64, f"in the app:  {web}", size=12.5, fill=LILAC)
        text(108, y + 88, "in the CLI:", size=12.5, fill=LILAC)
        text(180, y + 88, flag, size=13.5, fill=GOLD, family=MONO)
        text(108, y + 116, detail, size=12, fill=FAINT)

        # curved beam into the prism
        sy = y + 73
        add(
            f'<path d="M 384 {sy} C 480 {sy}, 500 {py}, {px-96} {py}" fill="none" '
            f'stroke="{color}" stroke-width="2.6" opacity="0.55"/>'
        )

    # --- the white beam entering ----------------------------------------
    add(f'<rect x="{px-96}" y="{py-9}" width="96" height="18" fill="url(#beamin)"/>')

    # --- the prism --------------------------------------------------------
    add(
        f'<path d="M {px} {py-ph} L {px+118} {py+ph} L {px-118} {py+ph} Z" '
        f'fill="url(#prism)" stroke="{GOLD}" stroke-width="2.4" '
        'stroke-linejoin="round" filter="url(#soft)"/>'
    )
    text(px, py + 66, "GEMINI", size=15, fill=GOLD, weight="bold", anchor="middle",
         family=MONO, spacing=2)
    text(px, py + 92, "four rubrics", size=12.5, fill=LILAC, anchor="middle")
    text(px, py + 110, "humor included", size=12.5, fill=LILAC, anchor="middle")

    # --- the fan of criteria ---------------------------------------------
    cx0, cw, ch, gap = 840, 690, 152, 22
    top = 448
    for i, (name, who, body, color, grad) in enumerate(CRITERIA):
        y = top + i * (ch + gap)
        mid = y + ch / 2

        add(
            f'<path d="M {px+40} {py} C {px+180} {py}, {cx0-150} {mid}, {cx0-6} {mid}" '
            f'fill="none" stroke="url(#{grad})" stroke-width="7" opacity="0.9"/>'
        )

        card(cx0, y, cw, ch, stroke=color)
        add(f'<rect x="{cx0}" y="{y}" width="6" height="{ch}" rx="3" fill="{color}"/>')
        text(cx0 + 28, y + 40, name, size=22, fill=color, weight="bold")
        text(cx0 + 28, y + 66, who, size=11.5, fill=FAINT, spacing=0.6)
        for j, line in enumerate(body.split("\n")):
            text(cx0 + 28, y + 98 + j * 21, line, size=13.5, fill=MAUVE)

        gx = cx0 + cw - 132
        if i == 0:
            liwc_chart(gx + 52, mid)
        elif i == 1:
            bigfive_chart(gx + 14, mid - 36)
        elif i == 2:
            cognitive_chart(gx + 52, mid + 14)
        elif i == 3:
            socio_chart(gx + 4, mid - 18)
        else:
            humor_chart(gx + 52, mid - 6)



# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def output() -> None:
    y = 1382
    section_label(y, "02", "What you get")

    dy = y + 40
    card(80, dy, 360, 210, stroke=GOLD, sw=2.2)
    # a document with a seal
    add(f'<rect x="140" y="{dy+30}" width="150" height="118" rx="7" fill="#ffffff" opacity="0.07" stroke="{DIM}" stroke-width="1.4"/>')
    for k in range(6):
        add(f'<rect x="158" y="{dy+50+k*16}" width="{110 - (k%3)*26}" height="4.5" rx="2" fill="{LILAC}" opacity="0.55"/>')
    add(f'<circle cx="298" cy="{dy+134}" r="24" fill="{GOLD}" opacity="0.93"/>')
    add(f'<circle cx="298" cy="{dy+134}" r="24" fill="none" stroke="#fff8d0" stroke-width="1.4"/>')
    text(298, dy + 140, "PD", size=17, fill="#3a2400", weight="bold", anchor="middle", family=MONO)
    text(260, dy + 186, "persona.md", size=21, fill=GOLD, anchor="middle", family=MONO)

    add(f'<path d="M 470 {dy+105} L 560 {dy+105}" stroke="{GOLD}" stroke-width="3"/>')
    add(f'<path d="M 560 {dy+96} L 578 {dy+105} L 560 {dy+114} Z" fill="{GOLD}"/>')

    card(600, dy, 920, 210, stroke=DIM)
    text(632, dy + 44, "Paste it into any AI and it becomes that identity", size=21,
         fill=LILAC, weight="bold")
    chips = ["Claude Code", "Cursor", "a chatbot", "a game character", "a desktop robot"]
    x = 632
    for c in chips:
        w = 15 + len(c) * 9.2
        add(f'<rect x="{x}" y="{dy+64}" width="{w:.0f}" height="34" rx="17" fill="#ffffff" opacity="0.07" stroke="{DIM}" stroke-width="1"/>')
        text(x + w / 2, dy + 87, c, size=14, fill=MAUVE, anchor="middle")
        x += w + 12

    add(f'<rect x="632" y="{dy+118}" width="856" height="70" rx="10" fill="#150c26" stroke="{GOLD}" stroke-width="1.2" opacity="0.95"/>')
    text(652, dy + 146, '"That schedule isn\'t a calendar, it\'s a crime scene.', size=16.5,
         fill=GOLD, family=MONO)
    text(652, dy + 172, ' Let\'s fix it before your sanity hits 1%."', size=16.5,
         fill=GOLD, family=MONO)
    text(1470, dy + 172, "humor 8/10", size=12.5, fill=FAINT, anchor="end")


# ---------------------------------------------------------------------------
# stack
# ---------------------------------------------------------------------------

def stack() -> None:
    y = 1706
    section_label(y, "03", "The stack")

    bands = [
        ("YOUR MACHINE", GREEN, y + 34, 160,
         [("Typer", "commands"), ("Rich", "the terminal UI"), ("git + gh", "repo mining"),
          ("22 regex rules", "secret scan"), ("SQLite-free", "no database")],
         "Everything here is local. --dry-run stops the run at this line."),
        ("THE ONE HOP OUT", GOLD, y + 246, 150,
         [("requests", "plain HTTPS"), ("x-goog-api-key", "header, never the URL"),
          ("your key", "0600, or a metered proxy")],
         "Scanned, priced and shown to you before anything is sent."),
        ("GOOGLE", BLUE, y + 428, 150,
         [("Gemini 3.6 Flash", "REST v1beta"), ("no SDK", "two endpoints"),
          ("PDFs + images", "read natively")],
         "The only third party involved. Nothing else is contacted, ever."),
    ]

    for title, color, by, bh, chips, note in bands:
        card(80, by, 1440, bh, stroke=color, fill="#180f2c")
        add(f'<rect x="80" y="{by}" width="1440" height="4" rx="2" fill="{color}" opacity="0.9"/>')
        text(112, by + 44, title, size=17, fill=color, weight="bold", spacing=3)
        text(1488, by + 44, note, size=13, fill=FAINT, anchor="end")

        x = 112
        for name, what in chips:
            w = max(190, 22 + len(name) * 11)
            add(f'<rect x="{x}" y="{by+66}" width="{w}" height="72" rx="12" fill="#ffffff" opacity="0.055" stroke="{color}" stroke-width="1" stroke-opacity="0.5"/>')
            text(x + w / 2, by + 96, name, size=16.5, fill=LILAC, anchor="middle",
                 weight="bold", family=MONO)
            text(x + w / 2, by + 120, what, size=12.5, fill=FAINT, anchor="middle")
            x += w + 16

    # dashed trust boundary between local and network
    ty = y + 218
    add(f'<line x1="80" y1="{ty}" x2="1520" y2="{ty}" stroke="{ROSE}" stroke-width="1.6" stroke-dasharray="9 7" opacity="0.8"/>')
    text(1520, ty + 20, "network boundary", size=12.5, fill=ROSE, anchor="end", spacing=1)

    # footer stats
    fy = y + 610
    stats = [("446", "tests, all offline"), ("4", "runtime dependencies"),
             ("0", "servers to run"), ("1", "file you actually get")]
    bw = 1440 / len(stats)
    for i, (big, small) in enumerate(stats):
        cx = 80 + bw * i + bw / 2
        text(cx, fy + 40, big, size=42, fill=GOLD, weight="bold", anchor="middle")
        text(cx, fy + 66, small, size=13.5, fill=FAINT, anchor="middle")

    add(f'<rect x="{W/2-190}" y="{fy+96}" width="380" height="2.5" fill="url(#goldbar)" opacity="0.8"/>')
    text(W / 2, fy + 142, "pixieduster clone", size=30, fill=GOLD, anchor="middle",
         family=MONO, style='filter="url(#soft)"')


def build_flow() -> tuple[Path, Path]:
    """Just the prism, as a standalone graphic for the web page.

    Same drawing code, cropped with a viewBox so it stays one source of truth.
    """
    out.clear()
    TOP, BOT = 444, 1500   # below the numbered label, past the output band
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{BOT-TOP}" '
        f'viewBox="0 {TOP} {W} {BOT-TOP}">')
    defs()
    background()
    flow()
    flow_output(1346)
    add("</svg>")

    # SVG blur filters make browsers re-rasterize on every zoom step, which
    # reads as flicker. The standalone graphic is viewed and zoomed, so it does
    # without them; the print poster keeps them.
    body = "\n".join(out).replace(' filter="url(#soft)"', "").replace(' style=\'filter="url(#glow)"\'', "")

    DOCS.mkdir(parents=True, exist_ok=True)
    svg = DOCS / "PixieDuster-Flow.svg"
    svg.write_text(body, encoding="utf-8")
    png = DOCS / "PixieDuster-Flow.png"
    subprocess.run(["rsvg-convert", "-w", str(W * 2), "-o", str(png), str(svg)], check=True)

    # A web copy, deliberately raster. Served as SVG, the browser re-rasterizes
    # ~300 elements and a full-canvas gradient at every zoom step, which reads
    # as the whole graphic flashing. A bitmap is simply interpolated instead.
    web = DOCS / "PixieDuster-Flow-web.png"
    subprocess.run(["rsvg-convert", "-w", "2000", "-o", str(web), str(svg)], check=True)
    return svg, png, web


def build() -> Path:
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">')
    defs()
    background()
    header()
    flow()
    output()
    stack()
    add("</svg>")

    DOCS.mkdir(parents=True, exist_ok=True)
    svg = DOCS / "PixieDuster-Poster.svg"
    svg.write_text("\n".join(out), encoding="utf-8")

    png = DOCS / "PixieDuster-Poster.png"
    subprocess.run(
        ["rsvg-convert", "-w", str(W * 2), "-o", str(png), str(svg)],
        check=True,
    )
    return png


if __name__ == "__main__":
    for path in (build(), *build_flow()):
        print(f"wrote {path}  ({path.stat().st_size:,} bytes)")
