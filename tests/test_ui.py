"""Tests for pixieduster.ui.

Everything here runs offline and without a TTY: output is captured through a
``rich.console.Console`` writing to ``io.StringIO``, and the raw-key handling is
tested through the pure ``decode_key`` function plus a fake stream.
"""

from __future__ import annotations

import io
import re
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from rich.console import Console

from pixieduster import ui

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture
def cap(monkeypatch):
    """A plain (no-colour) console capturing into StringIO."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=80, no_color=True)
    monkeypatch.setattr(ui, "console", console)
    return buf


@pytest.fixture
def rich_cap(monkeypatch):
    """A colour-capable console capturing into StringIO (for styled output)."""
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=True, color_system="truecolor", width=80)
    monkeypatch.setattr(ui, "console", console)
    return buf


@pytest.fixture
def plain(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", True)
    yield
    monkeypatch.setattr(ui, "PLAIN", False)


@dataclass
class FakeSample:
    kind: str
    origin: str
    text: str = ""
    author: str | None = None
    tokens: int = 0


@dataclass
class FakeFinding:
    rule: str
    origin: str
    line: int
    excerpt: str
    severity: str


PERSONA = """# Voice Profile

## Tone
Wry, precise, allergic to filler.

- Uses **em dashes** liberally
- Prefers short paragraphs
"""


# --------------------------------------------------------------------------
# degradation
# --------------------------------------------------------------------------


def test_is_plain_when_flag_set(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", True)
    assert ui.is_plain() is True


def test_is_plain_when_no_color(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.is_plain() is True


def test_is_plain_when_not_a_tty(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", False)
    monkeypatch.delenv("NO_COLOR", raising=False)

    class NotATty:
        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdout", NotATty())
    assert ui.is_plain() is True


def test_is_plain_false_on_a_real_tty(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", False)
    monkeypatch.delenv("NO_COLOR", raising=False)

    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdout", Tty())
    assert ui.is_plain() is False


def test_no_ansi_leaks_when_no_color_set(monkeypatch):
    """With NO_COLOR set, nothing must emit an escape sequence."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(ui, "PLAIN", False)
    buf = io.StringIO()
    # A terminal-capable console: rich would normally colour this.
    monkeypatch.setattr(
        ui, "console", Console(file=buf, force_terminal=True, no_color=True, width=80)
    )

    ui.banner()
    ui.certificate(PERSONA, "ada")
    ui.samples_table([FakeSample("commit", "git log a1b2c3d", tokens=42)])
    ui.findings_table([FakeFinding("aws-access-key", "README.md", 3, "<REDACTED>", "high")])
    ui.error("boom")
    ui.success("done")
    ui.hint("try --plain")
    with ui.stages("Working") as stage:
        stage("Inspecting your writing samples")

    out = buf.getvalue()
    assert ANSI_RE.search(out) is None, repr(out[:200])


# --------------------------------------------------------------------------
# banner
# --------------------------------------------------------------------------


def test_banner_plain(cap, plain):
    ui.banner()
    out = cap.getvalue()
    assert "PIXIEDUSTER" in out
    assert "Your Fairy Prompt-Mother" in out
    assert "█" not in out


def test_banner_fits_80_columns():
    rows = ui._wordmark_rows()
    assert len(rows) == 5
    assert max(len(r) for r in rows) <= 80


def test_banner_renders_blocks_and_tagline(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.banner()
    out = rich_cap.getvalue()
    assert "█" in out
    assert "Your Fairy Prompt-Mother" in out
    # gradient: gold at the start, purple-ish at the end
    assert "255;215;0" in out


def test_gradient_endpoints():
    cols = ui.gradient([ui.GOLD, ui.PIXIE_PURPLE], 5)
    assert cols[0] == ui.GOLD
    assert cols[-1] == ui.PIXIE_PURPLE
    assert len(cols) == 5


def test_gradient_edge_cases():
    assert ui.gradient([ui.GOLD], 0) == []
    assert ui.gradient([ui.GOLD, ui.DEEP], 1) == [ui.GOLD]


# --------------------------------------------------------------------------
# certificate
# --------------------------------------------------------------------------


def test_certificate_plain(cap, plain):
    ui.certificate(PERSONA, "ada lovelace")
    out = cap.getvalue()
    assert "CERTIFICATE OF PERSONA" in out
    assert "Officially cloned for: ADA LOVELACE" in out
    assert "Authorized by PixieDuster" in out
    # raw markdown is preserved verbatim in plain mode
    assert "## Tone" in out
    assert "═" not in out


def test_certificate_rich(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.certificate(PERSONA, "ada")
    out = ANSI_RE.sub("", rich_cap.getvalue())
    # double box border
    assert "╔" in out and "╚" in out
    # letter-spaced heading
    assert "C E R T I F I C A T E" in out
    assert "Officially cloned for: ADA" in out
    assert "✦ Authorized by PixieDuster" in out
    # markdown got rendered, not passed through
    assert "## Tone" not in out
    assert "Tone" in out


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def test_stages_plain(cap, plain):
    with ui.stages("Consulting the fairies") as stage:
        for name in ui.STAGE_NAMES[:3]:
            stage(name)
    out = cap.getvalue()
    assert "Consulting the fairies" in out
    for name in ui.STAGE_NAMES[:3]:
        assert name in out
    # the first two ticked to done, and the last is closed out at exit
    assert out.count("[done]") == 3
    assert "⠋" not in out


def test_stage_list_state_machine():
    steps = ui._StageList("t")
    steps.start("one")
    assert steps.done == [] and steps.current == "one"
    steps.start("two")
    assert steps.done == ["one"] and steps.current == "two"
    steps.finish()
    assert steps.done == ["one", "two"] and steps.current is None


def test_stages_rich_renders_check_and_spinner(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    with ui.stages("Consulting the fairies") as stage:
        stage("Inspecting your writing samples")
        stage("Mapping sociolinguistics")
    out = ANSI_RE.sub("", rich_cap.getvalue())
    assert "Consulting the fairies" in out
    assert "✓" in out
    assert "Mapping sociolinguistics" in out


# --------------------------------------------------------------------------
# key decoding
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seq,expected",
    [
        ("\x1b[A", "up"),
        ("\x1b[B", "down"),
        ("\x1b[C", "right"),
        ("\x1b[D", "left"),
        ("\x1bOA", "up"),
        ("\x1bOD", "left"),
        ("\x1b[H", "home"),
        ("\x1b[F", "end"),
        ("\r", "enter"),
        ("\n", "enter"),
        ("\x03", "interrupt"),
        ("\x04", "eof"),
        ("\x7f", "backspace"),
        ("\t", "tab"),
        (" ", "space"),
        ("\x1b", "escape"),
        ("k", "up"),
        ("j", "down"),
        ("h", "left"),
        ("l", "right"),
        ("q", "escape"),
        ("3", "3"),
        ("", ""),
        ("\x1b[Z", ""),
        ("\xe0H", "up"),
        ("\x00P", "down"),
    ],
)
def test_decode_key(seq, expected):
    assert ui.decode_key(seq) == expected


def test_read_key_from_fake_stream():
    stream = io.StringIO("\x1b[A\x1b[Bx\r")
    assert ui.read_key_from(stream) == "up"
    assert ui.read_key_from(stream) == "down"
    assert ui.read_key_from(stream) == "x"
    assert ui.read_key_from(stream) == "enter"
    assert ui.read_key_from(stream) == "eof"


# --------------------------------------------------------------------------
# ask_choice / ask_slider
# --------------------------------------------------------------------------


def test_ask_choice_plain_numbered(cap, plain, monkeypatch):
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    result = ui.ask_choice("How do you write?", ["Terse", "Winding", "Both"], 2, 3)
    out = cap.getvalue()
    assert "Q 2 of 3" in out
    assert "1. Terse" in out
    assert result == "Winding"


def test_ask_choice_plain_default_on_empty(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert ui.ask_choice("Q?", ["A", "B"], 1, 1) == "A"


def test_ask_choice_plain_reprompts_on_garbage(cap, plain, monkeypatch):
    answers = iter(["banana", "9", "1"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert ui.ask_choice("Q?", ["A", "B"], 1, 1) == "A"
    assert "Please enter a number" in cap.getvalue()


def test_ask_choice_requires_options():
    with pytest.raises(ValueError):
        ui.ask_choice("Q?", [], 1, 1)


def test_ask_choice_interactive_arrow_keys(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["down", "down", "up", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    result = ui.ask_choice("How do you write?", ["Terse", "Winding", "Both"], 2, 3)
    assert result == "Winding"
    out = ANSI_RE.sub("", rich_cap.getvalue())
    assert "Winding" in out


def test_ask_choice_interactive_ctrl_c(monkeypatch, rich_cap):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    monkeypatch.setattr(ui, "_read_key", lambda: "interrupt")
    with pytest.raises(KeyboardInterrupt):
        ui.ask_choice("Q?", ["A", "B"], 1, 1)


def test_slider_bar_shape():
    assert ui.slider_bar(0, 10, 0, 11).startswith("●")
    assert ui.slider_bar(0, 10, 10, 11).endswith("●")
    bar = ui.slider_bar(0, 10, 5, 11)
    assert bar.count("●") == 1
    assert len(bar) == 11
    assert bar.index("●") == 5


def test_ask_slider_plain(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "7")
    assert ui.ask_slider("Humor", 0, 10, 3, "0 = deadpan, 10 = unhinged") == 7
    out = cap.getvalue()
    assert "Humor (0-10)" in out
    assert "0 = deadpan" in out


def test_ask_slider_plain_clamps_and_reprompts(cap, plain, monkeypatch):
    answers = iter(["99", "abc", "4"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert ui.ask_slider("Humor", 0, 10, 3, "") == 4
    assert "between 0 and 10" in cap.getvalue()


def test_ask_slider_plain_default_on_empty(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert ui.ask_slider("Humor", 0, 10, 3, "") == 3


def test_ask_slider_interactive(monkeypatch, rich_cap):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["right", "right", "left", "right", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    assert ui.ask_slider("Humor", 0, 10, 5, "help text") == 7


def test_ask_slider_interactive_home_end(monkeypatch, rich_cap):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["end", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    assert ui.ask_slider("Humor", 0, 10, 5, "") == 10


# --------------------------------------------------------------------------
# ask_text / confirm
# --------------------------------------------------------------------------


def test_ask_text_plain_default(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "")
    assert ui.ask_text("Name", default="ada") == "ada"


def test_ask_text_plain_value(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "  grace  ")
    assert ui.ask_text("Name") == "grace"


def test_ask_text_password_does_not_echo_default(cap, plain, monkeypatch):
    captured = {}

    def fake_input(prompt=""):
        captured["prompt"] = prompt
        return "secret"

    monkeypatch.setattr("builtins.input", fake_input)
    ui.ask_text("API key", default="AIzaTOPSECRET", password=True)
    assert "AIzaTOPSECRET" not in captured["prompt"]


def test_confirm_plain(cap, plain, monkeypatch):
    answers = iter(["", "y", "n", "maybe", "YES"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    assert ui.confirm("Send?", default=True) is True
    assert ui.confirm("Send?") is True
    assert ui.confirm("Send?") is False
    assert ui.confirm("Send?") is True  # "maybe" reprompts, then "YES"


# --------------------------------------------------------------------------
# tables and messages
# --------------------------------------------------------------------------


def test_samples_table_plain(cap, plain):
    samples = [
        FakeSample("commit", "git log a1b2c3d", tokens=120),
        FakeSample("doc", "README.md", tokens=380),
    ]
    ui.samples_table(samples)
    out = cap.getvalue()
    assert "commit" in out and "README.md" in out
    assert "500" in out  # total
    assert "TOTAL" in out


def test_samples_table_rich_totals(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.samples_table([FakeSample("commit", "git log a1b2c3d", tokens=120)])
    out = ANSI_RE.sub("", rich_cap.getvalue())
    assert "Kind" in out and "Tokens" in out and "120" in out
    assert "1 samples" in out


def test_findings_table_plain(cap, plain):
    findings = [
        FakeFinding("aws-access-key", "README.md", 12, "<REDACTED:aws-access-key>", "high"),
        FakeFinding("jwt", "notes.md", 4, "<REDACTED:jwt>", "low"),
    ]
    ui.findings_table(findings)
    out = cap.getvalue()
    assert "aws-access-key" in out
    assert "<REDACTED:aws-access-key>" in out
    assert "high" in out


def test_findings_table_empty_is_success(cap, plain):
    ui.findings_table([])
    assert "No potential secrets" in cap.getvalue()


def test_findings_table_rich_marks_high_red(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.findings_table([FakeFinding("aws-access-key", "a.md", 1, "<REDACTED>", "high")])
    raw = rich_cap.getvalue()
    assert "HIGH" in ANSI_RE.sub("", raw)
    assert "\x1b[1;31m" in raw or "31m" in raw  # bold red somewhere


def test_messages_plain(cap, plain):
    ui.error("it broke")
    ui.success("it worked")
    ui.hint("try again")
    out = cap.getvalue()
    assert "ERROR: it broke" in out
    assert "OK: it worked" in out
    assert "hint: try again" in out
    assert "✓" not in out and "✗" not in out


# --------------------------------------------------------------------------
# dust
# --------------------------------------------------------------------------


def test_dust_is_noop_when_plain(cap, plain):
    with ui.dust():
        ui.hint("still printing")
    out = cap.getvalue()
    assert "hint: still printing" in out
    for glyph in ui.DUST_GLYPHS:
        assert glyph not in out


def test_dust_field_motes_fall_and_recycle():
    field = ui._DustField(width=30, height=4)
    assert len(field.motes) >= 7
    for _ in range(200):
        field.step()
    assert all(-3.0 <= m.y < field.height for m in field.motes)
    assert all(0 <= m.x < field.width for m in field.motes)
    assert all(m.glyph in ui.DUST_GLYPHS for m in field.motes)


def test_dust_field_render_is_bounded():
    field = ui._DustField(width=20, height=3)
    buf = io.StringIO()
    Console(file=buf, force_terminal=False, width=40, no_color=True).print(field.render())
    lines = buf.getvalue().rstrip("\n").split("\n")
    assert len(lines) == 3


def test_dust_starts_and_stops_cleanly(monkeypatch, rich_cap):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    import threading

    before = threading.active_count()
    with ui.dust(height=3, fps=30):
        pass
    # the animation thread is joined on exit
    for _ in range(50):
        if threading.active_count() <= before:
            break
        __import__("time").sleep(0.02)
    assert threading.active_count() <= before


def test_dust_stops_on_exception(monkeypatch, rich_cap):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    import threading

    before = threading.active_count()
    with pytest.raises(KeyboardInterrupt):
        with ui.dust(height=3, fps=30):
            raise KeyboardInterrupt
    for _ in range(50):
        if threading.active_count() <= before:
            break
        __import__("time").sleep(0.02)
    assert threading.active_count() <= before


# --------------------------------------------------------------------------
# _FdStream (the unbuffered fd reader used for real terminal input)
# --------------------------------------------------------------------------


def test_fd_stream_reads_escape_sequences_whole():
    """Regression: a buffered read swallows the tail of an escape sequence."""
    import os

    r, w = os.pipe()
    try:
        os.write(w, b"\x1b[A\x1b[Cz")
        stream = ui._FdStream(r)
        assert ui.read_key_from(stream) == "up"
        assert ui.read_key_from(stream) == "right"
        assert ui.read_key_from(stream) == "z"
    finally:
        os.close(r)
        os.close(w)


def test_fd_stream_read_on_closed_fd_is_empty():
    import os

    r, w = os.pipe()
    os.close(r)
    os.close(w)
    assert ui._FdStream(r).read(1) == ""


# --------------------------------------------------------------------------
# note() / welcome() / dead_end() / next_steps()
# --------------------------------------------------------------------------


def test_note_plain(cap, plain):
    ui.note("What this does", ["line one", "", "line two"])
    out = cap.getvalue()
    assert "What this does" in out
    assert "line one" in out
    assert "line two" in out
    assert "╭" not in out


def test_note_rich_is_boxed(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.note("Heading", ["body"])
    out = ANSI_RE.sub("", rich_cap.getvalue())
    assert "Heading" in out
    assert "body" in out
    assert "─" in out


def test_welcome_explains_the_output(cap, plain):
    ui.welcome()
    out = cap.getvalue()
    assert "writes one file" in out
    assert "Nothing is deleted" in out


def test_dead_end_numbers_the_next_actions(cap, plain):
    ui.dead_end("Nothing to read.", ["do this", "or do that"])
    out = cap.getvalue()
    assert "ERROR: Nothing to read." in out
    assert "1. do this" in out
    assert "2. or do that" in out


def test_dead_end_rich(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.dead_end("Nope.", ["first thing", "second thing"])
    out = ANSI_RE.sub("", rich_cap.getvalue())
    assert "Nope." in out
    assert "1." in out and "first thing" in out


def test_next_steps_for_a_pasteable_file(cap, plain):
    ui.next_steps("persona.md", False, "ada")
    out = cap.getvalue()
    assert "persona.md" in out
    assert "paste" in out.lower()
    assert "ada" in out


def test_next_steps_for_an_agent_file(cap, plain):
    ui.next_steps("CLAUDE.md", True, "ada")
    out = cap.getvalue()
    assert "automatically" in out
    assert "nothing else to do" in out.lower()


# --------------------------------------------------------------------------
# triage_report()
# --------------------------------------------------------------------------


@dataclass
class FakeScored:
    origin: str
    reason: str
    verdict: str
    score: float = 0.5
    sample: object = None
    file: object = None


KEPT = [
    FakeScored("morning-note.txt", "reads like personal writing", "keep"),
    FakeScored("half-list.md", "part list, part prose", "unsure"),
]
REJECTED = [
    FakeScored("invoice-2411.pdf", "looks like an invoice, not your writing", "drop"),
    FakeScored("shopping.txt", "a list of items, not sentences", "drop"),
]


def test_triage_report_plain_names_everything(cap, plain):
    ui.triage_report(KEPT, REJECTED)
    out = cap.getvalue()
    assert "Using 2 of 4 file(s)." in out
    for item in KEPT + REJECTED:
        assert item.origin in out
    for item in REJECTED:
        assert item.reason in out
    assert "Nothing was deleted" in out


def test_triage_report_rich_names_everything(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    ui.triage_report(KEPT, REJECTED)
    out = ANSI_RE.sub("", rich_cap.getvalue()).replace("\n", " ")
    for item in KEPT + REJECTED:
        assert item.origin in out
    assert "invoice" in out
    assert "Nothing was deleted" in out


def test_triage_report_with_nothing_rejected(cap, plain):
    ui.triage_report(KEPT, [])
    out = cap.getvalue()
    assert "Using 2 of 2 file(s)." in out
    assert "Left out" not in out


def test_triage_report_no_ansi_when_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(ui, "PLAIN", False)
    buf = io.StringIO()
    monkeypatch.setattr(
        ui, "console", Console(file=buf, force_terminal=True, no_color=True, width=80)
    )
    ui.welcome()
    ui.note("t", ["a"])
    ui.dead_end("x", ["y", "z"])
    ui.triage_report(KEPT, REJECTED)
    ui.next_steps("persona.md", False, "ada")
    assert ANSI_RE.search(buf.getvalue()) is None


def test_origin_of_falls_back_to_sample_and_file():
    @dataclass
    class Bare:
        origin: str = ""
        sample: object = None
        file: object = None

    assert ui.origin_of(Bare(origin="a.txt")) == "a.txt"
    assert ui.origin_of(Bare(sample=FakeSample("file", "b.txt"))) == "b.txt"
    assert ui.origin_of(Bare(file=("c.png", "image/png", b""))) == "c.png"
    assert ui.origin_of(Bare()) == "(unnamed)"


# --------------------------------------------------------------------------
# ask_multi()
# --------------------------------------------------------------------------


def test_parse_selection():
    assert ui._parse_selection("1,3", 3) == [0, 2]
    assert ui._parse_selection("2 2 1", 3) == [1, 0]
    assert ui._parse_selection("", 3) == []
    assert ui._parse_selection("4", 3) is None
    assert ui._parse_selection("x", 3) is None


def test_ask_multi_plain_defaults_to_none(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "")
    assert ui.ask_multi("Put any back?", ["a", "b"]) == []
    assert "1. a" in cap.getvalue()


def test_ask_multi_plain_picks_numbers(cap, plain, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "2")
    assert ui.ask_multi("Put any back?", ["a", "b"]) == [1]


def test_ask_multi_plain_reprompts_on_garbage(cap, plain, monkeypatch):
    answers = iter(["nine", "1"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    assert ui.ask_multi("Put any back?", ["a", "b"]) == [0]
    assert "Please enter numbers" in cap.getvalue()


def test_ask_multi_plain_eof_is_none(cap, plain, monkeypatch):
    def boom(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert ui.ask_multi("Put any back?", ["a", "b"]) == []


def test_ask_multi_with_no_options_is_empty():
    assert ui.ask_multi("Put any back?", []) == []


def test_ask_multi_interactive_space_toggles(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["space", "down", "down", "space", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    assert ui.ask_multi("Put any back?", ["a", "b", "c"]) == [0, 2]


def test_ask_multi_interactive_untoggles(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["space", "space", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    assert ui.ask_multi("Put any back?", ["a", "b"]) == []


def test_ask_multi_interactive_digit_toggles(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    keys = iter(["2", "enter"])
    monkeypatch.setattr(ui, "_read_key", lambda: next(keys))
    assert ui.ask_multi("Put any back?", ["a", "b"]) == [1]


def test_ask_multi_interactive_ctrl_c(rich_cap, monkeypatch):
    monkeypatch.setattr(ui, "is_plain", lambda: False)
    monkeypatch.setattr(ui, "_interactive", lambda: True)
    monkeypatch.setattr(ui, "_read_key", lambda: "interrupt")
    with pytest.raises(KeyboardInterrupt):
        ui.ask_multi("Put any back?", ["a", "b"])


def test_ask_multi_claims_the_live_region(monkeypatch):
    monkeypatch.setattr(ui, "PLAIN", True)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    ui._live_owner.clear()
    with pytest.raises(ui.LiveConflictError):
        with ui.stages("t"):
            ui.ask_multi("q", ["a"])
    ui._live_owner.clear()
