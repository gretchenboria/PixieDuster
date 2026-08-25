"""Load writing samples from arbitrary files and folders.

This is the main way people use PixieDuster: point it at a folder of their own
writing. Not a code repository -- a folder of whatever they happen to have.
Photos of handwritten notes, screenshots of text messages, emails they saved,
old essays, a chat log. Anything with their voice in it.

Text is read directly. Anything the model has to *look* at -- a photo, a
screenshot, a PDF, an email -- is passed through untouched for Gemini to read,
including handwriting.

Text becomes :class:`~pixieduster.types.Sample` objects. Anything the model has
to look at rather than read - PDFs and images - is returned as raw
``(filename, mimetype, bytes)`` tuples for the API's ``inlineData`` parts.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .relevance import DEFAULT_BUDGET_CHARS, Scored, triage
from .types import Sample

#: Extensions read as text and sent inline.
TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".rst", ".text",
    ".csv", ".json", ".log", ".org", ".tex",
    ".eml", ".mbox", ".html", ".htm", ".vtt", ".srt",
}

#: Extensions sent to the model as binary parts. Gemini reads PDFs natively and
#: can transcribe handwriting or chat screenshots from images.
BINARY_SUFFIXES = {
    ".pdf",
    # screenshots and photos -- of handwriting, of a messages thread, of anything
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".heic", ".heif",
    ".tif", ".tiff", ".bmp",
}

#: Per-file ceiling. Above this a text file is truncated and a binary skipped.
MAX_FILE_BYTES = 8 * 1024 * 1024

#: How many files one invocation will take, to keep a stray folder from
#: becoming a 500-file upload.
MAX_FILES = 60


class SourceError(RuntimeError):
    """A path could not be used as a writing sample."""


def _kind_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in BINARY_SUFFIXES:
        return "binary"
    return None


def _mimetype_for(path: Path) -> str:
    guess, _ = mimetypes.guess_type(path.name)
    if guess:
        return guess
    return "application/octet-stream"


def expand(paths: list[Path], *, max_files: int = MAX_FILES) -> list[Path]:
    """Turn a list of files and folders into a flat list of usable files.

    Folders are walked one level deep by default via ``rglob``, skipping hidden
    files, anything inside a dot-directory, and unsupported extensions.

    Raises:
        SourceError: If a path does not exist, or nothing usable was found.
    """
    found: list[Path] = []
    for raw in paths:
        path = raw.expanduser()
        if not path.exists():
            raise SourceError(f"No such file or folder: {path}")

        if path.is_file():
            if _kind_for(path) is None:
                raise SourceError(
                    f"{path.name}: unsupported file type. Supported: "
                    + ", ".join(sorted(TEXT_SUFFIXES | BINARY_SUFFIXES))
                )
            found.append(path)
            continue

        for child in sorted(path.rglob("*")):
            if not child.is_file() or child.is_symlink():
                continue
            if any(part.startswith(".") for part in child.parts):
                continue
            if _kind_for(child) is None:
                continue
            found.append(child)

    if not found:
        raise SourceError(
            "Found no readable writing samples in those paths. Supported types: "
            + ", ".join(sorted(TEXT_SUFFIXES | BINARY_SUFFIXES))
        )

    # Deduplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)

    return unique[:max_files]


def load(
    paths: list[Path],
    *,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_FILE_BYTES,
) -> tuple[list[Sample], list[tuple[str, str, bytes]]]:
    """Load writing samples from files and folders.

    Returns:
        ``(samples, files)`` - text as :class:`Sample` objects, and PDFs and
        images as ``(filename, mimetype, bytes)`` tuples for the API.

    Raises:
        SourceError: If a path is missing or nothing usable was found.
    """
    samples: list[Sample] = []
    files: list[tuple[str, str, bytes]] = []

    for path in expand(paths, max_files=max_files):
        kind = _kind_for(path)
        try:
            size = path.stat().st_size
        except OSError as exc:  # pragma: no cover - permissions, races
            raise SourceError(f"Could not read {path}: {exc}") from None

        if kind == "text":
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise SourceError(f"Could not read {path}: {exc}") from None
            if len(text) > max_bytes:
                text = text[:max_bytes]
            if text.strip():
                samples.append(Sample(kind="file", origin=path.name, text=text))
            continue

        if size > max_bytes:
            # Silently skipping would be worse than saying so.
            raise SourceError(
                f"{path.name} is {size / 1_048_576:.1f} MB, over the "
                f"{max_bytes / 1_048_576:.0f} MB limit for a single file."
            )
        try:
            files.append((path.name, _mimetype_for(path), path.read_bytes()))
        except OSError as exc:
            raise SourceError(f"Could not read {path}: {exc}") from None

    if not samples and not files:
        raise SourceError("Those files were all empty.")

    return samples, files


def load_triaged(
    paths: list[Path],
    *,
    max_files: int = MAX_FILES,
    max_bytes: int = MAX_FILE_BYTES,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> tuple[list[Scored], list[Scored]]:
    """Load writing samples and sort them by how much they look like your voice.

    This is :func:`load` followed by :func:`pixieduster.relevance.triage`. Use
    it instead of :func:`load` anywhere a folder of somebody's real documents
    might be pointed at, which is to say everywhere a person is involved.

    Args:
        budget_chars: Total characters of text one run may send.

    Returns:
        ``(kept, rejected)`` :class:`~pixieduster.relevance.Scored` lists, best
        score first. Nothing is discarded: every loaded file is in one list or
        the other, with a plain-language ``reason``.

    Raises:
        SourceError: As for :func:`load`.
    """
    samples, files = load(paths, max_files=max_files, max_bytes=max_bytes)
    return triage(samples, files, budget_chars=budget_chars)


def unpack(kept: list[Scored]) -> tuple[list[Sample], list[tuple[str, str, bytes]]]:
    """Split a :func:`load_triaged` result back into ``(samples, files)``.

    Lets a caller feed a triaged, possibly user-edited selection straight into
    the same code paths that consume :func:`load`.
    """
    samples = [item.sample for item in kept if item.sample is not None]
    files = [item.file for item in kept if item.file is not None]
    return samples, files


def describe(files: list[tuple[str, str, bytes]]) -> list[str]:
    """One human-readable line per binary file, for the dry-run report."""
    return [
        f"{name}  ({mimetype}, {len(blob) / 1024:.0f} KB) - not text, cannot be scanned"
        for name, mimetype, blob in files
    ]


__all__ = [
    "SourceError",
    "TEXT_SUFFIXES",
    "BINARY_SUFFIXES",
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "expand",
    "load",
    "load_triaged",
    "unpack",
    "describe",
]
