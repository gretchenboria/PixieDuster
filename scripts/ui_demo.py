#!/usr/bin/env python3
"""Manual demo of every pixieduster.ui widget, in sequence.

    .venv-cli/bin/python scripts/ui_demo.py            # full, interactive
    .venv-cli/bin/python scripts/ui_demo.py --no-input # skip the key-driven bits
    .venv-cli/bin/python scripts/ui_demo.py --plain    # the degraded path
    .venv-cli/bin/python scripts/ui_demo.py | cat      # non-tty degradation
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pixieduster import ui


@dataclass
class Sample:
    kind: str
    origin: str
    text: str = ""
    author: str | None = None
    tokens: int = 0


@dataclass
class Finding:
    rule: str
    origin: str
    line: int
    excerpt: str
    severity: str


PERSONA = """# Terminology Standards & Persona

## Voice
Dry, exacting, and faintly amused. Sentences run short and land hard; the
author would rather cut a clause than soften a claim.

## Lexical Fingerprint
- **Pronoun orientation:** heavy first-person singular, almost no "we"
- **Temporal stance:** present tense, occasionally the historical present
- **Hedging:** rare — certainty markers outnumber tentative ones 4:1

## Big Five
| Trait | Reading |
| --- | --- |
| Openness | High |
| Conscientiousness | High |
| Extraversion | Low-mid |

> Write as though the reader is smart and in a hurry.
"""


def pause(seconds: float = 1.2) -> None:
    if sys.stdout.isatty():
        time.sleep(seconds)


def main() -> None:
    if "--plain" in sys.argv:
        ui.PLAIN = True
    interactive = "--no-input" not in sys.argv and sys.stdin.isatty() and not ui.is_plain()

    ui.banner()
    pause()

    ui.hint("Mining the repository for writing samples…")
    samples = [
        Sample("commit", "git log a1b2c3d", tokens=142),
        Sample("commit", "git log 9f8e7d6", tokens=96),
        Sample("doc", "README.md", tokens=410),
        Sample("comment", "pixieduster/ui.py", tokens=88),
        Sample("pr", "gh pr #17", tokens=203),
    ]
    ui.samples_table(samples)
    print()
    pause()

    ui.findings_table(
        [
            Finding("aws-access-key", "notes/scratch.md", 12, "AKIA<REDACTED:aws-access-key>", "high"),
            Finding("generic-secret", "README.md", 88, "token = <REDACTED:generic-secret>", "medium"),
            Finding("jwt", "git log 9f8e7d6", 3, "<REDACTED:jwt>", "low"),
        ]
    )
    print()
    pause()

    with ui.stages("Consulting the fairies") as stage:
        for name in ui.STAGE_NAMES:
            stage(name)
            pause(0.9)
    ui.success("Analysis complete.")
    print()
    pause()

    ui.hint("Falling pixie dust (3 seconds)…")
    with ui.dust(height=7):
        pause(3.0)
    print()

    if interactive:
        answer = ui.ask_choice(
            "Which rhythm best matches the author?",
            ["Staccato — short, punchy sentences", "Winding — long, subordinate clauses", "Both, by mood"],
            2,
            3,
        )
        humor = ui.ask_slider(
            "Humor level", 0, 10, 4, "0 = deadpan technical, 10 = unhinged whimsy"
        )
        name = ui.ask_text("Persona name", default="Ada Lovelace")
        if not ui.confirm("Mint the certificate?", default=True):
            ui.error("Aborted.")
            return
        ui.hint(f"rhythm={answer!r} humor={humor}")
    else:
        name = "Ada Lovelace"
        ui.hint("(interactive widgets skipped)")

    ui.certificate(PERSONA, name)
    ui.success("Wrote AGENTS.md")
    ui.error("…and this is what a failure looks like.")


if __name__ == "__main__":
    main()
