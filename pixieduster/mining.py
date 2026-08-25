"""Repo mining: extract genuine human prose from a git repository.

Every miner here operates on ``git ls-files`` output (so ``.gitignore`` is
respected for free) and never reads a path outside the repository root.
There are no network calls anywhere in this module except the optional
``gh`` subprocess used by :func:`mine_prs`, which fails silently.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import time
import tokenize
from pathlib import Path

from pixieduster.types import Sample

__all__ = [
    "is_git_repo",
    "list_authors",
    "mine_commits",
    "mine_docs",
    "mine_comments",
    "mine_prs",
    "mine_all",
]

# --------------------------------------------------------------------------
# tunables
# --------------------------------------------------------------------------

GIT_TIMEOUT = 30
"""Seconds before a ``git`` subprocess is abandoned."""

GH_TIMEOUT = 20
"""Seconds before the optional ``gh`` subprocess is abandoned."""

MAX_FILE_BYTES = 1_000_000
"""Files larger than this are skipped outright (never voice, always noise)."""

DOC_MIN_CHARS = 80
COMMENT_MIN_CHARS = 60
PR_MIN_CHARS = 80

BLAME_FILE_CAP = 40
"""Most files ``git blame`` will be run on during one author-filtered mine."""

BLAME_WALL_SECONDS = 15.0
"""Overall wall-clock budget for the blame phase; past it we degrade to
whole-file attribution rather than letting ``clone`` look like it has hung."""

BLAME_TIMEOUT = 10
"""Per-file timeout for a single ``git blame``."""

COMMENT_OWNERSHIP_MIN = 0.6
"""Fraction of a comment block's lines the target must own to keep it."""

# Rough share of the character budget each kind may occupy in ``mine_all``.
KIND_SHARE: dict[str, float] = {
    "commit": 0.40,
    "doc": 0.25,
    "comment": 0.20,
    "pr": 0.15,
}

# --------------------------------------------------------------------------
# subprocess helpers
# --------------------------------------------------------------------------


def _run(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Run ``argv`` in ``cwd`` and return ``(returncode, stdout)``.

    Never raises: any failure to launch, or a timeout, yields ``(-1, "")``.
    Uses a list argv (never ``shell=True``) and always sets a timeout.
    """
    env = dict(os.environ)
    # Keep git non-interactive: no credential/editor/pager prompts, ever.
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env["GIT_PAGER"] = "cat"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace")


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    """Run a git command in ``repo``; return stdout, or ``""`` on any failure."""
    code, out = _run(["git", *args], repo, timeout)
    return out if code == 0 else ""


def _gh(repo: Path, *args: str, timeout: int = GH_TIMEOUT) -> tuple[int, str]:
    """Run a ``gh`` command in ``repo``; ``(-1, "")`` if gh is not installed."""
    return _run(["gh", *args], repo, timeout)


# --------------------------------------------------------------------------
# path safety
# --------------------------------------------------------------------------


def _safe_path(repo_root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` under ``repo_root``, refusing anything that escapes.

    Returns ``None`` for symlinks, non-regular files, oversized files, and any
    path whose resolved location falls outside ``repo_root``.
    """
    if not rel or rel.startswith("/") or "\x00" in rel:
        return None
    candidate = repo_root / rel
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return None
        resolved = candidate.resolve(strict=True)
        root = repo_root.resolve(strict=True)
        if not resolved.is_relative_to(root):
            return None
        if resolved.stat().st_size > MAX_FILE_BYTES:
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _read_text(path: Path) -> str:
    """Read a file as text, replacing undecodable bytes. ``""`` on failure."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in data[:8000]:  # crude binary sniff
        return ""
    return data.decode("utf-8", errors="replace")


def _tracked_files(repo: Path) -> list[str]:
    """Every file tracked by git, as repo-relative POSIX paths."""
    out = _git(repo, "ls-files", "-z")
    return [p for p in out.split("\0") if p]


# --------------------------------------------------------------------------
# public: repo/author basics
# --------------------------------------------------------------------------


def is_git_repo(path: Path) -> bool:
    """True if ``path`` is inside a git working tree."""
    path = Path(path)
    if not path.is_dir():
        return False
    code, out = _run(
        ["git", "rev-parse", "--is-inside-work-tree"], path, GIT_TIMEOUT
    )
    return code == 0 and out.strip() == "true"


def list_authors(repo: Path) -> list[tuple[str, str, int]]:
    """Return ``(email, name, commit_count)`` triples, most prolific first."""
    repo = Path(repo)
    out = _git(repo, "log", "--no-merges", "--format=%aE\x1f%aN")
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        email, _, name = line.partition("\x1f")
        email = email.strip().lower()
        if not email:
            continue
        counts[email] = counts.get(email, 0) + 1
        names.setdefault(email, name.strip() or email)
    return sorted(
        ((e, names[e], c) for e, c in counts.items()),
        key=lambda t: (-t[2], t[0]),
    )


# --------------------------------------------------------------------------
# author attribution for file content
# --------------------------------------------------------------------------


def _email_matches(candidate: str, target: str) -> bool:
    """Loose equality between two git author emails."""
    a, b = candidate.strip().lower(), target.strip().lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


class _Attribution:
    """Decides which lines of a tracked file a given author actually wrote.

    Two passes, cheapest first:

    1. ``git log --follow -- <path>`` gives the set of authors who ever touched
       a file. A file the target never touched is dropped outright, and this
       costs one cheap git call per candidate file.
    2. ``git blame --line-porcelain`` attributes individual lines, so a file
       with many contributors only yields the target's own runs. Blame is slow,
       so it is capped at :data:`BLAME_FILE_CAP` files and bounded by an overall
       wall-clock budget; once either is spent, or if blame fails on a file, we
       degrade to the pass-1 answer (keep the whole file) rather than raising.

    When ``author`` is ``None`` the whole thing is inert and every query says
    "yes", so the no-author code path costs nothing.
    """

    def __init__(
        self,
        repo: Path,
        author: str | None,
        *,
        file_cap: int | None = None,
        wall_seconds: float | None = None,
    ) -> None:
        self.repo = repo
        self.author = (author or "").strip().lower()
        self.enabled = bool(self.author)
        self.file_cap = BLAME_FILE_CAP if file_cap is None else file_cap
        self.wall_seconds = (
            BLAME_WALL_SECONDS if wall_seconds is None else wall_seconds
        )
        self._deadline: float | None = None
        self._blamed = 0
        self._touched: dict[str, bool] = {}
        self._lines: dict[str, list[str] | None] = {}
        self._local_email: str | None = None

    def _uncommitted_owner(self) -> str:
        """Who owns working-tree lines that are not committed yet.

        ``git blame`` labels uncommitted lines ``<not.committed.yet>``. Those
        lines belong to whoever is sitting at this checkout, so we resolve them
        to the local ``user.email`` rather than throwing the work away.
        """
        if self._local_email is None:
            self._local_email = _git(
                self.repo, "config", "--get", "user.email"
            ).strip().lower()
        return self._local_email

    # -- pass 1 ------------------------------------------------------------

    def touched(self, rel: str) -> bool:
        """True if the target author ever appears in ``rel``'s history."""
        if not self.enabled:
            return True
        if rel not in self._touched:
            out = _git(
                self.repo, "log", "--follow", "--max-count=300",
                "--format=%aE", "--", rel,
            )
            emails = {line.strip().lower() for line in out.splitlines() if line.strip()}
            hit = any(_email_matches(e, self.author) for e in emails)
            if not hit and _email_matches(self._uncommitted_owner(), self.author):
                # Uncommitted working-tree edits never show up in the log, but
                # they are the local user's writing all the same.
                hit = bool(_git(self.repo, "status", "--porcelain", "--", rel).strip())
            self._touched[rel] = hit
        return self._touched[rel]

    # -- pass 2 ------------------------------------------------------------

    def _budget_left(self) -> bool:
        """False once the file cap or the wall-clock budget has been spent."""
        if self._blamed >= self.file_cap:
            return False
        if self._deadline is None:
            self._deadline = time.monotonic() + self.wall_seconds
        return time.monotonic() < self._deadline

    def line_authors(self, rel: str) -> list[str] | None:
        """Per-line author emails for ``rel`` (index 0 == line 1).

        ``None`` means "blame unavailable" — no budget left, or git failed —
        and callers should fall back to whole-file attribution.
        """
        if not self.enabled:
            return None
        if rel in self._lines:
            return self._lines[rel]
        if not self._budget_left():
            self._lines[rel] = None
            return None
        self._blamed += 1
        out = _git(
            self.repo, "blame", "--line-porcelain", "-w", "--", rel,
            timeout=BLAME_TIMEOUT,
        )
        if not out:
            self._lines[rel] = None
            return None
        authors: list[str] = []
        current = ""
        for line in out.splitlines():
            if line.startswith("author-mail "):
                current = line[len("author-mail "):].strip().strip("<>").lower()
            elif line.startswith("\t"):
                if current in ("not.committed.yet", "external.file"):
                    authors.append(self._uncommitted_owner())
                else:
                    authors.append(current)
        self._lines[rel] = authors or None
        return self._lines[rel]

    # -- queries -----------------------------------------------------------

    def mask(self, rel: str, lines: list[str]) -> list[str]:
        """Blank every line of ``lines`` the target author did not write.

        Line count is preserved so downstream line-based cleaning still works.
        Falls back to returning ``lines`` unchanged when blame is unavailable.
        """
        if not self.enabled:
            return lines
        authors = self.line_authors(rel)
        if authors is None:
            return lines
        return [
            line
            if i < len(authors) and _email_matches(authors[i], self.author)
            else ""
            for i, line in enumerate(lines)
        ]

    def owns_range(self, rel: str, lo: int, hi: int, min_ratio: float) -> bool:
        """True if the target wrote at least ``min_ratio`` of lines ``lo``-``hi``.

        ``lo``/``hi`` are 1-based and inclusive. Returns ``True`` when blame is
        unavailable, so a degraded run keeps content rather than dropping it.
        """
        if not self.enabled:
            return True
        authors = self.line_authors(rel)
        if authors is None:
            return True
        span = [authors[i] for i in range(lo - 1, min(hi, len(authors)))]
        if not span:
            return False
        mine = sum(1 for e in span if _email_matches(e, self.author))
        return (mine / len(span)) >= min_ratio


# --------------------------------------------------------------------------
# commits
# --------------------------------------------------------------------------

# Trailer keys that are machine bookkeeping, never the human's voice.
_TRAILER_KEYS = (
    "co-authored-by",
    "signed-off-by",
    "claude-session",
    "acked-by",
    "reviewed-by",
    "tested-by",
    "reported-by",
    "suggested-by",
    "helped-by",
    "cc",
    "change-id",
    "pr-link",
    "differential revision",
    "reviewed-on",
    "git-svn-id",
    "bug",
)

_TRAILER_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(k) for k in _TRAILER_KEYS) + r")\s*:",
    re.IGNORECASE,
)
# Generic "<Something>-by:" trailer, e.g. "Co-Developed-by: ..."
_GENERIC_TRAILER_RE = re.compile(r"^\s*[A-Za-z][A-Za-z-]*-by\s*:", re.IGNORECASE)

_GENERATED_LINE_RE = re.compile(
    r"(?:"
    r"\U0001F916"                       # robot emoji
    r"|generated with \[?claude code"
    r"|generated with \[?cursor"
    r"|co-?authored-?by"
    r"|https?://claude\.ai/code"
    r"|claude-session"
    r"|noreply@anthropic\.com"
    r")",
    re.IGNORECASE,
)

_NOISE_SUBJECT_RES = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"^merge\b",
        r"^merge pull request\b",
        r"^revert\b",
        r"^bump\b",
        r"^\w+\(deps(?:-dev)?\)",              # chore(deps): / build(deps-dev):
        r"^(?:chore|ci|build|style)\b[^:]*:\s*(?:bump|update|upgrade|pin)\b",
        r"^(?:chore|ci|build)\b[^:]*:\s*(?:lint|format|prettier|reformat)\b",
        r"^update\s+(?:dependenc|changelog|lock|submodule|snapshot|package-lock)",
        r"^upgrade\s+dependenc",
        r"^(?:release|version|chore\(release\))\b",
        r"^v?\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?\s*$",   # bare version bump
        r"^\[?(?:automated|auto|bot|skip ci)\]?\b",
        r"^(?:apply|run)\s+(?:black|prettier|gofmt|rustfmt|isort|clang-format)",
        r"^regenerate\b",
        r"^(?:wip|tmp|temp|test|asdf|foo|stuff|misc|minor|cleanup|typo|fixes|fix)\s*[.!]?$",
        r"^(?:fix|fixed)\s+typos?\b",
        r"^initial commit\s*$",
        r"^(?:add|update)\s+\.?gitignore\s*$",
        r"^(?:merge branch|merge remote-tracking)\b",
    )
]

_BOT_AUTHOR_RE = re.compile(
    r"(?:dependabot|renovate|github-actions|greenkeeper|snyk-bot|imgbot|"
    r"pre-commit-ci|allcontributors|weblate|crowdin|"
    r"\[bot\]|(?:^|[^a-z])bot@)",
    re.IGNORECASE,
)


def _strip_trailers(body: str) -> str:
    """Remove machine trailers and tool-attribution lines from a commit body."""
    kept: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if _GENERATED_LINE_RE.search(stripped):
            continue
        if _TRAILER_RE.match(stripped) or _GENERIC_TRAILER_RE.match(stripped):
            continue
        kept.append(line.rstrip())
    # Collapse runs of blank lines and trim.
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_noise_commit(subject: str, author_email: str, author_name: str) -> bool:
    """True if a commit is machine-generated or too trivial to be voice."""
    if _BOT_AUTHOR_RE.search(author_email) or _BOT_AUTHOR_RE.search(author_name):
        return True
    subject = subject.strip()
    if not subject:
        return True
    return any(rx.search(subject) for rx in _NOISE_SUBJECT_RES)


def mine_commits(
    repo: Path,
    author: str | None = None,
    limit: int = 200,
    min_chars: int = 40,
) -> list[Sample]:
    """Mine commit messages (full bodies, ``--format=%B``) as writing samples.

    Skips merge commits, bot authors, dependency bumps, release/version noise
    and anything shorter than ``min_chars`` after cleaning. Trailers such as
    ``Co-Authored-By``, ``Signed-off-by``, ``Claude-Session`` and the
    "Generated with Claude Code" line are stripped, so the sample is the
    human's prose only.

    Args:
        repo: Path to a git working tree.
        author: Optional author email (or substring) to restrict the log to.
        limit: Maximum number of samples to return.
        min_chars: Minimum length of the cleaned message.

    Returns:
        Samples of kind ``"commit"``, newest first.
    """
    repo = Path(repo)
    if limit <= 0:
        return []
    argv = [
        "log",
        "--no-merges",
        "--no-notes",
        f"--max-count={max(limit * 5, limit)}",
        "--format=%x1e%H%x1f%aE%x1f%aN%x1f%B",
    ]
    if author:
        argv.insert(1, f"--author={author}")
    out = _git(repo, *argv)
    if not out:
        return []

    samples: list[Sample] = []
    seen: set[str] = set()
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        parts = record.split("\x1f", 3)
        if len(parts) != 4:
            continue
        sha, email, name, body = parts
        sha = sha.strip()
        email = email.strip()
        subject = body.strip().splitlines()[0] if body.strip() else ""
        if _is_noise_commit(subject, email, name):
            continue
        text = _strip_trailers(body)
        if len(text) < min_chars:
            continue
        key = re.sub(r"\s+", " ", text).lower()
        if key in seen:
            continue
        seen.add(key)
        samples.append(
            Sample(
                kind="commit",
                origin=f"git log {sha[:7]}",
                text=text,
                author=email or None,
            )
        )
        if len(samples) >= limit:
            break
    return samples


# --------------------------------------------------------------------------
# docs
# --------------------------------------------------------------------------

_DOC_SUFFIXES = {".md", ".markdown", ".mdx", ".rst", ".txt"}

_DOC_SKIP_NAME_RE = re.compile(
    r"^(?:changelog|change_log|changes|history|news|license|licence|copying|"
    r"notice|authors|contributors|codeowners|patents|third[-_]party[-_]notices|"
    r"requirements[\w.-]*|constraints)\b",
    re.IGNORECASE,
)

_VENDOR_DIR_RE = re.compile(
    r"(?:^|/)(?:node_modules|vendor|third_party|thirdparty|site-packages|"
    r"dist|build|\.venv|venv|target|\.tox|__pycache__|migrations|fixtures|"
    r"locales?|i18n|\.github/ISSUE_TEMPLATE|\.github/PULL_REQUEST_TEMPLATE)(?:/|$)",
    re.IGNORECASE,
)

_BADGE_RE = re.compile(
    r"^\s*(?:\[?!\[[^\]]*\]\((?:[^)]*)\)\]?(?:\([^)]*\)|\[[^\]]*\])?\s*"
    r"|\[?!\[[^\]]*\]\[[^\]]*\]\]?(?:\[[^\]]*\])?\s*)+$"
)
_LINKREF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*\S+")
_HTML_TAG_RE = re.compile(r"<[^>\n]{1,200}>")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_REFLINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\[[^\]]*\]")


def _blank(match: "re.Match[str]") -> str:
    """Replace a matched region with the same number of newlines it consumed.

    Keeping the line count intact is what lets ``git blame`` line numbers stay
    aligned with the text after block constructs have been removed.
    """
    return "\n" * match.group(0).count("\n")


def _blank_block_constructs(text: str) -> str:
    """Blank out fences, front matter and HTML blocks, preserving line numbers."""
    # YAML front matter
    text = re.sub(r"\A---\n.*?\n---\n", _blank, text, flags=re.DOTALL)
    # Fenced code blocks (``` and ~~~), including an unterminated trailing fence.
    text = re.sub(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", _blank, text,
                  flags=re.DOTALL | re.MULTILINE)
    text = re.sub(r"^[ \t]*(?:```|~~~).*\Z", _blank, text,
                  flags=re.DOTALL | re.MULTILINE)
    # reStructuredText directives and their indented bodies
    text = re.sub(r"^\.\. \w+::.*(?:\n(?:[ \t].*|\s*))*", _blank, text,
                  flags=re.MULTILINE)
    # HTML comments and script/style blocks
    text = re.sub(r"<!--.*?-->", _blank, text, flags=re.DOTALL)
    text = re.sub(r"<(script|style)\b.*?</\1>", _blank, text,
                  flags=re.DOTALL | re.IGNORECASE)
    return text


def _clean_doc_lines(lines: list[str]) -> str:
    """Strip badges, link refs, tables, indented code and inline markup."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
            continue
        if _BADGE_RE.match(stripped) or _LINKREF_RE.match(stripped):
            continue
        if stripped.startswith("|") or re.fullmatch(r"[-=~^_*+|: ]{3,}", stripped):
            continue  # table rows and rules / rst underlines
        if line.startswith(("    ", "\t")) and not stripped.startswith(("-", "*", ">", "#")):
            continue  # indented code block
        stripped = _IMAGE_RE.sub("", stripped)
        stripped = _IMAGE_REF_RE.sub("", stripped)
        stripped = _MD_LINK_RE.sub(r"\1", stripped)
        stripped = _MD_REFLINK_RE.sub(r"\1", stripped)
        stripped = _HTML_TAG_RE.sub("", stripped)
        stripped = re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", stripped)
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        stripped = stripped.strip()
        if not stripped:
            continue
        out.append(stripped)
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _clean_markdown(text: str) -> str:
    """Strip fences, badges, HTML, link refs and tables from doc-ish text."""
    return _clean_doc_lines(_blank_block_constructs(text).splitlines())


def _doc_priority(rel: str) -> int:
    """Lower sorts first: README, CONTRIBUTING, docs/**, then everything else."""
    name = Path(rel).name.lower()
    lower = rel.lower()
    if name.startswith("readme"):
        return 0
    if name.startswith(("contributing", "code_of_conduct", "architecture", "design")):
        return 1
    if lower.startswith("docs/") or "/docs/" in lower:
        return 2
    if name.startswith(("agents", "claude")):
        return 3
    return 4


def mine_docs(
    repo: Path, limit: int = 20, author: str | None = None
) -> list[Sample]:
    """Mine tracked ``*.md`` / ``*.rst`` / ``*.txt`` prose.

    READMEs, CONTRIBUTING and ``docs/**`` come first. Code fences, badge lines,
    link-reference blocks, tables and raw HTML are stripped. CHANGELOG, LICENSE
    and other boilerplate files are skipped because they are not voice.

    When ``author`` is given, files that author never touched are skipped and
    the remaining files are masked line-by-line with ``git blame`` so only the
    lines they wrote survive. A doc where the target contributed three lines
    therefore falls under :data:`DOC_MIN_CHARS` and drops out entirely instead
    of contributing a whole-file sample. Blame is capped and time-boxed; see
    :class:`_Attribution`.

    Args:
        repo: Path to a git working tree.
        limit: Maximum number of samples to return.
        author: Optional author email to attribute doc lines to.

    Returns:
        Samples of kind ``"doc"``.
    """
    repo = Path(repo)
    if limit <= 0:
        return []
    attribution = _Attribution(repo, author)
    candidates: list[str] = []
    for rel in _tracked_files(repo):
        if Path(rel).suffix.lower() not in _DOC_SUFFIXES:
            continue
        if _VENDOR_DIR_RE.search(rel) or _DOC_SKIP_NAME_RE.match(Path(rel).name):
            continue
        candidates.append(rel)
    candidates.sort(key=lambda r: (_doc_priority(r), r.count("/"), r.lower()))

    samples: list[Sample] = []
    for rel in candidates:
        path = _safe_path(repo, rel)
        if path is None:
            continue
        raw = _read_text(path)
        if not raw:
            continue
        low = raw[:2000].lower()
        if "do not edit" in low or "auto-generated" in low or "@generated" in low:
            continue
        if not attribution.touched(rel):
            continue
        # Blank block constructs FIRST so line numbers still line up with blame,
        # then drop the lines somebody else wrote, then do the per-line clean.
        lines = _blank_block_constructs(raw).splitlines()
        cleaned = _clean_doc_lines(attribution.mask(rel, lines))
        if len(cleaned) < DOC_MIN_CHARS:
            continue
        samples.append(
            Sample(kind="doc", origin=rel, text=cleaned, author=author or None)
        )
        if len(samples) >= limit:
            break
    return samples


# --------------------------------------------------------------------------
# comments
# --------------------------------------------------------------------------

_PY_SUFFIXES = {".py"}
_SLASH_SUFFIXES = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".swift", ".c", ".h", ".cc", ".cpp",
    ".hpp", ".cs", ".scala", ".php", ".dart",
}
_HASH_SUFFIXES = {".sh", ".bash", ".zsh", ".rb", ".pl", ".yaml", ".yml", ".toml"}

_GENERATED_FILE_RE = re.compile(
    r"(?:do not edit|@generated|code generated by|autogenerated|auto-generated|"
    r"generated by (?:protoc|swagger|openapi|thrift|sqlc|prisma|the protocol))",
    re.IGNORECASE,
)
_LICENSE_RE = re.compile(
    r"(?:copyright\s+(?:\(c\)|\d{4}|©)|spdx-license-identifier|licensed under|"
    r"permission is hereby granted|all rights reserved|apache license|"
    r"gnu general public|redistribution and use in source)",
    re.IGNORECASE,
)
_PRAGMA_RE = re.compile(
    r"^(?:noqa|type:|pylint:|pyright:|mypy:|flake8:|ruff:|pragma:|fmt:|"
    r"eslint|prettier|ts-ignore|@ts-|tslint|nolint|coding[:=]|!|-\*-|"
    r"@ts-expect-error|istanbul |c8 |codegen|region\b|endregion\b)",
    re.IGNORECASE,
)
_URL_ONLY_RE = re.compile(r"^\s*(?:see\s+)?https?://\S+\s*$", re.IGNORECASE)


def _looks_like_prose(text: str) -> bool:
    """Cheap prose test: enough words, enough letters, not a pragma or URL."""
    text = text.strip()
    if len(text) < COMMENT_MIN_CHARS:
        return False
    if _PRAGMA_RE.match(text) or _URL_ONLY_RE.match(text):
        return False
    if _LICENSE_RE.search(text):
        return False
    words = re.findall(r"[A-Za-z']{2,}", text)
    if len(words) < 8:
        return False
    letters = sum(c.isalpha() or c.isspace() for c in text)
    return letters / max(len(text), 1) > 0.6


_Block = tuple[str, int, int]
"""A comment block: ``(text, first_line, last_line)``, 1-based and inclusive.

The line span is what lets ``git blame`` decide whether the target author
actually wrote a given comment, so every extractor must report it honestly.
"""


def _python_comment_blocks(source: str) -> list[_Block]:
    """Docstrings (via ``ast``) plus ``#`` comment runs of two or more lines."""
    blocks: list[_Block] = []
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            doc = ast.get_docstring(node, clean=True)
            if not doc:
                continue
            body = getattr(node, "body", None)
            lo, hi = 1, 1
            if body:
                first = body[0]
                lo = getattr(first, "lineno", 1) or 1
                hi = getattr(first, "end_lineno", None) or lo
            blocks.append((doc.strip(), lo, hi))
    blocks.extend(_python_comment_runs(source))
    return blocks


def _python_comment_runs(source: str) -> list[_Block]:
    """``#`` comment runs of two or more lines, tokenized so strings are safe.

    Using :mod:`tokenize` rather than a line scan means a ``## Heading`` inside
    a triple-quoted prompt string is never mistaken for a comment. Falls back
    to the naive scan if the file does not tokenize.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return _hash_comment_runs(source)
    lines = source.splitlines()
    runs: list[_Block] = []
    current: list[str] = []
    first_row = 0
    last_row = -10
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if row - 1 >= len(lines) or lines[row - 1][:col].strip():
            continue  # trailing comment on a code line, not a prose run
        body = tok.string.lstrip("#").strip()
        if tok.string.startswith("#!") and row == 1:
            continue
        if re.fullmatch(r"[-=*#_~ ]*", body):
            continue
        if row != last_row + 1 and current:
            if len(current) >= 2:
                runs.append(("\n".join(current).strip(), first_row, last_row))
            current = []
        if not current:
            first_row = row
        current.append(body)
        last_row = row
    if len(current) >= 2:
        runs.append(("\n".join(current).strip(), first_row, last_row))
    return runs


def _hash_comment_runs(source: str) -> list[_Block]:
    """Runs of two or more consecutive whole-line ``#`` comments."""
    runs: list[_Block] = []
    current: list[str] = []
    first_row = 0
    last_row = 0
    for row, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            body = stripped.lstrip("#").strip()
            if re.fullmatch(r"[-=*#_~ ]*", body):  # divider bar
                continue
            if not current:
                first_row = row
            current.append(body)
            last_row = row
        else:
            if len(current) >= 2:
                runs.append(("\n".join(current).strip(), first_row, last_row))
            current = []
    if len(current) >= 2:
        runs.append(("\n".join(current).strip(), first_row, last_row))
    return runs


_BLOCK_COMMENT_RE = re.compile(r"/\*+(.*?)\*+/", re.DOTALL)


def _slash_comment_blocks(source: str) -> list[_Block]:
    """Regex fallback for C-family languages: ``//`` runs and ``/* */`` blocks."""
    blocks: list[_Block] = []
    for match in _BLOCK_COMMENT_RE.finditer(source):
        body = "\n".join(
            re.sub(r"^\s*\*+ ?", "", line).rstrip()
            for line in match.group(1).splitlines()
        ).strip()
        if not body:
            continue
        if body.count("\n") >= 1 or len(body) >= COMMENT_MIN_CHARS:
            lo = source.count("\n", 0, match.start()) + 1
            hi = lo + match.group(0).count("\n")
            blocks.append((body, lo, hi))
    current: list[str] = []
    first_row = 0
    last_row = 0
    for row, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("//"):
            body = stripped.lstrip("/").strip()
            if re.fullmatch(r"[-=*/_~ ]*", body):
                continue
            if not current:
                first_row = row
            current.append(body)
            last_row = row
        else:
            if len(current) >= 2:
                blocks.append(("\n".join(current).strip(), first_row, last_row))
            current = []
    if len(current) >= 2:
        blocks.append(("\n".join(current).strip(), first_row, last_row))
    return blocks


def mine_comments(
    repo: Path, limit: int = 150, author: str | None = None
) -> list[Sample]:
    """Mine docstrings and multi-line comment runs from tracked source files.

    Python files are parsed with :mod:`ast` so docstrings come out clean; other
    languages use a regex fallback. Licence headers, shebangs, linter pragmas,
    type stubs and generated files are skipped, and a comment must read as
    prose (two or more lines, enough words) to survive.

    When ``author`` is given, files that author never touched are skipped and
    each surviving comment block must be at least
    :data:`COMMENT_OWNERSHIP_MIN` owned by them according to ``git blame`` — so
    a file with many contributors only yields the comments they actually wrote.
    Blame is capped and time-boxed; see :class:`_Attribution`.

    Args:
        repo: Path to a git working tree.
        limit: Maximum number of samples to return.
        author: Optional author email to attribute comments to.

    Returns:
        Samples of kind ``"comment"``.
    """
    repo = Path(repo)
    if limit <= 0:
        return []
    attribution = _Attribution(repo, author)
    samples: list[Sample] = []
    seen: set[str] = set()
    for rel in _tracked_files(repo):
        if len(samples) >= limit:
            break
        suffix = Path(rel).suffix.lower()
        if rel.endswith((".pyi", ".d.ts", ".min.js", "_pb2.py", ".pb.go")):
            continue
        if _VENDOR_DIR_RE.search(rel):
            continue
        if suffix in _PY_SUFFIXES:
            extract = _python_comment_blocks
        elif suffix in _SLASH_SUFFIXES:
            extract = _slash_comment_blocks
        elif suffix in _HASH_SUFFIXES:
            extract = _hash_comment_runs
        else:
            continue
        path = _safe_path(repo, rel)
        if path is None:
            continue
        source = _read_text(path)
        if not source or _GENERATED_FILE_RE.search(source[:4000]):
            continue
        if not attribution.touched(rel):
            continue
        for block, lo, hi in extract(source):
            block = re.sub(r"\n{3,}", "\n\n", block).strip()
            if not _looks_like_prose(block):
                continue
            if not attribution.owns_range(rel, lo, hi, COMMENT_OWNERSHIP_MIN):
                continue
            key = re.sub(r"\s+", " ", block).lower()
            if key in seen:
                continue
            seen.add(key)
            samples.append(
                Sample(kind="comment", origin=rel, text=block, author=author or None)
            )
            if len(samples) >= limit:
                break
    return samples


# --------------------------------------------------------------------------
# pull requests (optional, via gh)
# --------------------------------------------------------------------------


def _norm(value: str) -> str:
    """Lowercase and strip every non-alphanumeric character."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _author_needles(repo: Path, author: str | None) -> set[str]:
    """Identity fragments for ``author``, for matching against GitHub logins.

    A git email rarely equals a GitHub login, so we also pull the author's git
    display name out of the log and normalise both. An empty set means "match
    everyone".
    """
    if not author:
        return set()
    author = author.strip().lower()
    needles = {_norm(author.split("@", 1)[0]), _norm(author)}
    for email, name, _count in list_authors(repo):
        if email == author or author in email:
            needles.add(_norm(name))
            needles.add(_norm(name.replace(" ", ".")))
    return {n for n in needles if len(n) >= 3}


def _author_matches(needles: set[str], login: str, name: str = "") -> bool:
    """True if a GitHub login/display name plausibly belongs to the author."""
    if not needles:
        return True
    haystack = _norm(login) + "|" + _norm(name)
    return any(n in haystack for n in needles)


def mine_prs(repo: Path, author: str | None = None, limit: int = 30) -> list[Sample]:
    """Mine pull-request bodies and comments via the ``gh`` CLI.

    This is the only function in the module that touches the network, and it is
    strictly best-effort: if ``gh`` is missing, unauthenticated, times out, or
    the repo has no GitHub remote, it returns ``[]`` silently. It never raises
    and never blocks longer than :data:`GH_TIMEOUT`.

    Args:
        repo: Path to a git working tree.
        author: Optional author email; matched loosely against GitHub logins.
        limit: Maximum number of PRs to consider.

    Returns:
        Samples of kind ``"pr"``, possibly empty.
    """
    repo = Path(repo)
    if limit <= 0 or not repo.is_dir():
        return []
    needles = _author_needles(repo, author)
    code, out = _gh(
        repo,
        "pr", "list",
        "--state", "all",
        "--limit", str(max(1, min(limit, 100))),
        "--json", "number,title,body,author,comments",
    )
    if code != 0 or not out.strip():
        return []
    try:
        payload = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []

    samples: list[Sample] = []
    for pr in payload:
        if not isinstance(pr, dict):
            continue
        number = pr.get("number")
        pr_author = pr.get("author") or {}
        login = str(pr_author.get("login") or "")
        name = str(pr_author.get("name") or "")
        body = (pr.get("body") or "").strip()
        if body and _author_matches(needles, login, name):
            cleaned = _clean_markdown(body)
            if len(cleaned) >= PR_MIN_CHARS:
                samples.append(
                    Sample(
                        kind="pr",
                        origin=f"PR #{number}",
                        text=cleaned,
                        author=author if author else None,
                    )
                )
        for comment in pr.get("comments") or []:
            if not isinstance(comment, dict):
                continue
            c_author = comment.get("author") or {}
            c_login = str(c_author.get("login") or "")
            if not _author_matches(needles, c_login):
                continue
            c_body = _clean_markdown((comment.get("body") or "").strip())
            if len(c_body) < PR_MIN_CHARS:
                continue
            samples.append(
                Sample(
                    kind="pr",
                    origin=f"PR #{number} comment",
                    text=c_body,
                    author=author if author else None,
                )
            )
        if len(samples) >= limit:
            break
    return samples[:limit]


# --------------------------------------------------------------------------
# mine_all + budget balancing
# --------------------------------------------------------------------------


def _quotas(totals: dict[str, int], budget: int) -> dict[str, int]:
    """Water-fill ``budget`` across kinds using :data:`KIND_SHARE`.

    A kind that needs less than its share donates the remainder to the kinds
    that are still over quota, so an absent source never wastes budget.
    """
    quotas = {k: int(budget * share) for k, share in KIND_SHARE.items()}
    for _ in range(len(KIND_SHARE)):
        spare = sum(
            quotas[k] - totals.get(k, 0)
            for k in KIND_SHARE
            if totals.get(k, 0) < quotas[k]
        )
        hungry = [k for k in KIND_SHARE if totals.get(k, 0) > quotas[k]]
        if spare <= 0 or not hungry:
            break
        for k in KIND_SHARE:
            if totals.get(k, 0) < quotas[k]:
                quotas[k] = totals.get(k, 0)
        share_sum = sum(KIND_SHARE[k] for k in hungry)
        for k in hungry:
            quotas[k] += int(spare * (KIND_SHARE[k] / share_sum))
    return quotas


def _trim_to_quota(samples: list[Sample], quota: int) -> list[Sample]:
    """Drop the longest samples first until the kind fits ``quota`` chars."""
    if quota <= 0:
        return []
    order = sorted(range(len(samples)), key=lambda i: len(samples[i].text), reverse=True)
    dropped: set[int] = set()
    total = sum(len(s.text) for s in samples)
    for idx in order:
        if total <= quota:
            break
        dropped.add(idx)
        total -= len(samples[idx].text)
    return [s for i, s in enumerate(samples) if i not in dropped]


def mine_all(
    repo: Path,
    author: str | None = None,
    *,
    budget_chars: int = 180_000,
    prs: bool = True,
) -> list[Sample]:
    """Run every miner and balance the results across kinds.

    Aims for roughly 40% commits / 25% docs / 20% comments / 15% PRs of
    ``budget_chars``; unused share is redistributed to the kinds that have more
    material than they can fit, and each kind is trimmed longest-first until it
    fits. ``author`` is threaded through to every miner, so docs and comments
    are attributed with ``git blame`` rather than being taken wholesale.

    Args:
        repo: Path to a git working tree.
        author: Optional author email to restrict every source to.
        budget_chars: Total character budget across all returned samples.
        prs: Mine pull requests via ``gh``. Set False (the ``--no-pr`` flag) to
            skip the only subprocess that touches the network; the PR share of
            the budget is then water-filled across the other kinds.

    Returns:
        Samples ordered commits, docs, comments, PRs.
    """
    repo = Path(repo)
    if not is_git_repo(repo):
        return []
    by_kind: dict[str, list[Sample]] = {
        "commit": mine_commits(repo, author=author),
        "doc": mine_docs(repo, author=author),
        "comment": mine_comments(repo, author=author),
        "pr": mine_prs(repo, author=author) if prs else [],
    }
    totals = {k: sum(len(s.text) for s in v) for k, v in by_kind.items()}
    if sum(totals.values()) <= budget_chars:
        return [s for k in KIND_SHARE for s in by_kind[k]]

    quotas = _quotas(totals, budget_chars)
    result: list[Sample] = []
    for kind in KIND_SHARE:
        result.extend(_trim_to_quota(by_kind[kind], quotas[kind]))
    return result
