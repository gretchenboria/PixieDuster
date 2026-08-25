"""Terminal presentation layer for the PixieDuster CLI.

This module ports the visual identity of the Streamlit app (``app.py``) to the
terminal: gold on deep purple, a Cinzel-flavoured wordmark, falling pixie dust
and a gold-bordered "CERTIFICATE OF PERSONA".

Rich + stdlib only -- no Textual, no readchar, no questionary.

Every public function degrades to plain, ANSI-free text when any of the
following is true:

* ``sys.stdout`` is not a TTY (piped to a file, running in CI),
* the ``NO_COLOR`` environment variable is set,
* ``ui.PLAIN`` has been set to ``True`` (the ``--plain`` flag).
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Sequence

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich import box

__all__ = [
    "PLAIN",
    "console",
    "is_plain",
    "banner",
    "dust",
    "stages",
    "ask_choice",
    "ask_slider",
    "ask_text",
    "confirm",
    "certificate",
    "samples_table",
    "findings_table",
    "error",
    "success",
    "hint",
    "decode_key",
    "STAGE_NAMES",
]

# --------------------------------------------------------------------------
# Palette (lifted from the app.py CSS block)
# --------------------------------------------------------------------------

GOLD = "#ffd700"
DIM_GOLD = "#daa520"
LILAC = "#e2d1f9"
MAUVE = "#d1c4e9"
PURPLE = "#2b1845"
DEEP = "#0f081c"
PIXIE_PURPLE = "#a678d6"  # legible tail for the gold->purple gradient

DUST_GLYPHS = "·✦*✧⋆"

#: The processing steps the web app shows while the persona is generated.
STAGE_NAMES = [
    "Inspecting your writing samples",
    "Formulating profiling questions",
    "Evaluating Big Five personality traits",
    "Analyzing LIWC syntax and pronoun orientation",
    "Assessing cognitive style",
    "Mapping sociolinguistics",
]

#: Set to True by ``--plain`` to force text-only output.
PLAIN = False

console: Console = Console()


def is_plain() -> bool:
    """Return True when all decoration must be suppressed.

    True if ``PLAIN`` is set, ``NO_COLOR`` is in the environment, or stdout is
    not an interactive terminal.
    """
    if PLAIN:
        return True
    if os.environ.get("NO_COLOR"):
        return True
    try:
        if not sys.stdout.isatty():
            return True
    except Exception:  # pragma: no cover - exotic stdout replacements
        return True
    return False


def _out() -> Console:
    """The console to write to (indirection so tests can swap it out)."""
    return console


def _plain_print(text: str = "") -> None:
    """Print without any markup interpretation or styling."""
    _out().print(Text(text))


# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _lerp(a: str, b: str, t: float) -> str:
    """Linearly interpolate between two hex colours. ``t`` in [0, 1]."""
    t = max(0.0, min(1.0, t))
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex(
        (
            round(ar + (br - ar) * t),
            round(ag + (bg - ag) * t),
            round(ab + (bb - ab) * t),
        )
    )


def gradient(stops: Sequence[str], n: int) -> list[str]:
    """Return ``n`` hex colours interpolated across the given colour stops."""
    if n <= 0:
        return []
    if n == 1 or len(stops) == 1:
        return [stops[0]] * n
    out: list[str] = []
    segments = len(stops) - 1
    for i in range(n):
        pos = (i / (n - 1)) * segments
        seg = min(int(pos), segments - 1)
        out.append(_lerp(stops[seg], stops[seg + 1], pos - seg))
    return out


# --------------------------------------------------------------------------
# banner()
# --------------------------------------------------------------------------

# 5-row, 5-column block font. Only the letters of PIXIEDUSTER are defined.
_FONT: dict[str, list[str]] = {
    "P": ["█████", "█   █", "█████", "█    ", "█    "],
    "I": ["█████", "  █  ", "  █  ", "  █  ", "█████"],
    "X": ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
    "E": ["█████", "█    ", "████ ", "█    ", "█████"],
    "D": ["████ ", "█   █", "█   █", "█   █", "████ "],
    "U": ["█   █", "█   █", "█   █", "█   █", "█████"],
    "S": ["█████", "█    ", "█████", "    █", "█████"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    "R": ["█████", "█   █", "████ ", "█  █ ", "█   █"],
}

WORDMARK = "PIXIEDUSTER"
TAGLINE = "Your Fairy Prompt-Mother"


def _wordmark_rows(word: str = WORDMARK) -> list[str]:
    """Render ``word`` as 5 rows of block characters (6 cols per letter)."""
    rows: list[str] = []
    for r in range(5):
        rows.append("".join(_FONT[ch][r] + " " for ch in word).rstrip())
    return rows


def banner() -> None:
    """Print the gradient gold->purple ASCII wordmark and the tagline.

    Fits inside 80 columns (the wordmark is 65 cells wide).
    """
    out = _out()
    if is_plain():
        _plain_print(WORDMARK)
        _plain_print(TAGLINE)
        _plain_print()
        return

    rows = _wordmark_rows()
    width = max(len(r) for r in rows)
    cols = gradient([GOLD, DIM_GOLD, PIXIE_PURPLE], width)

    lines: list[RenderableType] = []
    for row in rows:
        text = Text()
        for x, ch in enumerate(row.ljust(width)):
            if ch == " ":
                text.append(" ")
            else:
                text.append(ch, style=cols[x])
        lines.append(Align.center(text))

    sparkle = Text()
    for i, ch in enumerate("·  ✦  ⋆  ✧  ✦  ⋆  ·"):
        sparkle.append(ch, style=GOLD if i % 3 else DIM_GOLD)

    tag = Text(TAGLINE, style=f"italic {LILAC}")

    out.print()
    for line in lines:
        out.print(line)
    out.print(Align.center(sparkle))
    out.print(Align.center(tag))
    out.print()


# --------------------------------------------------------------------------
# dust()
# --------------------------------------------------------------------------


@dataclass
class _Mote:
    x: int
    y: float
    speed: float
    glyph: str
    style: str


class _DustField:
    """A bounded region of falling pixie dust, rendered on demand."""

    def __init__(self, width: int, height: int, density: int | None = None) -> None:
        import random

        self._random = random.Random()
        self.width = max(10, width)
        self.height = max(2, height)
        self.count = density or max(8, self.width // 4)
        self.motes = [self._spawn(seed=True) for _ in range(self.count)]

    def _spawn(self, seed: bool = False) -> _Mote:
        r = self._random
        dim = r.choice([GOLD, GOLD, DIM_GOLD, "white", f"dim {DIM_GOLD}", "dim white"])
        return _Mote(
            x=r.randrange(self.width),
            y=r.uniform(0, self.height) if seed else -r.uniform(0.0, 2.0),
            speed=r.uniform(0.15, 0.85),
            glyph=r.choice(DUST_GLYPHS),
            style=dim,
        )

    def step(self) -> None:
        for i, mote in enumerate(self.motes):
            mote.y += mote.speed
            if mote.y >= self.height:
                self.motes[i] = self._spawn()

    def render(self) -> RenderableType:
        grid = [[(" ", "") for _ in range(self.width)] for _ in range(self.height)]
        for mote in self.motes:
            row = int(mote.y)
            if 0 <= row < self.height and 0 <= mote.x < self.width:
                grid[row][mote.x] = (mote.glyph, mote.style)
        lines: list[Text] = []
        for row in grid:
            text = Text()
            for ch, style in row:
                text.append(ch, style=style or None)
            lines.append(text)
        return Group(*lines)


class LiveConflictError(RuntimeError):
    """Raised when two Live-owning widgets are nested.

    Rich drives a single Live region per console. ``dust()``, ``stages()``,
    ``ask_choice()`` and ``ask_slider()`` each need it, so nesting any two of
    them corrupts the display -- historically in silent, hard-to-trace ways
    rather than with an error. This makes the mistake loud at the call site.
    """


_live_owner: list[str] = []


@contextmanager
def _own_live(name: str) -> Iterator[None]:
    """Claim the console's single Live region for the duration of the block."""
    if _live_owner:
        raise LiveConflictError(
            f"{name}() cannot run inside {_live_owner[-1]}(): Rich drives one Live "
            f"region per console, so nesting them breaks the display. Close "
            f"{_live_owner[-1]}() first. The convention this enforces: dust() runs "
            f"during `chat`, stages() during `clone`."
        )
    _live_owner.append(name)
    try:
        yield
    finally:
        _live_owner.pop()


def live_owner() -> str | None:
    """Name of the widget currently holding the Live region, if any."""
    return _live_owner[-1] if _live_owner else None


def _guard_cm(name: str):
    """Wrap a context manager so it claims the single Live region."""
    def deco(fn):
        @functools.wraps(fn)
        @contextmanager
        def wrapper(*args, **kwargs):
            with _own_live(name), fn(*args, **kwargs) as value:
                yield value
        return wrapper
    return deco


def _guard_fn(name: str):
    """Wrap a plain function so it claims the single Live region."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with _own_live(name):
                return fn(*args, **kwargs)
        return wrapper
    return deco


@_guard_cm("dust")
@contextmanager
def dust(height: int = 6, fps: float = 10.0) -> Iterator[None]:
    """Run a falling-pixie-dust animation in its own bounded Live region.

    No-op when :func:`is_plain`. The region is transient, so it leaves no trace
    when the block exits, and it is torn down cleanly on ``Ctrl-C``.
    """
    if is_plain():
        yield
        return

    out = _out()
    field = _DustField(width=max(20, out.size.width - 2), height=height)
    stop = threading.Event()
    live = Live(
        field.render(),
        console=out,
        refresh_per_second=max(1.0, fps),
        transient=True,
    )

    def _run() -> None:
        interval = 1.0 / max(1.0, fps)
        while not stop.is_set():
            field.step()
            try:
                live.update(field.render())
            except Exception:  # pragma: no cover - console torn down mid-frame
                break
            stop.wait(interval)

    thread = threading.Thread(target=_run, name="pixiedust", daemon=True)
    live.start()
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)
        try:
            live.stop()
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------
# stages()
# --------------------------------------------------------------------------

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _StageList:
    """Renderable step list: gold check for done, spinner for the active step."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.done: list[str] = []
        self.current: str | None = None
        self.icons: dict[str, str] = {}

    def start(self, text: str, icon: str | None = None) -> None:
        if self.current is not None:
            self.done.append(self.current)
        self.current = text
        if icon:
            self.icons[text] = icon

    def finish(self) -> None:
        if self.current is not None:
            self.done.append(self.current)
            self.current = None

    def __rich__(self) -> RenderableType:
        frame = _SPINNER_FRAMES[int(time.monotonic() * 10) % len(_SPINNER_FRAMES)]
        lines: list[Text] = []
        for text in self.done:
            line = Text("  ")
            line.append("✓", style=f"bold {GOLD}")
            line.append(" ")
            line.append(text, style=f"dim {MAUVE}")
            lines.append(line)
        if self.current is not None:
            line = Text("  ")
            line.append(frame, style=f"bold {GOLD}")
            line.append(" ")
            line.append(self.current, style=f"bold {LILAC}")
            line.append(" …", style=f"dim {DIM_GOLD}")
            lines.append(line)
        head = Text(self.title, style=f"bold {GOLD}")
        return Panel(
            Group(head, Text(""), *lines),
            box=box.ROUNDED,
            border_style=DIM_GOLD,
            padding=(0, 2),
        )


@_guard_cm("stages")
@contextmanager
def stages(title: str) -> Iterator[Callable[..., None]]:
    """Yield a ``stage(text, icon=None)`` callable driving the step display.

    Each call ticks the previous step to a gold ``✓`` and starts a spinner on
    the new one. Falls back to one plain line per step.
    """
    out = _out()

    if is_plain():
        state: dict[str, str | None] = {"current": None}

        def plain_stage(text: str, icon: str | None = None) -> None:
            if state["current"] is not None:
                _plain_print(f"[done] {state['current']}")
            state["current"] = text
            _plain_print(f"[....] {text}")

        _plain_print(title)
        try:
            yield plain_stage
        finally:
            if state["current"] is not None:
                _plain_print(f"[done] {state['current']}")

        return

    steps = _StageList(title)
    live = Live(steps, console=out, refresh_per_second=12, transient=False)
    live.start()
    try:
        yield steps.start
    finally:
        steps.finish()
        try:
            live.update(steps)
            live.stop()
        except Exception:  # pragma: no cover
            pass


# --------------------------------------------------------------------------
# Raw keyboard input
# --------------------------------------------------------------------------

_ESC_MAP = {
    "[A": "up",
    "[B": "down",
    "[C": "right",
    "[D": "left",
    "OA": "up",
    "OB": "down",
    "OC": "right",
    "OD": "left",
    "[H": "home",
    "[F": "end",
    "[1~": "home",
    "[4~": "end",
}


def decode_key(seq: str) -> str:
    """Map a raw terminal byte sequence to a symbolic key name.

    Pure function -- the whole point is that it is testable without a TTY.
    Returns one of ``up``/``down``/``left``/``right``/``home``/``end``/
    ``enter``/``escape``/``backspace``/``tab``/``space``/``interrupt``, or the
    literal character for anything else. Unknown sequences return ``""``.
    """
    if not seq:
        return ""
    if seq in ("\r", "\n", "\r\n"):
        return "enter"
    if seq == "\x03":
        return "interrupt"
    if seq == "\x04":
        return "eof"
    if seq in ("\x7f", "\b"):
        return "backspace"
    if seq == "\t":
        return "tab"
    if seq == " ":
        return "space"
    if seq == "\x1b":
        return "escape"
    if seq.startswith("\x1b"):
        return _ESC_MAP.get(seq[1:], "")
    # Windows getwch() two-part sequences.
    if seq[0] in ("\x00", "\xe0") and len(seq) == 2:
        return {"H": "up", "P": "down", "K": "left", "M": "right",
                "G": "home", "O": "end"}.get(seq[1], "")
    if len(seq) == 1:
        lowered = seq.lower()
        if lowered == "k":
            return "up"
        if lowered == "j":
            return "down"
        if lowered == "h":
            return "left"
        if lowered == "l":
            return "right"
        if lowered == "q":
            return "escape"
        return seq
    return ""


class _FdStream:
    """Unbuffered, ``read``-compatible view onto a file descriptor."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        return self._fd

    def read(self, n: int = 1) -> str:
        try:
            data = os.read(self._fd, n)
        except OSError:  # pragma: no cover - fd closed under us
            return ""
        return data.decode("utf-8", "replace")


def _read_pending(stream: Any, limit: int = 6) -> str:
    """Read the remainder of an escape sequence from ``stream``."""
    try:
        import select

        fd = stream.fileno()
        is_tty = os.isatty(fd)
    except Exception:
        is_tty = False

    if is_tty:
        import select

        buf = ""
        while len(buf) < limit:
            ready, _, _ = select.select([stream], [], [], 0.05)
            if not ready:
                break
            ch = stream.read(1)
            if not ch:
                break
            buf += ch
            if ch.isalpha() or ch == "~":
                break
        return buf

    # Fake / non-tty stream (tests): CSI sequences are 2 chars, or end with '~'.
    buf = stream.read(2) or ""
    if buf.endswith("~"):
        return buf
    if buf and not (buf[-1].isalpha() or buf[-1] == "~"):
        extra = stream.read(1) or ""
        buf += extra
    return buf


def read_key_from(stream: Any) -> str:
    """Read one symbolic key from an already-raw ``stream``.

    Factored out of :func:`_read_key` so it can be driven by a fake stream in
    the tests.
    """
    ch = stream.read(1)
    if not ch:
        return "eof"
    if ch == "\x1b":
        return decode_key("\x1b" + _read_pending(stream))
    if ch in ("\x00", "\xe0"):
        return decode_key(ch + (stream.read(1) or ""))
    return decode_key(ch)


def _read_key() -> str:
    """Read a single keypress from the real terminal, restoring state after."""
    if os.name == "nt":  # pragma: no cover - Windows path
        try:
            import msvcrt
        except ImportError:
            return "eof"
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return decode_key(ch + msvcrt.getwch())
        return decode_key(ch)

    try:
        import termios
        import tty
    except ImportError:  # pragma: no cover - no POSIX termios
        line = sys.stdin.readline()
        return "enter" if line else "eof"

    fd = sys.stdin.fileno()
    try:
        saved = termios.tcgetattr(fd)
    except Exception:  # pragma: no cover - stdin is not a tty
        line = sys.stdin.readline()
        return "enter" if line else "eof"
    try:
        tty.setraw(fd)
        # Read straight from the file descriptor: sys.stdin is buffered, and a
        # buffered read swallows the tail of an escape sequence before select()
        # can see it, which turns every arrow key into a bare ESC.
        return read_key_from(_FdStream(fd))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _interactive() -> bool:
    """True when we can actually read raw keys from the user."""
    if is_plain():
        return False
    try:
        return sys.stdin.isatty()
    except Exception:  # pragma: no cover
        return False


# --------------------------------------------------------------------------
# ask_choice()
# --------------------------------------------------------------------------


def _choice_renderable(
    question: str, options: Sequence[str], selected: int, index: int, total: int
) -> RenderableType:
    head = Text()
    head.append(f"Q {index} of {total}", style=f"bold {GOLD}")
    head.append("   ")
    head.append(question, style=f"bold {LILAC}")

    rows: list[Text] = []
    for i, option in enumerate(options):
        if i == selected:
            row = Text("  ")
            row.append(f" ❯ {option} ", style=f"bold {DEEP} on {GOLD}")
        else:
            row = Text("  ")
            row.append(f"   {option} ", style=MAUVE)
        rows.append(row)

    foot = Text("  ↑/↓ move · enter select", style=f"dim {DIM_GOLD}")
    return Panel(
        Group(head, Text(""), *rows, Text(""), foot),
        box=box.ROUNDED,
        border_style=DIM_GOLD,
        padding=(0, 1),
    )


@_guard_fn("ask_choice")
def ask_choice(question: str, options: list[str], index: int, total: int) -> str:
    """Single-select with arrow keys; numbered prompt when plain.

    Returns the chosen option string. ``index``/``total`` drive the
    "Q 2 of 3" indicator.
    """
    if not options:
        raise ValueError("ask_choice requires at least one option")

    out = _out()

    if not _interactive():
        _plain_print(f"Q {index} of {total}: {question}")
        for i, option in enumerate(options, 1):
            _plain_print(f"  {i}. {option}")
        while True:
            try:
                raw = input(f"Select 1-{len(options)} [1]: ").strip()
            except EOFError:
                return options[0]
            if not raw:
                return options[0]
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1]
            _plain_print("Please enter a number from the list.")

    selected = 0
    with Live(
        _choice_renderable(question, options, selected, index, total),
        console=out,
        refresh_per_second=20,
        transient=True,
    ) as live:
        while True:
            key = _read_key()
            if key == "up":
                selected = (selected - 1) % len(options)
            elif key == "down":
                selected = (selected + 1) % len(options)
            elif key == "enter":
                break
            elif key == "interrupt":
                raise KeyboardInterrupt
            elif key == "eof":
                break
            elif key.isdigit() and 1 <= int(key) <= len(options):
                selected = int(key) - 1
                break
            live.update(_choice_renderable(question, options, selected, index, total))

    chosen = options[selected]
    answered = Text("  ")
    answered.append("✓", style=f"bold {GOLD}")
    answered.append(f" {question} ", style=f"dim {MAUVE}")
    answered.append(chosen, style=f"bold {GOLD}")
    out.print(answered)
    return chosen


# --------------------------------------------------------------------------
# ask_slider()
# --------------------------------------------------------------------------


def slider_bar(lo: int, hi: int, value: int, width: int = 24) -> str:
    """Return the ``━━━●━━━`` bar string for ``value`` within ``[lo, hi]``."""
    width = max(3, width)
    span = max(1, hi - lo)
    pos = round((value - lo) / span * (width - 1))
    pos = max(0, min(width - 1, pos))
    return "━" * pos + "●" + "━" * (width - 1 - pos)


def _slider_renderable(label: str, lo: int, hi: int, value: int, help: str) -> RenderableType:
    bar = slider_bar(lo, hi, value)
    knob = bar.index("●")

    line = Text("  ")
    line.append(bar[:knob], style=DIM_GOLD)
    line.append("●", style=f"bold {GOLD}")
    line.append(bar[knob + 1 :], style="grey37")
    line.append("   ")
    line.append(str(value), style=f"bold {GOLD}")
    line.append(f" / {hi}", style=f"dim {MAUVE}")

    head = Text(label, style=f"bold {LILAC}")
    body: list[RenderableType] = [head, Text(""), line]
    if help:
        body.append(Text(""))
        body.append(Text(f"  {help}", style=MAUVE))
    body.append(Text("  ←/→ adjust · enter accept", style=f"dim {DIM_GOLD}"))
    return Panel(
        Group(*body), box=box.ROUNDED, border_style=DIM_GOLD, padding=(0, 1)
    )


@_guard_fn("ask_slider")
def ask_slider(label: str, lo: int, hi: int, default: int, help: str) -> int:
    """Gold slider driven by left/right arrows; numeric input when plain."""
    value = max(lo, min(hi, default))
    out = _out()

    if not _interactive():
        _plain_print(f"{label} ({lo}-{hi})")
        if help:
            _plain_print(f"  {help}")
        while True:
            try:
                raw = input(f"Value [{value}]: ").strip()
            except EOFError:
                return value
            if not raw:
                return value
            try:
                candidate = int(raw)
            except ValueError:
                _plain_print(f"Please enter a whole number between {lo} and {hi}.")
                continue
            if lo <= candidate <= hi:
                return candidate
            _plain_print(f"Please enter a whole number between {lo} and {hi}.")

    with Live(
        _slider_renderable(label, lo, hi, value, help),
        console=out,
        refresh_per_second=20,
        transient=True,
    ) as live:
        while True:
            key = _read_key()
            if key == "left":
                value = max(lo, value - 1)
            elif key == "right":
                value = min(hi, value + 1)
            elif key == "home":
                value = lo
            elif key == "end":
                value = hi
            elif key in ("enter", "eof"):
                break
            elif key == "interrupt":
                raise KeyboardInterrupt
            live.update(_slider_renderable(label, lo, hi, value, help))

    done = Text("  ")
    done.append("✓", style=f"bold {GOLD}")
    done.append(f" {label} ", style=f"dim {MAUVE}")
    done.append(str(value), style=f"bold {GOLD}")
    out.print(done)
    return value


# --------------------------------------------------------------------------
# ask_text() / confirm()
# --------------------------------------------------------------------------


def ask_text(label: str, default: str | None = None, password: bool = False) -> str:
    """Prompt for a line of text. Never echoes when ``password`` is True."""
    out = _out()
    suffix = f" [{default}]" if default and not password else ""
    if is_plain():
        try:
            raw = input(f"{label}{suffix}: ")
        except EOFError:
            raw = ""
        return raw.strip() or (default or "")

    prompt = Text()
    prompt.append(label, style=f"bold {LILAC}")
    if suffix:
        prompt.append(suffix, style=f"dim {MAUVE}")
    prompt.append(": ", style=GOLD)
    try:
        raw = out.input(prompt, password=password)
    except EOFError:
        raw = ""
    return raw.strip() or (default or "")


def confirm(question: str, default: bool = True) -> bool:
    """Yes/no prompt. Empty input takes ``default``."""
    hint_text = "[Y/n]" if default else "[y/N]"
    while True:
        if is_plain():
            try:
                raw = input(f"{question} {hint_text}: ").strip().lower()
            except EOFError:
                return default
        else:
            prompt = Text()
            prompt.append(question, style=f"bold {LILAC}")
            prompt.append(f" {hint_text}", style=f"dim {DIM_GOLD}")
            prompt.append(": ", style=GOLD)
            try:
                raw = _out().input(prompt).strip().lower()
            except EOFError:
                return default
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


# --------------------------------------------------------------------------
# certificate()
# --------------------------------------------------------------------------

#: Markdown styling for the certificate body, matching the web app's CSS.
_CERT_THEME = Theme(
    {
        "markdown.h1": f"bold {GOLD}",
        "markdown.h2": f"bold {GOLD}",
        "markdown.h3": f"bold {LILAC}",
        "markdown.h4": LILAC,
        "markdown.text": MAUVE,
        "markdown.paragraph": MAUVE,
        "markdown.item.bullet": f"bold {GOLD}",
        "markdown.item.number": f"bold {GOLD}",
        "markdown.strong": f"bold {GOLD}",
        "markdown.emph": f"italic {LILAC}",
        "markdown.block_quote": LILAC,
        "markdown.code": DIM_GOLD,
        "markdown.link": DIM_GOLD,
        "markdown.hr": DIM_GOLD,
    },
    inherit=True,
)

CERT_HEADING = "CERTIFICATE OF PERSONA"
CERT_FOOTER = "✦ Authorized by PixieDuster"


def _spaced(text: str) -> str:
    """Letter-space a heading, the terminal's stand-in for Cinzel Decorative."""
    return " ".join(text)


def _gold_rule(width: int) -> Text:
    """A rule that fades gold at the centre, like the web certificate's <hr>."""
    width = max(4, width)
    text = Text()
    for i in range(width):
        t = 1.0 - abs((i / (width - 1)) * 2 - 1)
        text.append("─", style=_lerp(DEEP, GOLD, t))
    return text


def certificate(persona_md: str, target_name: str) -> None:
    """Print the terminal version of the web app's persona certificate."""
    out = _out()

    if is_plain():
        _plain_print("=" * 72)
        _plain_print(CERT_HEADING.center(72))
        _plain_print(f"Officially cloned for: {target_name.upper()}".center(72))
        _plain_print("=" * 72)
        _plain_print()
        _plain_print(persona_md)
        _plain_print()
        _plain_print("-" * 72)
        _plain_print("Authorized by PixieDuster".center(72))
        _plain_print("=" * 72)
        return

    inner = max(30, min(out.size.width, 100) - 10)

    heading = Text(_spaced(CERT_HEADING), style=f"bold {GOLD}")

    sparkle = Text()
    for i, ch in enumerate("⋆  ·  ✦  ·  ⋆"):
        sparkle.append(ch, style=DIM_GOLD if i % 2 else GOLD)

    cloned = Text()
    cloned.append("Officially cloned for: ", style=LILAC)
    cloned.append(target_name.upper(), style=f"bold {GOLD}")

    footer = Text(CERT_FOOTER, style=f"bold {GOLD}")

    body = Markdown(persona_md, style=MAUVE)

    group = Group(
        Align.center(sparkle),
        Text(""),
        Align.center(heading),
        Text(""),
        Align.center(cloned),
        Text(""),
        Align.center(_gold_rule(inner)),
        Text(""),
        body,
        Text(""),
        Align.center(_gold_rule(inner)),
        Text(""),
        Align.center(footer),
    )

    out.print()
    out.push_theme(_CERT_THEME)
    try:
        out.print(
            Panel(
                group,
                box=box.DOUBLE,
                border_style=GOLD,
                padding=(1, 4),
                width=min(out.size.width, 100),
            )
        )
    finally:
        out.pop_theme()
    out.print()


# --------------------------------------------------------------------------
# Tables and messages
# --------------------------------------------------------------------------


def samples_table(samples: Sequence[Any]) -> None:
    """Show mined samples: kind / origin / tokens, with a totals row."""
    out = _out()
    total_tokens = sum(getattr(s, "tokens", 0) or 0 for s in samples)

    if is_plain():
        _plain_print("KIND        ORIGIN                                   TOKENS")
        for s in samples:
            _plain_print(
                f"{str(s.kind)[:10]:<11} {str(s.origin)[:40]:<40} "
                f"{getattr(s, 'tokens', 0) or 0:>7}"
            )
        _plain_print(f"{'TOTAL':<11} {f'{len(samples)} samples':<40} {total_tokens:>7}")
        return

    table = Table(
        box=box.SIMPLE_HEAD,
        border_style=DIM_GOLD,
        header_style=f"bold {GOLD}",
        show_footer=True,
        footer_style=f"bold {DIM_GOLD}",
    )
    table.add_column("Kind", style=LILAC, footer="TOTAL")
    table.add_column("Origin", style=MAUVE, overflow="ellipsis", footer=f"{len(samples)} samples")
    table.add_column("Tokens", justify="right", style=GOLD, footer=str(total_tokens))
    for s in samples:
        table.add_row(str(s.kind), str(s.origin), str(getattr(s, "tokens", 0) or 0))
    out.print(table)


_SEVERITY_STYLE = {"high": "bold red", "medium": DIM_GOLD, "low": MAUVE}


def findings_table(findings: Sequence[Any]) -> None:
    """Show secret-scan findings, severity-coloured (red for high)."""
    out = _out()

    if not findings:
        success("No potential secrets found in the outbound text.")
        return

    if is_plain():
        _plain_print("SEVERITY  RULE                 ORIGIN                    LINE  EXCERPT")
        for f in findings:
            _plain_print(
                f"{str(f.severity)[:8]:<9} {str(f.rule)[:20]:<20} "
                f"{str(f.origin)[:25]:<25} {f.line:>5}  {f.excerpt}"
            )
        return

    table = Table(
        box=box.SIMPLE_HEAD,
        border_style=DIM_GOLD,
        header_style=f"bold {GOLD}",
        title="Potential secrets",
        title_style=f"bold {GOLD}",
    )
    table.add_column("Severity")
    table.add_column("Rule", style=LILAC)
    table.add_column("Origin", style=MAUVE, overflow="ellipsis")
    table.add_column("Line", justify="right", style=MAUVE)
    table.add_column("Excerpt", style=MAUVE, overflow="fold")
    for f in findings:
        sev = str(f.severity).lower()
        table.add_row(
            Text(sev.upper(), style=_SEVERITY_STYLE.get(sev, MAUVE)),
            str(f.rule),
            str(f.origin),
            str(f.line),
            str(f.excerpt),
        )
    out.print(table)


def error(msg: str) -> None:
    """Print an error message."""
    if is_plain():
        _plain_print(f"ERROR: {msg}")
        return
    text = Text()
    text.append("✗ ", style="bold red")
    text.append(msg, style="red")
    _out().print(text)


def success(msg: str) -> None:
    """Print a success message."""
    if is_plain():
        _plain_print(f"OK: {msg}")
        return
    text = Text()
    text.append("✓ ", style=f"bold {GOLD}")
    text.append(msg, style=LILAC)
    _out().print(text)


def hint(msg: str) -> None:
    """Print a dim advisory line."""
    if is_plain():
        _plain_print(f"hint: {msg}")
        return
    text = Text()
    text.append("✦ ", style=f"dim {DIM_GOLD}")
    text.append(msg, style=f"dim {MAUVE}")
    _out().print(text)
