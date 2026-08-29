"""PixieDuster hosted API - a metered proxy in front of Gemini.

The Gemini key lives here as a Space secret and never reaches a client. Callers
authenticate with their own Hugging Face token; we verify it against the HF API,
meter per account, and refuse to spend past a global daily ceiling.

Deliberate design choices:

* The proxy mirrors Google's URL shape (``/models/{model}:generateContent``) so
  the CLI reaches it through the same code path as a direct call.
* Quota is charged per *generateContent* call, not per byte, and is checked and
  incremented before the upstream call so a slow request cannot be raced. Calls
  are billed to one of two meters -- personas, or the looser interview/chat
  budget -- according to the ``X-Op`` header the web app sends.
* The global ceiling fails **closed**: if the counter store is unavailable, the
  service refuses rather than spending an unknown amount.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# --------------------------------------------------------------------------
# configuration (all overridable as Space variables)
# --------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

#: Personas one Hugging Face account may generate per UTC day.
DAILY_PER_USER = int(os.environ.get("DAILY_PER_USER", "5"))

#: Interview questions and try-it-out chat turns per account per UTC day. These
#: are metered apart from personas so that testing a persona -- or answering the
#: interview that produces one -- cannot cost you the next persona.
DAILY_AUX_PER_USER = int(os.environ.get("DAILY_AUX_PER_USER", "50"))

#: Hard ceiling across everyone. This is the number that protects the bill.
DAILY_GLOBAL = int(os.environ.get("DAILY_GLOBAL", "800"))

#: Largest request body we will forward, in bytes.
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(6 * 1024 * 1024)))

#: Models callers may ask for. Anything else is refused, so nobody can bill us
#: for an expensive model we did not budget for.
ALLOWED_MODELS = {
    m.strip()
    for m in os.environ.get(
        "ALLOWED_MODELS", "gemini-3.6-flash,gemini-2.5-flash,gemini-2.5-flash-lite"
    ).split(",")
    if m.strip()
}

#: HF Spaces persistent storage if it is enabled, otherwise ephemeral.
DB_PATH = Path(os.environ.get("QUOTA_DB", "/data/quota.db"))

UPSTREAM_TIMEOUT = int(os.environ.get("UPSTREAM_TIMEOUT", "180"))

app = FastAPI(title="PixieDuster", docs_url=None, redoc_url=None)

#: The stlite web app, served from the same Space so the public URL keeps
#: working. Mounted last, after the /api routes, so it never shadows them.
STATIC_DIR = Path(__file__).resolve().parent / "static"

_lock = threading.Lock()
_identity_cache: dict[str, tuple[str, float]] = {}
IDENTITY_TTL = 300.0


# --------------------------------------------------------------------------
# quota store
# --------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        path = DB_PATH
    except OSError:
        # No persistent volume on this Space. Fall back to ephemeral storage and
        # accept that a restart resets counters - better than refusing to run.
        path = Path("/tmp/quota.db")
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS usage ("
        " day TEXT NOT NULL, who TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,"
        " PRIMARY KEY (day, who))"
    )
    return conn


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _resets_at() -> str:
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def _meter_key(user: str, op: str) -> str:
    """The counter row an op is billed against.

    Personas keep the bare username so existing rows keep counting; the looser
    interview/chat budget gets its own row.
    """
    return f"{user}#aux" if op == "aux" else user


def _op_of(header: str) -> str:
    """Classify a call from its ``X-Op`` header.

    The CLI sends no header and is always generating a persona, so anything
    absent or unrecognised reads as ``persona`` -- the conservative default.
    """
    return "aux" if header.strip().lower() in {"interview", "chat"} else "persona"


def _counts(key: str) -> tuple[int, int]:
    """(this row's count today, everyone's count today)."""
    with _connect() as conn:
        day = _today()
        mine = conn.execute(
            "SELECT n FROM usage WHERE day=? AND who=?", (day, key)
        ).fetchone()
        total = conn.execute(
            "SELECT COALESCE(SUM(n), 0) FROM usage WHERE day=?", (day,)
        ).fetchone()
    return (mine[0] if mine else 0), (total[0] if total else 0)


def _charge(key: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage (day, who, n) VALUES (?, ?, 1) "
            "ON CONFLICT(day, who) DO UPDATE SET n = n + 1",
            (_today(), key),
        )
        conn.commit()


def _refund(key: str) -> None:
    """Give a charge back when the upstream call never happened."""
    with _connect() as conn:
        conn.execute(
            "UPDATE usage SET n = MAX(n - 1, 0) WHERE day=? AND who=?", (_today(), key)
        )
        conn.commit()


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

def whoami(authorization: str = Header(default="")) -> str:
    """Verify the caller's Hugging Face token and return their username.

    The token is only ever sent to huggingface.co, never stored, never logged.
    """
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "Sign in first: run 'pixieduster login'.")

    now = time.monotonic()
    cached = _identity_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]

    try:
        response = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except requests.RequestException:
        raise HTTPException(503, "Could not reach Hugging Face to verify your token.")

    if response.status_code == 401:
        raise HTTPException(401, "Hugging Face rejected that token.")
    if response.status_code >= 400:
        raise HTTPException(502, "Hugging Face could not verify that token.")

    name = (response.json() or {}).get("name")
    if not name:
        raise HTTPException(401, "That token has no account attached to it.")

    with _lock:
        _identity_cache[token] = (name, now + IDENTITY_TTL)
        if len(_identity_cache) > 2000:  # keep the cache from growing forever
            _identity_cache.clear()
    return name


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness, and whether the Space is configured at all."""
    return {"ok": True, "configured": bool(GEMINI_API_KEY), "models": sorted(ALLOWED_MODELS)}


@app.get("/api/me")
def me(user: str = Depends(whoami)) -> dict[str, Any]:
    """Who the caller is, and how much quota is left today."""
    try:
        mine, _ = _counts(_meter_key(user, "persona"))
        aux, _ = _counts(_meter_key(user, "aux"))
    except sqlite3.Error:
        raise HTTPException(503, "Quota store unavailable. Try again shortly.")
    return {
        "user": user,
        # used/limit/remaining are the persona allowance, unchanged.
        "used": mine,
        "limit": DAILY_PER_USER,
        "remaining": max(DAILY_PER_USER - mine, 0),
        # The interview + try-it-out chat budget, which personas do not touch.
        "aux_used": aux,
        "aux_limit": DAILY_AUX_PER_USER,
        "aux_remaining": max(DAILY_AUX_PER_USER - aux, 0),
        "resets_at": _resets_at(),
    }


@app.get("/api/models")
def models(user: str = Depends(whoami)) -> dict[str, Any]:
    """Mirror of Google's list shape, filtered to what we allow."""
    return {"models": [{"name": f"models/{m}"} for m in sorted(ALLOWED_MODELS)]}


@app.post("/api/models/{spec:path}")
async def generate(
    spec: str,
    request: Request,
    user: str = Depends(whoami),
    x_op: str = Header(default=""),
) -> Any:
    """Proxy ``{model}:generateContent`` to Gemini, metered.

    ``spec`` arrives as ``gemini-3.6-flash:generateContent``.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(503, "This Space has no Gemini key configured.")

    model, _, method = spec.partition(":")
    model = model.removeprefix("models/")
    if method not in {"generateContent", "streamGenerateContent"}:
        raise HTTPException(404, f"Unsupported method: {method or '(none)'}")
    if model not in ALLOWED_MODELS:
        raise HTTPException(
            400,
            f"Model '{model}' is not available here. Allowed: {', '.join(sorted(ALLOWED_MODELS))}",
        )

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(
            413,
            f"That request is {len(body) / 1_048_576:.1f} MB, over the "
            f"{MAX_BODY_BYTES / 1_048_576:.0f} MB limit. Send fewer samples.",
        )

    # Check and charge before spending, so concurrent calls cannot race past
    # the ceiling. Fail closed if the store is unreachable.
    op = _op_of(x_op)
    key = _meter_key(user, op)
    cap = DAILY_AUX_PER_USER if op == "aux" else DAILY_PER_USER
    try:
        with _lock:
            mine, total = _counts(key)
            if total >= DAILY_GLOBAL:
                raise HTTPException(
                    429,
                    "PixieDuster has hit its daily limit for everyone. Try tomorrow, "
                    "or use your own key: pixieduster clone --api-key ...",
                )
            if mine >= cap:
                what = "test messages" if op == "aux" else "personas"
                raise HTTPException(
                    429,
                    f"You have used all {cap} {what} for today "
                    f"(resets {_resets_at()}). Use your own key to keep going: "
                    "pixieduster clone --api-key ...",
                )
            _charge(key)
    except sqlite3.Error:
        raise HTTPException(503, "Quota store unavailable, so nothing was sent.")

    try:
        upstream = requests.post(
            f"{GEMINI_BASE}/models/{model}:{method}",
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
            data=body,
            timeout=UPSTREAM_TIMEOUT,
        )
    except requests.RequestException:
        _refund(key)
        raise HTTPException(502, "Could not reach Gemini. Nothing was charged.")

    if upstream.status_code >= 500:
        _refund(key)

    try:
        payload = upstream.json()
    except ValueError:
        _refund(key)
        raise HTTPException(502, "Gemini returned a response that was not JSON.")

    # Never let an upstream error echo anything about our key.
    if upstream.status_code >= 400:
        detail = "The model refused that request."
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            detail = error["message"].replace(GEMINI_API_KEY, "<redacted>")
        return JSONResponse({"error": {"message": detail}}, status_code=upstream.status_code)

    return JSONResponse(payload, status_code=200)


# --------------------------------------------------------------------------
# the web app
# --------------------------------------------------------------------------
# Mounted at the very end so every /api route above is matched first. This is
# the original stlite app, byte-for-byte -- it runs app.py in the visitor's
# browser via Pyodide and is unrelated to the proxy above.

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="web")
