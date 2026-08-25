"""Shared dataclasses for the PixieDuster CLI.

This module is dependency-free on purpose: every other module in the package
may import it, so it must never import from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Sample:
    """One piece of harvested writing that may be sent to the model.

    Attributes:
        kind: One of "commit", "doc", "comment", "pr", "file".
        origin: Human-readable source, e.g. "git log a1b2c3d" or "README.md".
        text: The raw text of the sample.
        author: Email of the author if known.
        tokens: Estimated token count, filled by ``safety.estimate_tokens``.
    """

    kind: str
    origin: str
    text: str
    author: str | None = None
    tokens: int = 0


@dataclass
class Question:
    """A single multiple-choice profiling question put to the user."""

    question: str
    options: list[str] = field(default_factory=list)


@dataclass
class Finding:
    """A potential secret detected in outbound text.

    ``excerpt`` is ALREADY REDACTED and is therefore safe to print or log.
    """

    rule: str
    origin: str
    line: int
    excerpt: str
    severity: str


__all__ = ["Sample", "Question", "Finding"]
