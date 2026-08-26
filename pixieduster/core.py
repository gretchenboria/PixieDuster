"""Gemini API calls and the two generation pipelines.

Lifted out of the Streamlit app and generalised so both the web UI and the CLI
share one implementation.

Security: the API key is sent in the ``x-goog-api-key`` header, never in the
URL, and every error message that leaves this module is passed through
``_sanitize`` first. ``str(GeminiError)`` is safe to paste into a bug report.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Callable, Iterable, Sequence

import requests

from .prompts import (
    CONFIDENCE_INSTRUCTION,
    INVENT_QUESTIONS_INSTRUCTION,
    INVENT_RUBRIC,
    ANTI_AI_PROMPT_TEMPLATE,
    PERSONA_RUBRIC,
    QUESTION_SCHEMA,
    QUESTIONS_INSTRUCTION,
)
from .types import Question, Sample

__all__ = [
    "API_BASE",
    "DEFAULT_MODEL",
    "MAX_ATTEMPTS",
    "RETRY_BASE_DELAY",
    "RETRY_MAX_DELAY",
    "RETRY_STATUSES",
    "GeminiError",
    "call_gemini",
    "chat_gemini",
    "list_models",
    "generate_questions",
    "generate_persona",
]

#: Base URL for the Generative Language REST API.
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

#: Model used unless overridden by --model or [settings] model.
DEFAULT_MODEL = "gemini-3.6-flash"

#: Total tries for one request, including the first. 3 means two retries.
MAX_ATTEMPTS = 3

#: First backoff wait in seconds. Doubles each retry, capped by RETRY_MAX_DELAY.
RETRY_BASE_DELAY = 1.0

#: Ceiling on a single backoff wait, including a server's own Retry-After.
RETRY_MAX_DELAY = 20.0

#: HTTP statuses worth trying again. 429 is the hosted proxy's rate limit and
#: 5xx is the API having a bad minute. 400/401/403 are never retried: the
#: request is wrong or the credential is, and repeating it wastes the user's
#: time and quota.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: Optional module-level ``(attempt, delay_seconds, why) -> None`` hook, called
#: before each backoff wait so a UI can say "rate limited, retrying in 2s".
#: Set it rather than importing ui here, which would make core depend on a
#: presentation layer. A per-call ``on_retry=`` argument overrides it.
RETRY_NOTIFIER: Callable[[int, float, str], None] | None = None

#: Mime types we inline as plain text rather than base64 blobs.
_TEXT_MIME_EXTRA = {"application/json", "text/markdown", "text/csv"}

# key=... in a query string, and anything shaped like a Google API key.
_KEY_QUERY_RE = re.compile(r"([?&](?:key|api_key)=)[^&\s\"'<>]+", re.IGNORECASE)
_GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{10,}")


def _sanitize(text: object, api_key: str | None = None) -> str:
    """Strip anything key-shaped out of ``text``.

    Removes ``?key=…`` / ``&key=…`` query parameters, redacts Google API keys
    by their ``AIza`` prefix, and - when the live key is known - removes that
    exact string too.
    """
    out = str(text)
    if api_key:
        stripped = api_key.strip()
        if len(stripped) >= 8:
            out = out.replace(stripped, "<REDACTED-API-KEY>")
    out = _KEY_QUERY_RE.sub(r"\1<REDACTED>", out)
    out = _GOOGLE_KEY_RE.sub("<REDACTED-API-KEY>", out)
    return out


class GeminiError(RuntimeError):
    """A failed Gemini call. ``str(self)`` never contains the API key."""

    def __init__(self, message: object, api_key: str | None = None) -> None:
        super().__init__(_sanitize(message, api_key))


def _headers(api_key: str, base_url: str | None = None) -> dict[str, str]:
    """Auth + content headers. The credential goes in a header, never the URL.

    Against Google directly the credential is the user's own Gemini key. Against
    the hosted proxy it is a Hugging Face token, and the proxy supplies the
    Gemini key on its side -- so the two use different header names.
    """
    if base_url:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    return {"Content-Type": "application/json", "x-goog-api-key": api_key}


def _endpoint(model: str, method: str = "generateContent",
              base_url: str | None = None) -> str:
    """Build a model endpoint URL (no credentials in it)."""
    name = model.strip()
    if name.startswith("models/"):
        name = name[len("models/") :]
    root = (base_url or API_BASE).rstrip("/")
    return f"{root}/models/{name}:{method}"


def _error_detail(response: requests.Response) -> str:
    """Pull the API's own message out of an error response, if there is one."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:500]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                status = error.get("status")
                return f"{message}" + (f" ({status})" if status else "")
    return json.dumps(body)[:500]


#: Transport failures worth trying again. Everything else in the
#: ``RequestException`` tree (a bad URL, too many redirects, an SSL error) will
#: fail identically the second time, so it is raised at once.
_RETRYABLE_EXCEPTIONS = (
    requests.Timeout,
    requests.ConnectionError,
)


def _retry_after_seconds(response: object) -> float | None:
    """Read a ``Retry-After`` header, in seconds. None when absent or unparsable.

    Only the delay-seconds form is honored. The HTTP-date form is rarer here
    and parsing it wrong would mean sleeping for hours.
    """
    headers = getattr(response, "headers", None) or {}
    try:
        raw = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:  # pragma: no cover - a non-mapping headers object
        return None
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except ValueError:
        return None
    if value < 0:
        return None
    return min(value, RETRY_MAX_DELAY)


def _backoff_delay(attempt: int, response: object | None = None) -> float:
    """Seconds to wait before try number ``attempt + 1``.

    Exponential from :data:`RETRY_BASE_DELAY`, capped at
    :data:`RETRY_MAX_DELAY`, but a server's own ``Retry-After`` wins when it
    asks for longer.
    """
    delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
    server = _retry_after_seconds(response) if response is not None else None
    if server is not None:
        delay = min(max(delay, server), RETRY_MAX_DELAY)
    return delay


def _notify_retry(
    on_retry: Callable[[int, float, str], None] | None,
    attempt: int,
    delay: float,
    why: str,
) -> None:
    """Tell the caller we are about to wait. A broken callback never fails a run."""
    callback = on_retry or RETRY_NOTIFIER
    if callback is None:
        return
    try:
        callback(attempt, delay, why)
    except Exception:  # pragma: no cover - a UI bug must not kill the request
        pass


def _post(url: str, api_key: str, payload: dict[str, Any], timeout: int,
          base_url: str | None = None, *,
          attempts: int = MAX_ATTEMPTS,
          on_retry: Callable[[int, float, str], None] | None = None) -> dict[str, Any]:
    """POST JSON and return the parsed body, raising ``GeminiError`` on trouble.

    Transient failures - a timeout, a dropped connection, a 429 from the hosted
    proxy, a 5xx from the API - are retried up to ``attempts`` times with
    exponential backoff. A 400, 401 or 403 is raised immediately, and so is
    anything that happens *after* a successful response, so a request that the
    server already accepted is never sent twice.

    Args:
        attempts: Total tries including the first. 1 disables retrying.
        on_retry: ``(attempt, delay_seconds, why) -> None``, called before each
            wait. Overrides :data:`RETRY_NOTIFIER`.
    """
    total = max(1, attempts)
    for attempt in range(1, total + 1):
        try:
            response = requests.post(
                url, headers=_headers(api_key, base_url), json=payload, timeout=timeout
            )
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt >= total:
                raise GeminiError(
                    f"Could not reach the Gemini API after {total} tries: {exc}", api_key
                ) from None
            delay = _backoff_delay(attempt)
            _notify_retry(on_retry, attempt, delay, "the connection failed")
            time.sleep(delay)
            continue
        except requests.RequestException as exc:
            raise GeminiError(f"Could not reach the Gemini API: {exc}", api_key) from None

        status = getattr(response, "status_code", 200)
        if status >= 400:
            retryable = status in RETRY_STATUSES or status >= 500
            if retryable and attempt < total:
                delay = _backoff_delay(attempt, response)
                why = (
                    "the daily limit or rate limit was hit"
                    if status == 429
                    else f"the server returned {status}"
                )
                _notify_retry(on_retry, attempt, delay, why)
                time.sleep(delay)
                continue
            raise GeminiError(
                f"Gemini API error {status}: {_error_detail(response)}",
                api_key,
            ) from None

        # From here the server has accepted and answered the request. Whatever
        # goes wrong next is not something a second identical POST would fix.
        try:
            return response.json()
        except ValueError:
            raise GeminiError(
                "Gemini API returned a response that was not JSON.", api_key
            ) from None

    raise GeminiError("Could not reach the Gemini API.", api_key)  # pragma: no cover


def _extract_text(body: dict[str, Any], api_key: str | None = None) -> str:
    """Pull the generated text out of a generateContent response.

    Joins every text part rather than trusting ``parts[0]``, which is what the
    Streamlit app did and which silently truncated multi-part answers.
    """
    if isinstance(body.get("promptFeedback"), dict):
        blocked = body["promptFeedback"].get("blockReason")
        if blocked:
            raise GeminiError(
                f"Gemini blocked the request ({blocked}). Try fewer or different samples.",
                api_key,
            )
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise GeminiError("Gemini returned no candidates.", api_key)
    first = candidates[0] or {}
    parts = (first.get("content") or {}).get("parts") or []
    chunks = [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if not chunks:
        reason = first.get("finishReason")
        raise GeminiError(
            "Gemini returned an empty response"
            + (f" (finishReason={reason})." if reason else ".")
            + " Try again.",
            api_key,
        )
    return "".join(chunks)


def _file_parts(files: Iterable[tuple[str, str, bytes]] | None) -> list[dict[str, Any]]:
    """Turn ``(filename, mimetype, bytes)`` tuples into request parts."""
    parts: list[dict[str, Any]] = []
    for filename, mime_type, data in files or []:
        mime_type = mime_type or "application/octet-stream"
        if mime_type.startswith("text/") or mime_type in _TEXT_MIME_EXTRA:
            text_data = bytes(data).decode("utf-8", errors="replace")
            parts.append(
                {
                    "text": f"\n\n--- Document: {filename} ---\n{text_data}\n--- End Document ---\n"
                }
            )
        else:
            b64_data = base64.b64encode(bytes(data)).decode("utf-8")
            parts.append({"inlineData": {"mimeType": mime_type, "data": b64_data}})
    return parts


def _inline_text_parts(inline_texts: Iterable[tuple[str, str]] | None) -> list[dict[str, Any]]:
    """Turn ``(label, text)`` pairs into delimited text parts."""
    return [
        {"text": f"\n\n--- Document: {label} ---\n{text}\n--- End Document ---\n"}
        for label, text in (inline_texts or [])
    ]


def call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    *,
    files: Sequence[tuple[str, str, bytes]] | None = None,
    inline_texts: Sequence[tuple[str, str]] | None = None,
    schema: dict | None = None,
    timeout: int = 120,
    base_url: str | None = None,
    on_retry: Callable[[int, float, str], None] | None = None,
) -> str:
    """Single-turn generateContent call.

    Args:
        api_key: Gemini API key. Sent as a header; never placed in the URL.
        model: Model id, with or without the ``models/`` prefix.
        prompt: The instruction text, sent as the first part.
        files: ``(filename, mimetype, bytes)`` tuples. Text-ish types are
            inlined as text; everything else is base64 ``inlineData``.
        inline_texts: ``(label, text)`` pairs appended as text parts.
        schema: If given, sets ``responseMimeType=application/json`` and
            ``responseSchema`` so the model must answer in that shape.
        timeout: Per-request timeout in seconds.
        on_retry: ``(attempt, delay_seconds, why) -> None``, called before each
            backoff wait so the caller can show the pause. Transient failures
            (timeout, dropped connection, 429, 5xx) are retried
            :data:`MAX_ATTEMPTS` times; 400, 401 and 403 never are.

    Returns:
        The generated text.

    Raises:
        GeminiError: On transport failure, an API error, or an empty response.
            The message carries the API's own wording with the key stripped.
    """
    if not api_key:
        raise GeminiError("No Gemini API key was provided.")
    parts: list[dict[str, Any]] = [{"text": prompt}]
    parts.extend(_file_parts(files))
    parts.extend(_inline_text_parts(inline_texts))

    payload: dict[str, Any] = {"contents": [{"parts": parts}]}
    if schema is not None:
        payload["generationConfig"] = {
            "responseMimeType": "application/json",
            "responseSchema": schema,
        }
    body = _post(
        _endpoint(model, base_url=base_url), api_key, payload, timeout, base_url,
        on_retry=on_retry,
    )
    return _extract_text(body, api_key)


def chat_gemini(
    api_key: str,
    model: str,
    sys_prompt: str,
    history: Sequence[dict[str, str]],
    user_input: str,
    *,
    timeout: int = 120,
    base_url: str | None = None,
    on_retry: Callable[[int, float, str], None] | None = None,
) -> str:
    """Multi-turn chat against a persona system prompt.

    Args:
        api_key: Gemini API key.
        model: Model id.
        sys_prompt: The persona document, sent as ``systemInstruction``.
        history: ``[{"role": "user"|"assistant", "content": str}, …]``.
        user_input: The new user turn.
        timeout: Per-request timeout in seconds.

    Returns:
        The assistant's reply text.

    Raises:
        GeminiError: As for :func:`call_gemini`.
    """
    if not api_key:
        raise GeminiError("No Gemini API key was provided.")
    contents: list[dict[str, Any]] = []
    for msg in history or []:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": user_input}]})

    payload = {
        "systemInstruction": {"parts": [{"text": sys_prompt}]},
        "contents": contents,
    }
    body = _post(
        _endpoint(model, base_url=base_url), api_key, payload, timeout, base_url,
        on_retry=on_retry,
    )
    return _extract_text(body, api_key)


def list_models(api_key: str, *, timeout: int = 30,
                base_url: str | None = None) -> list[str]:
    """List the model ids this key can see.

    Returns bare ids (the ``models/`` prefix is stripped), so the result can be
    compared directly against :data:`DEFAULT_MODEL`.

    Raises:
        GeminiError: On transport failure or an API error.
    """
    if not api_key:
        raise GeminiError("No Gemini API key was provided.")
    ids: list[str] = []
    page_token: str | None = None
    for _ in range(20):  # hard cap; the model list is short
        params = {"pageSize": 200}
        if page_token:
            params["pageToken"] = page_token
        try:
            response = requests.get(
                f"{(base_url or API_BASE).rstrip(chr(47))}/models",
                headers=_headers(api_key, base_url),
                params=params,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise GeminiError(f"Could not reach the Gemini API: {exc}", api_key) from None
        if response.status_code >= 400:
            raise GeminiError(
                f"Gemini API error {response.status_code}: {_error_detail(response)}",
                api_key,
            ) from None
        try:
            body = response.json()
        except ValueError:
            raise GeminiError("Model list response was not JSON.", api_key) from None
        for entry in body.get("models") or []:
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str) and name:
                ids.append(name[len("models/") :] if name.startswith("models/") else name)
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    return ids


def _strip_fences(text: str) -> str:
    """Remove ```json … ``` fencing the model sometimes adds around JSON."""
    clean = (text or "").strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return clean.strip()


def _coerce_questions(data: Any) -> list[Question]:
    """Normalise every shape the API has been seen to return.

    Accepts a bare array of question objects, ``{"questions": [...]}``, and a
    lone question object. Entries missing a question or options are dropped.
    """
    if isinstance(data, dict):
        for key in ("questions", "Questions", "items", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            if "question" in data:
                data = [data]
            else:
                return []
    if not isinstance(data, list):
        return []

    out: list[Question] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        text = entry.get("question") or entry.get("prompt") or entry.get("text")
        options = entry.get("options") or entry.get("choices") or []
        if not isinstance(text, str) or not text.strip():
            continue
        if isinstance(options, str):
            options = [options]
        clean_options = [str(o) for o in options if str(o).strip()]
        if not clean_options:
            continue
        out.append(Question(question=text.strip(), options=clean_options))
    return out


def _samples_to_inline(samples: Sequence[Sample] | None) -> list[tuple[str, str]]:
    """Label each sample with its kind and origin for the model."""
    return [
        (f"{s.kind}: {s.origin}" if s.kind else s.origin, s.text)
        for s in (samples or [])
        if (s.text or "").strip()
    ]


def generate_questions(
    api_key: str,
    model: str,
    target_name: str,
    samples: Sequence[Sample],
    n: int = 3,
    *,
    description: str | None = None,
    files: Sequence[tuple[str, str, bytes]] | None = None,
    timeout: int = 120,
    base_url: str | None = None,
    on_retry: Callable[[int, float, str], None] | None = None,
) -> list[Question]:
    """Ask the model for ``n`` multiple-choice profiling questions.

    Tolerates both response shapes the API produces - a bare JSON array and
    ``{"questions": [...]}`` - and strips ``` fences before parsing.

    Raises:
        GeminiError: On an API failure, or on JSON the model malformed. The
            message suggests retrying, because a retry usually succeeds.
    """
    if description and not samples and not files:
        prompt = INVENT_QUESTIONS_INSTRUCTION.format(
            target_name=target_name or "the persona", description=description, n=n
        )
    else:
        prompt = QUESTIONS_INSTRUCTION.format(target_name=target_name or "the author", n=n)
        if description:
            prompt += (
                f"\n\nThe user also describes this persona as: \"{description}\". "
                "Let that steer the questions where the samples are ambiguous."
            )
    raw = call_gemini(
        api_key,
        model,
        prompt,
        files=files,
        inline_texts=_samples_to_inline(samples),
        schema=QUESTION_SCHEMA,
        timeout=timeout,
        base_url=base_url,
        on_retry=on_retry,
    )
    clean = _strip_fences(raw)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        raise GeminiError(
            "The AI generated a malformed JSON payload (likely an unescaped "
            "quote). Run it again to let it retry.",
            api_key,
        ) from None

    questions = _coerce_questions(data)
    if not questions:
        raise GeminiError(
            "The AI returned JSON with no usable questions in it. Run it again "
            "to let it retry.",
            api_key,
        )
    return questions[:n] if n and len(questions) > n else questions


def generate_persona(
    api_key: str,
    model: str,
    target_name: str,
    samples: Sequence[Sample],
    answers: Sequence[tuple[str, str]],
    *,
    description: str | None = None,
    files: Sequence[tuple[str, str, bytes]] | None = None,
    timeout: int = 180,
    base_url: str | None = None,
    on_retry: Callable[[int, float, str], None] | None = None,
) -> str:
    """Run the profiling rubric and return the finished persona document.

    Args:
        answers: ``(question, chosen_option)`` pairs from the Q&A step.
        files: Optional raw uploads, for callers (the web app) that have them.

    Returns:
        The full document: the model's extracted persona already wrapped in
        :data:`prompts.ANTI_AI_PROMPT_TEMPLATE`.
    """
    formatted_answers = "\n\n".join(
        f"Q: {question}\nA: {answer}" for question, answer in (answers or [])
    )
    name = target_name or "the author"

    if description and not samples and not files:
        # No evidence to work from: design the persona instead of extracting it.
        instruction = (
            INVENT_RUBRIC.format(target_name=name, description=description)
            + "\n\nThe creator answered these questions about it:\n"
            + formatted_answers
        )
        extracted = call_gemini(api_key, model, instruction, timeout=timeout,
                                base_url=base_url, on_retry=on_retry)
        return ANTI_AI_PROMPT_TEMPLATE.replace("{extracted_persona}", extracted)

    # Tell the model how much it actually had to work from. Without this it
    # writes with the same confidence off four samples as off four hundred.
    words = sum(len(s.text.split()) for s in samples)
    parts = []
    if samples:
        parts.append(f"{len(samples)} text sample(s), about {words:,} words in total")
    if files:
        parts.append(f"{len(files)} image(s) or document(s) you must read yourself")
    evidence = " and ".join(parts) if parts else "no writing samples at all"
    if samples and words < 400:
        evidence += ". That is very little. Expect most claims to be provisional"

    described = (
        f"The user describes this persona as: \"{description}\". Honour that description; "
        "use the samples as evidence for how it should sound.\n\n"
        if description
        else ""
    )
    instruction = (
        described
        + f"Here are the original writing samples for '{name}'. "
        "I also asked the user some multiple choice questions to refine the persona.\n"
        f"Here are their answers:\n{formatted_answers}\n\n"
        + "\n\n"
        + PERSONA_RUBRIC.replace("{evidence}", evidence)
    )
    extracted = call_gemini(
        api_key,
        model,
        instruction,
        files=files,
        inline_texts=_samples_to_inline(samples),
        timeout=timeout,
        base_url=base_url,
        on_retry=on_retry,
    )
    return ANTI_AI_PROMPT_TEMPLATE.replace("{extracted_persona}", extracted)
