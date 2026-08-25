"""Hosted mode: use the PixieDuster Space instead of your own Gemini key.

The Space holds one Gemini key as a server-side secret and meters usage per
Hugging Face account. The CLI authenticates with the user's own HF token, which
is a credential they already have and can revoke, and which never grants the
Space anything beyond identifying them.

The proxy deliberately mirrors Google's API shape, so :mod:`pixieduster.core`
talks to it with the same code path -- only ``base_url`` and the auth header
differ.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests

#: The hosted endpoint. Overridable for local development and testing.
DEFAULT_ENDPOINT = "https://pixieduster-api.me-c41.workers.dev/api"

#: Where `huggingface-cli login` puts the token, so users already signed in to
#: Hugging Face need no extra step.
HF_TOKEN_PATHS = (
    Path.home() / ".cache" / "huggingface" / "token",
    Path.home() / ".huggingface" / "token",
)

TOKEN_PAGE = "https://huggingface.co/settings/tokens"


class HostedError(RuntimeError):
    """The hosted service refused or could not be reached.

    Never contains the user's token.
    """


def endpoint() -> str:
    """The API root, honouring ``PIXIEDUSTER_ENDPOINT`` for local testing."""
    return os.environ.get("PIXIEDUSTER_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")


def resolve_token(explicit: str | None = None) -> str | None:
    """Find a Hugging Face token. First hit wins, never logged.

    1. ``explicit`` (a ``--hf-token`` flag)
    2. ``HF_TOKEN`` or ``HUGGING_FACE_HUB_TOKEN`` in the environment
    3. the token written by ``huggingface-cli login``
    4. ``[auth] hf_token`` in the PixieDuster config file
    """
    if explicit:
        return explicit.strip()

    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()

    for path in HF_TOKEN_PATHS:
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:  # pragma: no cover - unreadable cache
            continue

    from . import config

    stored = config.load_config().get("auth", {}).get("hf_token")
    return stored.strip() if isinstance(stored, str) and stored.strip() else None


def token_source(explicit: str | None = None) -> str:
    """Which of the four sources supplied the token. Display only."""
    if explicit:
        return "flag"
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        if os.environ.get(var, "").strip():
            return "env"
    for path in HF_TOKEN_PATHS:
        try:
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                return "huggingface-cli"
        except OSError:  # pragma: no cover
            continue
    from . import config

    if config.load_config().get("auth", {}).get("hf_token"):
        return "config"
    return "none"


def _describe(response: requests.Response) -> str:
    """The server's own message, if it sent one."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:400]
    if isinstance(body, dict):
        for key in ("detail", "message", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return value["message"]
    return str(body)[:400]


def check(token: str, *, timeout: int = 20) -> dict:
    """Ask the Space who this token belongs to and what quota is left.

    Returns:
        ``{"user": str, "used": int, "limit": int, "remaining": int,
        "resets_at": str}``.

    Raises:
        HostedError: If the token is rejected or the Space is unreachable.
    """
    try:
        response = requests.get(
            f"{endpoint()}/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise HostedError(
            f"Could not reach the PixieDuster service: {exc.__class__.__name__}. "
            "Check your connection, or use your own key with --api-key."
        ) from None

    if response.status_code == 401:
        raise HostedError(
            "Hugging Face rejected that token. Make a new one at "
            f"{TOKEN_PAGE} (a read token is enough), then run: pixieduster login"
        )
    if response.status_code >= 400:
        raise HostedError(_describe(response) or f"Service error {response.status_code}.")

    try:
        return response.json()
    except ValueError:
        raise HostedError("The service returned a response that was not JSON.") from None


def quota_message(info: dict) -> str:
    """A one-line human summary of remaining quota."""
    remaining = info.get("remaining")
    limit = info.get("limit")
    user = info.get("user", "you")
    if remaining is None or limit is None:
        return f"Signed in as {user}."
    resets = info.get("resets_at")
    tail = f" Resets {resets}." if resets else ""
    return f"Signed in as {user}. {remaining} of {limit} personas left today.{tail}"


__all__ = [
    "DEFAULT_ENDPOINT",
    "TOKEN_PAGE",
    "HostedError",
    "endpoint",
    "resolve_token",
    "token_source",
    "check",
    "quota_message",
]
