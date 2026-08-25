"""Outbound-data guardrails for the PixieDuster CLI.

This module is the last thing standing between a user's private repository and
a third-party LLM API. Everything here is offline: **no network calls, ever.**

Responsibilities:

* :data:`SECRET_RULES` -- regex rules for credential material.
* :func:`scan`        -- find secrets in outbound :class:`~pixieduster.types.Sample`
                         text and return already-redacted :class:`Finding` objects.
* :func:`redact`      -- scrub every match out of a block of text.
* :func:`estimate_tokens` / :func:`estimate_cost` -- rough budgeting helpers.
* :func:`dry_run_report` -- plain-text description of exactly what would be sent.

Design notes
------------
The detector is deliberately biased toward *recall*: a missed secret is a
credential leak, a false positive is an annoying extra confirmation prompt.
The generic rules (``password = ...``, ``KEY=<long value>``) are the noisy
ones, so they are paired with structural filters and a Shannon-entropy floor
(see ``_VALIDATORS``) to keep the tool usable on real codebases.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from pixieduster.types import Finding, Sample

__all__ = [
    "SECRET_RULES",
    "MODEL_PRICING",
    "scan",
    "redact",
    "estimate_tokens",
    "estimate_cost",
    "dry_run_report",
    "shannon_entropy",
]


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
#
# USD per 1,000,000 tokens, Gemini API *paid tier*, standard (non-batch,
# non-cached) pricing.
#
# last verified: 2026-08-24
# source: https://ai.google.dev/gemini-api/docs/pricing
#
# HONESTY NOTE: only models whose price was read off the page above on that
# date appear here. Anything not in this table returns None from
# estimate_cost() -- we would rather say "cost unknown" than invent a number.
#
# Entries may carry a long-context tier: when the *input* size crosses
# ``threshold`` tokens, Google bills the whole request at the higher rates.
#
# CAVEAT (gemini-3.6-flash / gemini-3.7-flash): the listed $0.75 / $3.75 is a
# promotional rate documented as running "through Dec 31, 2026", doubling
# afterwards. ``estimate_cost`` does NOT model that cliff -- it always returns
# the promotional rate -- so treat post-2026 estimates for these two ids as a
# floor, not a forecast.
MODEL_PRICING: dict[str, dict[str, float]] = {
    # --- Gemini 3.x -------------------------------------------------------
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.6-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-3.1-pro-preview": {
        "input": 2.00,
        "output": 12.00,
        "threshold": 200_000,
        "input_over": 4.00,
        "output_over": 18.00,
    },
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    # --- Gemini 2.5 -------------------------------------------------------
    "gemini-2.5-pro": {
        "input": 1.25,
        "output": 10.00,
        "threshold": 200_000,
        "input_over": 2.50,
        "output_over": 15.00,
    },
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

# Model families whose billing is not a flat text in/out rate (per-image tiers,
# per-second audio, embeddings). We know these exist but refuse to guess a
# single number for them, so estimate_cost() returns None.
_UNPRICEABLE_MARKERS: tuple[str, ...] = (
    "-image",
    "-live",
    "-tts",
    "-audio",
    "-embedding",
    "embedding-",
    "-veo",
    "imagen",
)


# ---------------------------------------------------------------------------
# Secret rules
# ---------------------------------------------------------------------------
#
# Each entry is (rule_name, regex, severity).
#
# Convention: if a pattern contains a named group ``secret``, only that group
# is redacted / leak-checked; otherwise the whole match is. This lets the
# generic rules keep the human-readable key name visible
# (``password = <REDACTED:generic-secret-assignment>``) while still scrubbing
# the value.
#
# Order matters: rules are tried in sequence and the first rule to claim a
# span wins, so vendor-specific (high-confidence) rules are listed before the
# generic catch-alls.

SECRET_RULES: list[tuple[str, str, str]] = [
    # --- PEM private keys -------------------------------------------------
    # Whole block first so the key body is scrubbed, not just the header.
    (
        "private-key-pem-block",
        r"-----BEGIN (?:[A-Z0-9 ]{0,24})?PRIVATE KEY(?: BLOCK)?-----"
        r"[\s\S]{0,20000}?"
        r"-----END (?:[A-Z0-9 ]{0,24})?PRIVATE KEY(?: BLOCK)?-----",
        "high",
    ),
    # Truncated / header-only paste (no matching END marker).
    (
        "private-key-pem-header",
        r"-----BEGIN (?:[A-Z0-9 ]{0,24})?PRIVATE KEY(?: BLOCK)?-----",
        "high",
    ),
    # --- AWS --------------------------------------------------------------
    # Access key IDs have a fixed set of 4-char type prefixes + 16 base32 chars.
    (
        "aws-access-key-id",
        r"\b(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA|A3T[A-Z0-9])"
        r"[A-Z0-9]{16}\b",
        "high",
    ),
    # Secret access keys are 40 chars of base64 with no distinguishing prefix,
    # so they are only matched next to an AWS-ish key name. Matching bare
    # 40-char base64 anywhere would flag every git hash and base64 blob.
    (
        "aws-secret-access-key",
        r"(?i)\baws[_\-. ]?(?:secret|sec)[_\-. ]?(?:access[_\-. ]?)?key(?:[_\-. ]?id)?\b"
        r"\s*[:=]\s*[\"'`]?(?P<secret>[A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])",
        "high",
    ),
    # --- Google -----------------------------------------------------------
    # AIza + 35 chars. This is the key the CLI itself uses, so it must never
    # travel back out inside a sample.
    ("google-api-key", r"\bAIza[0-9A-Za-z_\-]{35}\b", "high"),
    # Google OAuth 2.0 client secret.
    ("google-oauth-client-secret", r"\bGOCSPX-[0-9A-Za-z_\-]{20,}\b", "high"),
    # --- Anthropic (before OpenAI: both start "sk-") ----------------------
    ("anthropic-api-key", r"\bsk-ant-[0-9A-Za-z_\-]{24,}", "high"),
    # --- OpenAI -----------------------------------------------------------
    # Classic sk-<48>, plus the project/service/admin variants. The negative
    # lookahead keeps Anthropic keys out of this rule.
    (
        "openai-api-key",
        r"\bsk-(?!ant-)(?:proj-|svcacct-|admin-)?[0-9A-Za-z_\-]{20,}",
        "high",
    ),
    # --- GitHub -----------------------------------------------------------
    # ghp_ personal, gho_ oauth, ghu_ user-to-server, ghs_ server-to-server,
    # ghr_ refresh. Fine-grained PATs use the github_pat_ prefix.
    ("github-token", r"\bgh[pousr]_[0-9A-Za-z]{36,255}\b", "high"),
    ("github-fine-grained-pat", r"\bgithub_pat_[0-9A-Za-z_]{22,255}\b", "high"),
    # --- Slack ------------------------------------------------------------
    ("slack-token", r"\bxox[baprse]-[0-9A-Za-z\-]{10,}", "high"),
    (
        "slack-webhook-url",
        r"https://hooks\.slack\.com/services/T[0-9A-Za-z_\-]+/B[0-9A-Za-z_\-]+/[0-9A-Za-z_\-]+",
        "high",
    ),
    # --- Stripe -----------------------------------------------------------
    # Live secret + restricted keys only. sk_test_ is not worth alarming over.
    ("stripe-secret-key", r"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}\b", "high"),
    # --- Other common vendor tokens (cheap, high-signal prefixes) ---------
    ("npm-token", r"\bnpm_[0-9A-Za-z]{36}\b", "high"),
    ("pypi-token", r"\bpypi-AgEIcHlwaS5vcmc[0-9A-Za-z_\-]{16,}", "high"),
    ("sendgrid-api-key", r"\bSG\.[0-9A-Za-z_\-]{22}\.[0-9A-Za-z_\-]{43}\b", "high"),
    ("huggingface-token", r"\bhf_[0-9A-Za-z]{34,}\b", "high"),
    # --- JWT --------------------------------------------------------------
    # Two base64url segments that both begin "eyJ" ('{"'), plus a signature
    # segment (which may be empty for alg=none).
    (
        "jwt",
        r"\beyJ[0-9A-Za-z_\-]{8,}\.eyJ[0-9A-Za-z_\-]{8,}\.[0-9A-Za-z_\-]*",
        "high",
    ),
    # --- Authorization headers -------------------------------------------
    (
        "authorization-header",
        r"(?i)\bauthorization\b\s*[:=]\s*[\"'`]?(?:bearer|basic|token)\s+"
        r"(?P<secret>[0-9A-Za-z._\-+/=]{16,})",
        "high",
    ),
    # --- Connection strings with inline credentials -----------------------
    # postgres://user:pass@host, mongodb+srv://..., amqp://..., https://u:p@h
    (
        "connection-string-credentials",
        r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis[s]?|amqps?"
        r"|mssql|sqlserver|ftps?|sftp|ssh|https?|jdbc:[a-z0-9]+)://"
        r"(?P<secret>[^\s:/@\"'`<>]{1,128}:[^\s@/\"'`<>]{1,256})@[^\s/\"'`<>]+",
        "high",
    ),
    # --- Generic assignments ---------------------------------------------
    # The workhorse for hand-rolled secrets. Heavily post-filtered by
    # _valid_generic_assignment(): placeholders, code identifiers, function
    # calls and low-entropy values are all dropped.
    (
        "generic-secret-assignment",
        r"(?i)\b(?:password|passwd|pwd|secret|secret[_\-]?key|token|auth[_\-]?token"
        r"|access[_\-]?token|refresh[_\-]?token|api[_\-]?key|apikey|client[_\-]?secret"
        r"|private[_\-]?key|encryption[_\-]?key|credential[s]?)\b"
        r"\s*(?:=>|:=|[:=])\s*"
        r"[\"'`]?(?P<secret>[^\s\"'`,;)\]}(\[<>]{8,})(?=[\"'`,;)\]}\s]|$)",
        "medium",
    ),
    # --- .env style high-entropy values ----------------------------------
    # SCREAMING_SNAKE=<32+ chars of key-ish material> on a line of its own.
    (
        "dotenv-high-entropy-value",
        r"(?m)^[ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]{2,}[ \t]*=[ \t]*"
        r"[\"']?(?P<secret>[0-9A-Za-z+/=_\-.]{32,})[\"']?[ \t]*$",
        "medium",
    ),
]


# ---------------------------------------------------------------------------
# Entropy + validators
# ---------------------------------------------------------------------------


def shannon_entropy(value: str) -> float:
    """Return the Shannon entropy of ``value`` in bits per character.

    Random-looking credential material typically scores above ~3.5 bits/char;
    English words and snake_case identifiers usually score below ~3.2.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


# Values that are obviously not real credentials.
_PLACEHOLDER_WORDS: tuple[str, ...] = (
    "your",
    "yours",
    "example",
    "changeme",
    "change_me",
    "placeholder",
    "redacted",
    "dummy",
    "fake",
    "sample",
    "insert",
    "replace",
    "todo",
    "fixme",
    "notreal",
    "goes_here",
    "goeshere",
    "here",
    "xxxx",
)

#: Matches a placeholder word only when it stands as its own token inside the
#: value ("your-api-key-here", "changeme"), never as an accidental substring
#: of real key material ("...fakeK7..." is not treated as a placeholder).
_PLACEHOLDER_TOKEN_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:" + "|".join(_PLACEHOLDER_WORDS) + r")(?:[^A-Za-z0-9]|$)",
    re.IGNORECASE,
)


def _looks_like_placeholder(value: str) -> bool:
    """True when the value is obviously filler rather than a real credential."""
    lowered = value.lower()
    if lowered in _PLACEHOLDER_EXACT:
        return True
    return bool(_PLACEHOLDER_TOKEN_RE.search(value))


_PLACEHOLDER_EXACT: frozenset[str] = frozenset(
    {
        "none",
        "null",
        "nil",
        "true",
        "false",
        "undefined",
        "empty",
        "optional",
        "required",
        "string",
        "str",
        "int",
        "integer",
        "boolean",
        "unset",
        "disabled",
        "enabled",
        "default",
        "password",
        "secret",
        "token",
        "apikey",
        "api_key",
        "hunter2",
        "abcdefgh",
        "12345678",
        "xxxxxxxx",
        "********",
        "........",
    }
)

# Code identifiers: snake_case, camelCase, PascalCase, CONSTANT_CASE, dotted
# attribute access. A real credential essentially never has this shape.
_IDENTIFIER_RE = re.compile(
    r"""^(?:
          [A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+          # os.environ, settings.SECRET_KEY
        | [a-z]+(?:_[a-z0-9]+)+                     # access_token
        | [A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+             # MY_SECRET_KEY
        | [a-z]+(?:[A-Z][a-z0-9]*)+                 # apiKeyValue
        | [A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+         # ApiKeyValue
    )$""",
    re.VERBOSE,
)

# Values that are template/interpolation syntax rather than a literal.
_TEMPLATE_PREFIXES: tuple[str, ...] = ("<", "{", "$", "%", "&", "!", "@", "?")


def _valid_generic_assignment(match: re.Match[str]) -> bool:
    """Post-filter for the ``generic-secret-assignment`` rule.

    Drops placeholders, code identifiers, function calls, template
    interpolation and low-entropy values. Everything else is treated as a
    possible credential.
    """
    value = match.group("secret")
    if len(value) < 8:
        return False
    lowered = value.lower()

    if _looks_like_placeholder(value):
        return False
    if value.startswith(_TEMPLATE_PREFIXES):
        return False
    if "${" in value or "{{" in value:
        return False
    # Function calls / subscripts / annotations got excluded by the regex's
    # character class, but be defensive in case the pattern is edited later.
    if any(ch in value for ch in "()[]{}<>"):
        return False
    if _IDENTIFIER_RE.match(value):
        return False
    # A path or URL is not a credential.
    if value.startswith(("/", "./", "../", "~/", "http://", "https://")):
        return False
    if shannon_entropy(value) < 3.0:
        return False
    return True


def _valid_dotenv_value(match: re.Match[str]) -> bool:
    """Post-filter for ``dotenv-high-entropy-value``.

    Requires genuinely key-shaped material: mixed character classes plus a
    high entropy score. Long prose, semver strings and paths are dropped.
    """
    value = match.group("secret")
    if _looks_like_placeholder(value):
        return False
    if _IDENTIFIER_RE.match(value):
        return False
    has_digit = any(ch.isdigit() for ch in value)
    has_alpha = any(ch.isalpha() for ch in value)
    has_upper = any(ch.isupper() for ch in value)
    has_symbol = any(ch in "+/=_-." for ch in value)
    if not (has_digit and has_alpha and (has_upper or has_symbol)):
        return False
    # Dotted-decimal / semver / date-ish values.
    if re.fullmatch(r"[0-9.\-_]+", value):
        return False
    if shannon_entropy(value) < 3.5:
        return False
    return True


def _valid_aws_secret(match: re.Match[str]) -> bool:
    """AWS secret keys are 40 base64 chars; reject obvious filler."""
    value = match.group("secret")
    if len(set(value)) <= 4:  # AAAA..., XXXX...
        return False
    return shannon_entropy(value) >= 3.0


def _valid_authorization_header(match: re.Match[str]) -> bool:
    return not _looks_like_placeholder(match.group("secret"))


# rule_name -> extra predicate applied after the regex matches.
_VALIDATORS: dict[str, Callable[[re.Match[str]], bool]] = {
    "generic-secret-assignment": _valid_generic_assignment,
    "dotenv-high-entropy-value": _valid_dotenv_value,
    "aws-secret-access-key": _valid_aws_secret,
    "authorization-header": _valid_authorization_header,
}


# Compiled once at import. (Compilation only -- no I/O, no network.)
_COMPILED: list[tuple[int, str, re.Pattern[str], str]] = [
    (index, name, re.compile(pattern), severity)
    for index, (name, pattern, severity) in enumerate(SECRET_RULES)
]


# ---------------------------------------------------------------------------
# Match collection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Hit:
    """One accepted rule match inside a block of text."""

    rule: str
    severity: str
    #: span of the material that must be scrubbed
    start: int
    end: int
    #: the raw secret material (never leaves this module un-redacted)
    value: str


def _collect(text: str) -> list[_Hit]:
    """Return every accepted, non-overlapping rule hit in ``text``.

    Rules earlier in :data:`SECRET_RULES` win overlapping spans, so a Google
    API key inside ``GOOGLE_KEY=AIza...`` is reported as ``google-api-key``
    rather than as a generic .env value.
    """
    if not text:
        return []

    candidates: list[tuple[int, _Hit]] = []
    for index, name, pattern, severity in _COMPILED:
        validator = _VALIDATORS.get(name)
        for match in pattern.finditer(text):
            if validator is not None and not validator(match):
                continue
            if "secret" in (match.groupdict() or {}) and match.group("secret") is not None:
                start, end = match.span("secret")
            else:
                start, end = match.span()
            if end <= start:
                continue
            candidates.append(
                (index, _Hit(name, severity, start, end, text[start:end]))
            )

    # Priority = rule order, then earliest position.
    candidates.sort(key=lambda item: (item[0], item[1].start))

    accepted: list[_Hit] = []
    for _, hit in candidates:
        if any(hit.start < other.end and other.start < hit.end for other in accepted):
            continue
        accepted.append(hit)

    accepted.sort(key=lambda hit: hit.start)
    return accepted


def _apply_redactions(
    text: str, hits: list[_Hit], *, offset: int = 0, limit: int | None = None
) -> str:
    """Replace each hit span in ``text`` with ``<REDACTED:rule>``.

    ``offset`` is the absolute position of ``text[0]`` in the document the
    hits were collected from; spans are clipped to the slice so a multi-line
    hit (a PEM block) can be redacted one line at a time.
    """
    end_limit = offset + (len(text) if limit is None else limit)
    out = text
    for hit in sorted(hits, key=lambda h: h.start, reverse=True):
        start = max(hit.start, offset)
        end = min(hit.end, end_limit)
        if end <= start:
            continue
        out = out[: start - offset] + f"<REDACTED:{hit.rule}>" + out[end - offset :]
    return out


def redact(text: str) -> str:
    """Return ``text`` with every :data:`SECRET_RULES` match replaced.

    Each match becomes ``<REDACTED:<rule_name>>``. Used both for ``--dry-run``
    display and as the last-resort scrub immediately before an API call.
    """
    if not text:
        return text
    return _apply_redactions(text, _collect(text))


# ---------------------------------------------------------------------------
# Leak guard
# ---------------------------------------------------------------------------

_LEAK_WINDOW = 8

_PLACEHOLDER_MARKER_RE = re.compile(r"<REDACTED:[^>]*>")


def _is_distinctive(window: str) -> bool:
    """True when a window is specific enough to be evidence of a leak.

    Runs like ``"-----\n"`` or ``"aaaaaaaa"`` occur naturally in report
    separators and padding, so they are not treated as surviving secret
    material.
    """
    return len({c for c in window if c.isalnum()}) >= 5


def _leaks(excerpt: str, secret: str) -> bool:
    """True if any distinctive run of >= 8 chars of ``secret`` survives in ``excerpt``.

    Belt-and-braces: even if a rule or the excerpt builder is buggy, a Finding
    that would leak credential material is caught here and blanked.
    """
    # Our own "<REDACTED:github-token>" markers embed rule names that can
    # coincidentally share a run of characters with the secret; strip them
    # before looking for survivors.
    excerpt = _PLACEHOLDER_MARKER_RE.sub(" ", excerpt)
    secret = secret.strip()
    if len(secret) < _LEAK_WINDOW:
        return secret in excerpt if secret else False
    return any(
        _is_distinctive(window) and window in excerpt
        for window in (
            secret[i : i + _LEAK_WINDOW]
            for i in range(len(secret) - _LEAK_WINDOW + 1)
        )
    )


_MAX_EXCERPT = 200


def _build_excerpt(text: str, hits: list[_Hit], hit: _Hit) -> str:
    """Build a redacted, single-line, length-capped excerpt around ``hit``."""
    line_start = text.rfind("\n", 0, hit.start) + 1
    line_end = text.find("\n", hit.start)
    if line_end == -1:
        line_end = len(text)

    line = text[line_start:line_end]
    excerpt = _apply_redactions(
        line, hits, offset=line_start, limit=line_end - line_start
    ).strip()

    if len(excerpt) > _MAX_EXCERPT:
        marker = excerpt.find(f"<REDACTED:{hit.rule}>")
        if marker == -1:
            excerpt = excerpt[:_MAX_EXCERPT] + " ..."
        else:
            lo = max(0, marker - 60)
            hi = min(len(excerpt), marker + len(hit.rule) + 130)
            excerpt = ("... " if lo else "") + excerpt[lo:hi] + (" ..." if hi < len(excerpt) else "")

    # Final guard. If anything of the secret survived, throw the excerpt away.
    if _leaks(excerpt, hit.value):
        return f"<REDACTED:{hit.rule}> (excerpt suppressed)"
    return excerpt


# ---------------------------------------------------------------------------
# Public scanning API
# ---------------------------------------------------------------------------


def scan(samples: list[Sample]) -> list[Finding]:
    """Scan outbound samples for credential material.

    Args:
        samples: The samples that would be sent to the model.

    Returns:
        A list of :class:`~pixieduster.types.Finding`. ``line`` is 1-based and
        relative to that sample's own ``text``. ``excerpt`` is **already
        redacted** and is safe to print, log, or paste into a bug report.
    """
    findings: list[Finding] = []
    for sample in samples or []:
        text = sample.text or ""
        hits = _collect(text)
        for hit in hits:
            findings.append(
                Finding(
                    rule=hit.rule,
                    origin=sample.origin,
                    line=text.count("\n", 0, hit.start) + 1,
                    excerpt=_build_excerpt(text, hits, hit),
                    severity=hit.severity,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Budgeting
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Roughly estimate the token count of ``text``.

    **This is an approximation, not a tokenizer.** It assumes ~4 characters
    per token, which is a reasonable average for English prose and code but
    can be off by a wide margin for CJK text, base64 blobs or dense symbols.
    Use it for budgeting and display only -- never for billing or for hard
    context-window limits.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _normalize_model(model: str) -> str:
    name = (model or "").strip().lower()
    if name.startswith("models/"):
        name = name[len("models/") :]
    for suffix in ("-latest", "-001", "-002", "-exp"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def _lookup_pricing(model: str) -> dict[str, float] | None:
    """Exact match, then longest known prefix. None when we do not know."""
    name = _normalize_model(model)
    if not name:
        return None
    if any(marker in name for marker in _UNPRICEABLE_MARKERS):
        return None
    if name in MODEL_PRICING:
        return MODEL_PRICING[name]
    for key in sorted(MODEL_PRICING, key=len, reverse=True):
        if name.startswith(key):
            return MODEL_PRICING[key]
    return None


def estimate_cost(tokens_in: int, tokens_out: int, model: str) -> float | None:
    """Estimate the USD cost of one request, or ``None`` if pricing is unknown.

    Returning ``None`` is a first-class result: callers must render it as
    "cost unknown" rather than as ``$0.00``. See :data:`MODEL_PRICING` for the
    verification date, source URL and caveats.

    Args:
        tokens_in: Estimated input tokens (see :func:`estimate_tokens`).
        tokens_out: Estimated output tokens.
        model: A Gemini model id, with or without a ``models/`` prefix.

    Returns:
        Estimated USD cost, or ``None`` when the model is not in the table.
    """
    pricing = _lookup_pricing(model)
    if pricing is None:
        return None

    tokens_in = max(0, int(tokens_in))
    tokens_out = max(0, int(tokens_out))

    threshold = pricing.get("threshold")
    if threshold is not None and tokens_in > threshold:
        in_rate = pricing.get("input_over", pricing["input"])
        out_rate = pricing.get("output_over", pricing["output"])
    else:
        in_rate = pricing["input"]
        out_rate = pricing["output"]

    return (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate


# ---------------------------------------------------------------------------
# Dry-run report
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def dry_run_report(
    samples: list[Sample],
    findings: list[Finding],
    model: str | None = None,
) -> str:
    """Render a plain-text description of exactly what would be sent.

    No rich markup, no ANSI: this is piped to stdout by ``--dry-run``.

    Args:
        samples: Samples that would be uploaded.
        findings: Result of :func:`scan` (excerpts are already redacted).
        model: Optional model id; when given, a cost estimate line is added
            (or "cost unknown" when the model is not in the price table).
    """
    samples = list(samples or [])
    findings = list(findings or [])

    lines: list[str] = []
    lines.append("PIXIEDUSTER DRY RUN")
    lines.append("=" * 60)
    lines.append("Nothing below has been sent anywhere. This is what *would* be sent.")
    lines.append("")

    lines.append(f"SAMPLES ({len(samples)})")
    lines.append("-" * 60)
    if not samples:
        lines.append("  (none)")
    total_tokens = 0
    for number, sample in enumerate(samples, start=1):
        tokens = sample.tokens or estimate_tokens(sample.text or "")
        total_tokens += tokens
        author = f"  author={sample.author}" if sample.author else ""
        lines.append(
            f"  {number:>3}. [{sample.kind}] {sample.origin}"
            f"  ({tokens} tokens){author}"
        )
    lines.append("")

    lines.append("TOTALS")
    lines.append("-" * 60)
    lines.append(f"  samples:                 {len(samples)}")
    lines.append(f"  characters:              {sum(len(s.text or '') for s in samples)}")
    lines.append(f"  estimated input tokens:  {total_tokens}")
    lines.append("  (token counts are a rough len/4 estimate, not a real tokenizer)")
    if model:
        cost = estimate_cost(total_tokens, 0, model)
        if cost is None:
            lines.append(f"  estimated cost ({model}): cost unknown (no verified price)")
        else:
            lines.append(f"  estimated cost ({model}): ${cost:.4f} (input only, estimate)")
    lines.append("")

    lines.append(f"SECRET SCAN ({len(findings)} finding(s))")
    lines.append("-" * 60)
    if not findings:
        lines.append("  No potential secrets detected.")
        lines.append("  NOTE: detection is best-effort. Review the sample list above.")
    else:
        lines.append("  Excerpts below are already redacted and safe to share.")
        lines.append("")
        ordered = sorted(
            findings,
            key=lambda f: (
                _SEVERITY_ORDER.get(f.severity, 3),
                f.origin,
                f.line,
            ),
        )
        for finding in ordered:
            lines.append(f"  [{finding.severity.upper()}] {finding.rule}")
            lines.append(f"      origin : {finding.origin}")
            lines.append(f"      line   : {finding.line}")
            lines.append(f"      excerpt: {finding.excerpt}")
            lines.append("")
        high = sum(1 for f in findings if f.severity == "high")
        if high:
            lines.append(
                f"  {high} high-severity finding(s). Do not send without redacting."
            )
    lines.append("")
    lines.append("END OF DRY RUN. No network request was made.")
    return "\n".join(lines)
