"""Decide which files in a folder actually look like the person's own writing.

``sources.load()`` will happily read every supported file in a folder. Point it
at ``~/Documents`` and it sends a tax return, a rental agreement and a bank
statement to Google as "writing samples". That wastes the user's daily quota,
dilutes the persona with prose the person never wrote, and ships private
documents off the machine.

This module scores each candidate 0.0 to 1.0 on how much it reads like one
person's own voice, and sorts them into ``keep`` / ``unsure`` / ``drop``.

Everything here is offline and pure: no network, no API key, no file system
access. It is given text that has already been read and returns judgments.

Design notes
------------
* **Nothing is deleted and nothing is silently discarded.** :func:`triage`
  returns both lists so the caller can show the user what was set aside and let
  them put it back.
* **Bias toward "unsure".** A false drop loses a piece of the user's real
  writing, which is worse than one wasted sample. Anything that reads like
  sustained first-person prose can never be dropped, however much invoice
  vocabulary it happens to contain (see :func:`_protected`).
* **Quoted text is trimmed, not fatal.** An email that is 80% somebody else's
  reply still has the user's own paragraph at the top, so the quoted chain is
  stripped and the remainder is scored on its own.
* **Binary files cannot be read offline**, so they are scored on file name and
  type alone. That signal is weak. See :func:`score_binary`.
* **Near duplicates** are found with 5-word shingles and a Jaccard overlap of
  0.8, compared only against better-scoring candidates already accepted.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass

from .types import Sample

__all__ = [
    "Scored",
    "DEFAULT_BUDGET_CHARS",
    "KEEP_THRESHOLD",
    "DROP_THRESHOLD",
    "strip_quoted",
    "score_text",
    "score_binary",
    "triage",
]

#: Total characters of text one run will send. Matches the CLI's default.
DEFAULT_BUDGET_CHARS = 180_000

#: At or above this score a candidate is a confident "keep".
KEEP_THRESHOLD = 0.55

#: Below this score a candidate is dropped, unless it is protected prose.
DROP_THRESHOLD = 0.32

#: Shorter than this (after quote stripping) and there is no voice to read.
MIN_VOICE_CHARS = 160

#: Longer than this and it is more likely a book or a scrape than a note.
MAX_VOICE_CHARS = 200_000

#: Jaccard overlap of word shingles above which two files are "the same file".
DUPLICATE_OVERLAP = 0.8


@dataclass
class Scored:
    """One candidate writing sample and what we decided about it.

    Attributes:
        sample: The text sample, possibly with quoted text trimmed out. None
            for a binary file.
        file: The ``(filename, mimetype, bytes)`` tuple. None for text.
        origin: File name, for display.
        score: 0.0 to 1.0. Higher means more like this person's own writing.
        reason: One short, plain, lowercase-first phrase shown to the user.
        verdict: "keep", "unsure" or "drop".
    """

    sample: Sample | None
    file: tuple[str, str, bytes] | None
    origin: str
    score: float
    reason: str
    verdict: str


# ---------------------------------------------------------------------------
# Quoted and forwarded text
# ---------------------------------------------------------------------------

#: "On Tuesday, 3 June 2025 at 09:12, Jo <jo@x.com> wrote:" and its variants.
_ON_WROTE_RE = re.compile(r"^\s*On\b.{0,200}?\bwrote:\s*$", re.IGNORECASE)

#: Outlook style separators.
_ORIGINAL_MESSAGE_RE = re.compile(
    r"^\s*-{2,}\s*(original message|forwarded message|begin forwarded)\b",
    re.IGNORECASE,
)

#: A mail header block pasted mid-body.
_HEADER_LINE_RE = re.compile(
    r"^\s*(from|sent|to|cc|bcc|subject|date|reply-to)\s*:\s*\S", re.IGNORECASE
)

#: Footer boilerplate that ends the human part of a message.
_FOOTER_RE = re.compile(
    r"^\s*(unsubscribe\b|to unsubscribe|this (e-?mail|message) (is|and any)"
    r"|sent from my \w+|confidentiality notice|you are receiving this)",
    re.IGNORECASE,
)


def strip_quoted(text: str) -> tuple[str, float]:
    """Remove quoted, forwarded and footer text from an email-ish body.

    Everything from an "On ... wrote:" line, a "----- Original Message -----"
    separator, a run of pasted mail headers or an unsubscribe footer onward is
    somebody else's voice (or a machine's), so it is cut. Lines starting with
    ``>`` are dropped wherever they appear.

    Returns:
        ``(remaining_text, removed_fraction)`` where the fraction is 0.0 to
        1.0 of the original character count that was removed.
    """
    original_len = len(text)
    if not original_len:
        return "", 0.0

    lines = text.splitlines()
    kept: list[str] = []
    header_run = 0
    for line in lines:
        if _ON_WROTE_RE.match(line) or _ORIGINAL_MESSAGE_RE.match(line):
            break
        if _FOOTER_RE.match(line):
            break
        if _HEADER_LINE_RE.match(line):
            header_run += 1
            # Two or more consecutive mail headers mid-body means a pasted
            # message starts here. One alone might just be a note to self.
            if header_run >= 2:
                if kept:
                    kept.pop()
                break
            kept.append(line)
            continue
        header_run = 0
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)

    remaining = "\n".join(kept).strip()
    removed = 1.0 - (len(remaining) / original_len)
    return remaining, max(0.0, min(1.0, removed))


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z']+")

_FIRST_PERSON = {
    "i", "i'm", "i've", "i'd", "i'll", "im", "ive",
    "me", "my", "mine", "myself",
    "we", "we're", "we've", "our", "ours", "us", "ourselves",
}

_DISCOURSE = {
    "anyway", "honestly", "actually", "basically", "though", "besides",
    "obviously", "frankly", "maybe", "probably", "kind", "sort", "really",
    "just", "still", "but", "so", "because", "well", "guess", "suppose",
}

#: Phrase-level markers only. A single word like "invoice" or "account" is
#: deliberately NOT here: people write about their invoices and their bank in
#: perfectly personal prose, and a bare keyword match would drop that writing.
_BOILERPLATE_MARKERS: tuple[tuple[str, str], ...] = (
    # (regex, reason bucket)
    (r"\bhereinafter\b", "legal"),
    (r"\bwhereas,", "legal"),
    (r"\bshall be deemed\b", "legal"),
    (r"\bin witness whereof\b", "legal"),
    (r"\bpursuant to\b", "legal"),
    (r"\bthe part(?:y|ies) of the\b", "legal"),
    (r"\bterms and conditions\b", "legal"),
    (r"\bgoverning law\b", "legal"),
    (r"\ball rights reserved\b", "legal"),
    (r"\bsecurity deposit\b", "legal"),
    (r"\blessee\b|\blessor\b|\btenant shall\b|\blandlord shall\b", "legal"),
    (r"\binvoice\s*(?:#|no\.?\b|number\b)", "financial"),
    (r"\b(?:total|amount|balance|payment)\s+due\b", "financial"),
    (r"\baccount\s+number\b", "financial"),
    (r"\brouting\s+number\b", "financial"),
    (r"\bsort\s+code\b", "financial"),
    (r"\bstatement\s+period\b", "financial"),
    (r"\b(?:beginning|opening|closing|ending|available)\s+balance\b", "financial"),
    (r"\b(?:gross|net)\s+pay\b", "financial"),
    (r"\bsubtotal\b", "financial"),
    (r"\bsales tax\b|\bvat\b|\btax withheld\b", "financial"),
    (r"\bpolicy\s+number\b", "financial"),
    (r"\bbill(?:ing)?\s+(?:period|address|cycle)\b", "financial"),
    (r"\bremit\s+to\b|\bpay\s+to\s+the\s+order\b", "financial"),
    (r"\bwages,?\s+tips\b|\bform\s+w-?2\b|\bform\s+1099\b", "financial"),
    (r"\bthis is an automated\b|\bdo not reply to this\b", "automated"),
    (r"\bauto(?:matic|mated)[- ]repl(?:y|ies)\b", "automated"),
    (r"\byou are receiving this (?:e-?mail|message)\b", "automated"),
    (r"\bunsubscribe\b", "automated"),
    (r"\bconfidentiality notice\b", "automated"),
    (r"\bdelivery status notification\b", "automated"),
)

_COMPILED_MARKERS = tuple(
    (re.compile(pattern, re.IGNORECASE), bucket)
    for pattern, bucket in _BOILERPLATE_MARKERS
)

#: A line that is mostly a label and a money amount, as in a statement.
_MONEY_LINE_RE = re.compile(
    r"[$£€]\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]*\.\d{2}\b"
)

#: A timestamped log line.
_LOG_LINE_RE = re.compile(
    r"^\s*(?:\[)?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}"
    r"|^\s*(?:DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL)\b"
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")

_CONTRACTION_RE = re.compile(
    r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE
)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _first_person_density(words: list[str]) -> float:
    """Fraction of words that are first-person pronouns."""
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in _FIRST_PERSON)
    return hits / len(words)


def _prose_signals(text: str, words: list[str]) -> float:
    """0.0 to 0.20 bonus for the texture of real prose.

    Contractions, questions, hedging or discourse markers, and varied sentence
    length. Contracts and statements have none of these.
    """
    bonus = 0.0
    if _CONTRACTION_RE.search(text):
        bonus += 0.05
    if "?" in text:
        bonus += 0.05
    if any(w in _DISCOURSE for w in words):
        bonus += 0.05
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) >= 4:
        lengths = [len(_WORD_RE.findall(s)) for s in sentences]
        try:
            if statistics.pstdev(lengths) >= 4.0:
                bonus += 0.05
        except statistics.StatisticsError:  # pragma: no cover - len >= 4 above
            pass
    return bonus


def _looks_machine_generated(text: str) -> str | None:
    """Return a reason bucket if the text is a data dump rather than writing."""
    stripped = text.strip()
    if not stripped:
        return None
    if stripped[0] in "[{" and stripped[-1] in "]}":
        try:
            json.loads(stripped)
        except ValueError:
            pass
        else:
            return "export"
    if stripped.startswith("BEGIN:VCALENDAR") or "\nBEGIN:VEVENT" in stripped:
        return "export"

    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) >= 5:
        log_lines = sum(1 for ln in lines if _LOG_LINE_RE.match(ln))
        if log_lines / len(lines) >= 0.6:
            return "log"
        comma_rows = sum(1 for ln in lines if ln.count(",") >= 3)
        if comma_rows / len(lines) >= 0.8:
            return "export"
    return None


def _money_line_fraction(text: str) -> float:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        return 0.0
    return sum(1 for ln in lines if _MONEY_LINE_RE.search(ln)) / len(lines)


def _caps_heading_fraction(text: str) -> float:
    """Fraction of lines that are short and shouted, as in a form or a form-like PDF."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        return 0.0
    shouted = 0
    for line in lines:
        letters = [c for c in line if c.isalpha()]
        if len(letters) >= 3 and all(c.isupper() for c in letters) and len(line) <= 60:
            shouted += 1
    return shouted / len(lines)


#: Tie-break order when a file trips markers from more than one bucket. The
#: most concrete description wins, because it is the most useful to the user.
_BUCKET_PRIORITY = ("financial", "automated", "export", "log", "legal")

_REASONS = {
    "legal": "looks like a contract, not your writing",
    "financial": "looks like an invoice or statement, not your writing",
    "automated": "reads like an automated message",
    "export": "looks like a data export, not writing",
    "log": "looks like a log file, not writing",
}


def _protected(density: float, words: int, prose: float) -> bool:
    """True when a candidate is sustained first-person prose.

    Protected candidates are never dropped on vocabulary alone. This is the
    guard against the expensive failure: an essay about the month the user
    spent chasing an unpaid invoice is still the user's writing.
    """
    return density >= 0.025 and words >= 120 and prose >= 0.10


def score_text(text: str, origin: str = "") -> tuple[float, str, str]:
    """Score one piece of text on how much it reads like personal writing.

    Args:
        text: The text, already trimmed of quoted replies by :func:`strip_quoted`.
        origin: File name. Contributes a small penalty when it tokenizes to
            an obviously financial or legal name, never enough to decide a
            verdict on its own.

    Returns:
        ``(score, reason, verdict)``. The reason is short, plain and
        lowercase-first, ready to show to a non-technical user.
    """
    body = text.strip()
    if not body:
        return 0.0, "empty", "drop"

    words = _words(body)
    word_count = len(words)
    density = _first_person_density(words)
    prose = _prose_signals(body, words)
    protected = _protected(density, word_count, prose)

    # A haiku, a text message or the two sentences at the top of a reply are
    # real writing even though they are too small to measure confidently. Short
    # text that is first person at all is scored normally rather than being
    # short-circuited: replies are some of the most characteristic writing a
    # person produces, and they are short by nature.
    #
    # The gate is deliberately loose. A reply is often mostly ABOUT the other
    # person ("that's where you sound like yourself") and carries a single
    # "I" in thirty words, so demanding a high first-person density here would
    # throw away the exact case this rule exists for. One first-person pronoun
    # plus either a little density or a little prose texture is enough to be
    # worth scoring; a shopping list and a two-line reminder have neither.
    short = len(body) < MIN_VOICE_CHARS
    first_person = sum(1 for w in words if w in _FIRST_PERSON)
    if short and not (
        first_person >= 1 and word_count >= 10 and (density >= 0.03 or prose >= 0.10)
    ):
        return 0.1, "too short to show a voice", "drop"

    machine = _looks_machine_generated(body)
    if machine and not protected:
        return 0.05, _REASONS[machine], "drop"

    # Match markers against a whitespace-collapsed copy, so a phrase that
    # happens to wrap across two lines still counts.
    flat = " ".join(body.split())
    buckets: dict[str, int] = {}
    for pattern, bucket in _COMPILED_MARKERS:
        if pattern.search(flat):
            buckets[bucket] = buckets.get(bucket, 0) + 1
    marker_hits = sum(buckets.values())

    money_frac = _money_line_fraction(body)
    caps_frac = _caps_heading_fraction(body)

    penalty = 0.20 * min(marker_hits, 4)
    # A nudge only, and through the same separator-normalizing tokenizer the
    # binary rules use. A file called "bank_statement_march.txt" full of chatty
    # first-person prose is still chatty first-person prose, so this can tip a
    # borderline call but must never decide one on its own.
    if origin and _BINARY_DROP_RE.search(_normalize_name(origin)):
        penalty += 0.15
    if money_frac >= 0.20:
        penalty += 0.35
    if caps_frac >= 0.30:
        penalty += 0.15

    # Damp the penalty by how personal the prose is. A statement has a
    # first-person density near zero, so it keeps its full penalty; an essay
    # about money keeps only a fraction of it.
    penalty *= max(0.20, min(1.0, 1.0 - density * 10.0))

    score = 0.45 + min(density / 0.04, 1.0) * 0.30 + prose - penalty

    if len(body) > MAX_VOICE_CHARS:
        score -= 0.20

    score = max(0.0, min(1.0, score))
    if short:
        # There is not enough text to be certain of anything, so cap the
        # confidence. It can still clear the keep threshold on its own merits.
        score = min(score, 0.80)

    if score >= KEEP_THRESHOLD:
        verdict = "keep"
    elif score < DROP_THRESHOLD and not (protected or short):
        verdict = "drop"
    else:
        verdict = "unsure"

    if short:
        reason = "short, but it does sound like you"
    elif verdict == "drop" or (verdict == "unsure" and penalty > 0.15):
        dominant = (
            max(buckets, key=lambda b: (buckets[b], -_BUCKET_PRIORITY.index(b)))
            if buckets
            else None
        )
        if money_frac >= 0.20 and (dominant is None or dominant == "legal"):
            dominant = "financial"
        reason = _REASONS.get(dominant or "", "does not read like personal writing")
    elif len(body) > MAX_VOICE_CHARS:
        reason = "very long, more like a book than a note"
    elif verdict == "keep":
        reason = "sounds like you, first person and conversational"
    else:
        reason = "some of your voice, but hard to be sure"

    return score, reason, verdict


# ---------------------------------------------------------------------------
# Binary files
# ---------------------------------------------------------------------------
#
# HONEST WARNING: we cannot read a PDF or an image without sending it, which is
# the very thing we are trying to avoid doing carelessly. So these files are
# judged on their name and type alone. That is a genuinely weak signal: a
# handwritten journal saved as "scan001.pdf" and a mortgage saved as
# "scan002.pdf" are indistinguishable to this code. Everything here therefore
# lands on "keep" or "unsure", and only an explicit financial or legal word in
# the file name earns a "drop".

#: File-name separators. An underscore is a word character, so matching
#: ``\btax\b`` against the raw stem silently fails on "tax_return_2024" - and
#: an underscore is the commonest separator in a saved document's name. Every
#: file-name rule below therefore runs against the SEPARATOR-NORMALIZED stem,
#: never the raw one.
_NAME_SEPARATOR_RE = re.compile(r"[_\-.\s]+")


def _normalize_name(filename: str) -> str:
    """Return the file stem with every separator turned into a space.

    ``"tax_return_2024.pdf"`` becomes ``"tax return 2024"``, so a plain
    ``\bword\b`` rule matches the way a reader would expect. Also splits
    ``camelCase`` runs, which scanner apps produce.
    """
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stem)
    return _NAME_SEPARATOR_RE.sub(" ", spaced).strip().lower()


_BINARY_DROP_RE = re.compile(
    r"\b(?:invoice|invoices|receipt|receipts|statement|statements"
    r"|payslip|payslips|paystub|paystubs|payroll|payment|payments"
    r"|w2|w4|w9|1099|1040|p60|p45"
    r"|tax|taxes|taxreturn|irs|hmrc|vat"
    r"|bill|billing|utility|utilities"
    r"|lease|tenancy|tenant|landlord|mortgage|deed|escrow"
    r"|contract|agreement|nda|terms|policy|policies|insurance|claim"
    r"|bank|banking|amex|visa|mastercard|paypal|venmo|stripe"
    r"|refund|invoiced|quote|estimate|purchase|order|po"
    r"|passport|licence|license|ssn|medicare|medicaid|benefit|benefits)\b",
    re.IGNORECASE,
)

_BINARY_KEEP_RE = re.compile(
    r"\b(?:img|image|pxl|dsc|dscn|photo|photos|pic|pics|picture"
    r"|screenshot|screen shot|signal|scan note"
    r"|journal|diary|letter|letters|note|notes|essay|essays|draft|drafts"
    r"|poem|poems|story|stories|handwriting|handwritten|writing|writings"
    r"|memoir|entry|entries)\b",
    re.IGNORECASE,
)


def score_binary(filename: str, mimetype: str) -> tuple[float, str, str]:
    """Score a PDF or image on file name and type only.

    This cannot read the file, so it is a name-shaped guess and nothing more.
    It is deliberately generous: only an explicit financial or legal word in
    the name produces a "drop".

    Returns:
        ``(score, reason, verdict)``.
    """
    name = _normalize_name(filename)
    is_pdf = "pdf" in (mimetype or "").lower() or filename.lower().endswith(".pdf")

    if _BINARY_DROP_RE.search(name):
        return 0.15, "the file name looks like a financial or legal document", "drop"
    if _BINARY_KEEP_RE.search(name):
        return 0.70, "a photo or scan, probably handwriting or a screenshot", "keep"
    if is_pdf:
        return 0.45, "a pdf we cannot check without sending it", "unsure"
    return 0.60, "an image, probably handwriting or a screenshot", "keep"


# ---------------------------------------------------------------------------
# Near duplicates
# ---------------------------------------------------------------------------

_NORMALIZE_RE = re.compile(r"[^a-z0-9\s]+")


def _shingles(text: str, size: int = 5) -> frozenset[str]:
    """Normalized 5-word shingles, the cheapest duplicate test that works.

    Chosen over a hash of the whole file because two exports of the same note
    usually differ by a header line or a trailing newline, which defeats an
    exact hash, and over full edit distance because that is quadratic in the
    file size for no extra accuracy at this threshold.
    """
    words = _NORMALIZE_RE.sub(" ", text.lower()).split()
    if len(words) < size:
        return frozenset([" ".join(words)]) if words else frozenset()
    return frozenset(
        " ".join(words[i : i + size]) for i in range(len(words) - size + 1)
    )


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap of two shingle sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


def _rank(item: Scored) -> tuple[float, int, str]:
    """Sort key: best score first, then the tighter copy, then the name.

    The length tie-break matters for near duplicates: two exports of the same
    note score identically, and the one carrying an extra "Exported from ..."
    header is the worse copy.
    """
    length = len(item.sample.text) if item.sample is not None else 0
    return (-item.score, length, item.origin)


def triage(
    samples: list[Sample],
    files: list[tuple[str, str, bytes]],
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
) -> tuple[list[Scored], list[Scored]]:
    """Sort candidate writing samples into what to send and what to set aside.

    Pure, offline, no network. Nothing is deleted: every input appears in
    exactly one of the two returned lists.

    Args:
        samples: Text samples, as returned by ``sources.load``.
        files: ``(filename, mimetype, bytes)`` tuples for PDFs and images.
        budget_chars: Total characters of text one run may send. Applied to the
            kept list from the best score down. Binary files are not counted
            against it, because their cost is bytes rather than characters and
            their number is already capped by ``sources.MAX_FILES``.

    Returns:
        ``(kept, rejected)``, each sorted best score first.

        ``kept`` holds the "keep" and "unsure" verdicts for TEXT, because we
        have read that text and a wrongly dropped sample costs the user more
        than a wasted one. ``rejected`` holds every "drop" verdict, anything
        that did not fit the character budget, and every "unsure" BINARY: a
        PDF we cannot read is judged on its file name alone, so the safe
        default there is to make the user opt it in.
    """
    scored: list[Scored] = []

    for sample in samples or []:
        trimmed, removed = strip_quoted(sample.text or "")
        score, reason, verdict = score_text(trimmed, sample.origin)
        if removed >= 0.5:
            # The remainder is judged on its own merits by score_text, which
            # already knows how to read short first-person prose. Applying a
            # second length floor here would throw away exactly the writing
            # this branch exists to rescue: a short, characteristic reply.
            if verdict == "drop":
                reason = "mostly a quoted reply from someone else"
                score = min(score, 0.15)
            elif reason != "short, but it does sound like you":
                reason = "trimmed a quoted reply, kept your part"
        body = trimmed if removed > 0.0 else (sample.text or "")
        scored.append(
            Scored(
                sample=Sample(
                    kind=sample.kind,
                    origin=sample.origin,
                    text=body,
                    author=sample.author,
                    tokens=sample.tokens,
                ),
                file=None,
                origin=sample.origin,
                score=score,
                reason=reason,
                verdict=verdict,
            )
        )

    for entry in files or []:
        name, mimetype, _ = entry
        score, reason, verdict = score_binary(name, mimetype)
        scored.append(
            Scored(
                sample=None,
                file=entry,
                origin=name,
                score=score,
                reason=reason,
                verdict=verdict,
            )
        )

    scored.sort(key=_rank)

    # Near-duplicate pass: compare each text candidate only against
    # better-scoring ones already accepted, so the best copy always survives.
    accepted: list[tuple[str, frozenset[str]]] = []
    for item in scored:
        if item.sample is None or item.verdict == "drop":
            continue
        fingerprint = _shingles(item.sample.text)
        twin = next(
            (name for name, other in accepted if _overlap(fingerprint, other) >= DUPLICATE_OVERLAP),
            None,
        )
        if twin is not None:
            item.verdict = "drop"
            item.reason = f"nearly identical to {twin}"
            item.score = min(item.score, 0.2)
        else:
            accepted.append((item.origin, fingerprint))

    kept: list[Scored] = []
    rejected: list[Scored] = []
    used = 0
    for item in scored:
        if item.verdict == "drop":
            rejected.append(item)
            continue
        # An unreadable binary we are unsure about is the one case where we
        # know least and the downside is largest: shipping a private document
        # off the machine. Text we have actually read, so "unsure" there means
        # weak evidence; for a PDF it means no evidence at all, only a file
        # name. So unsure binaries land in `rejected` for the user to opt in,
        # rather than in `kept` for the user to notice and opt out.
        if item.sample is None and item.verdict == "unsure":
            rejected.append(item)
            continue
        cost = len(item.sample.text) if item.sample is not None else 0
        # A zero-cost item (a binary) can never be squeezed out by the
        # character budget, and the first item is always kept: returning an
        # empty selection because of a tight budget would be useless.
        if cost and kept and used + cost > budget_chars:
            item.reason = "no room left in this run"
            rejected.append(item)
            continue
        used += cost
        kept.append(item)

    rejected.sort(key=_rank)
    return kept, rejected
