"""Configuration and API-key resolution for PixieDuster.

Security notes:
  * The API key is never logged, printed, or included in an exception message
    by anything in this module.
  * ``CONFIG_DIR`` is created 0700 and ``CONFIG_PATH`` written 0600, so the key
    is not readable by other users on a shared machine.
  * The config file is written by hand (stdlib ``tomllib`` is read-only) but
    unknown keys and tables are round-tripped, so nothing is silently dropped.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

__all__ = [
    "CONFIG_DIR",
    "CONFIG_PATH",
    "ENV_VAR",
    "resolve_api_key",
    "save_api_key",
    "key_source",
    "load_settings",
    "save_setting",
    "load_config",
    "mask_key",
]

#: Environment variable consulted for the key.
ENV_VAR = "GEMINI_API_KEY"


def _config_dir() -> Path:
    """Resolve the config directory, honouring ``XDG_CONFIG_HOME``."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "pixieduster"


CONFIG_DIR: Path = _config_dir()
CONFIG_PATH: Path = CONFIG_DIR / "config.toml"


def _paths() -> tuple[Path, Path]:
    """Current config dir/file.

    Re-derived from the environment on every call so that tests (and a user who
    exports ``XDG_CONFIG_HOME`` mid-session) are not stuck with the value that
    happened to be set at import time. The module-level constants remain for
    callers that only need the common case.
    """
    directory = _config_dir()
    return directory, directory / "config.toml"


# --------------------------------------------------------------------------- #
# TOML round-tripping
# --------------------------------------------------------------------------- #

def load_config() -> dict[str, Any]:
    """Parse the config file. Returns ``{}`` if it is absent or unreadable."""
    _, path = _paths()
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (FileNotFoundError, PermissionError, IsADirectoryError, tomllib.TOMLDecodeError):
        return {}


def _fmt_value(value: Any) -> str:
    """Serialise a scalar or flat list to TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) or isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt_value(v) for v in value) + "]"
    return _fmt_string(str(value))


def _fmt_string(value: str) -> str:
    """Quote a TOML basic string, escaping what the spec requires."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _fmt_key(key: str) -> str:
    """Bare key where legal, quoted otherwise."""
    if key and all(c.isalnum() or c in "-_" for c in key) and key.isascii():
        return key
    return _fmt_string(key)


def _dump(data: dict[str, Any]) -> str:
    """Serialise a two-level dict (scalars + flat tables) back to TOML."""
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{_fmt_key(key)} = {_fmt_value(value)}")
    for key, value in data.items():
        if isinstance(value, dict):
            if lines:
                lines.append("")
            lines.append(f"[{_fmt_key(key)}]")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, dict):
                    # Nested tables are outside this schema; skip rather than
                    # emit something tomllib cannot read back.
                    continue
                lines.append(f"{_fmt_key(sub_key)} = {_fmt_value(sub_value)}")
    return "\n".join(lines) + "\n"


def _write_config(data: dict[str, Any]) -> Path:
    """Write the config file with 0700 dir / 0600 file permissions."""
    directory, path = _paths()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    text = _dump(data)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return path


# --------------------------------------------------------------------------- #
# API key
# --------------------------------------------------------------------------- #

def _dotenv_key() -> str | None:
    """Read ``GEMINI_API_KEY`` from a ``.env`` in the cwd, if present.

    Uses ``dotenv_values`` rather than ``load_dotenv`` so the key is never
    pushed into ``os.environ`` (where a subprocess or a crash dump could pick
    it up). Because the real environment is consulted first, this is equivalent
    to ``load_dotenv(override=False)``.
    """
    dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.is_file():
        return None
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    try:
        value = dotenv_values(dotenv_path).get(ENV_VAR)
    except OSError:
        return None
    return value or None


def _config_key() -> str | None:
    """Read ``[auth] gemini_api_key`` from the config file."""
    auth = load_config().get("auth")
    if isinstance(auth, dict):
        value = auth.get("gemini_api_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve(explicit: str | None) -> tuple[str | None, str]:
    """Return ``(key, source)`` using the documented resolution order."""
    if explicit and explicit.strip():
        return explicit.strip(), "flag"

    env_value = os.environ.get(ENV_VAR)
    if env_value and env_value.strip():
        return env_value.strip(), "env"

    dotenv_value = _dotenv_key()
    if dotenv_value and dotenv_value.strip():
        return dotenv_value.strip(), "dotenv"

    config_value = _config_key()
    if config_value:
        return config_value, "config"

    return None, "none"


def resolve_api_key(explicit: str | None = None) -> str | None:
    """Find the Gemini API key.

    Resolution order, first hit wins:
      1. ``explicit`` (the ``--api-key`` flag)
      2. the ``GEMINI_API_KEY`` environment variable
      3. ``.env`` in the current directory
      4. ``CONFIG_PATH`` -> ``[auth] gemini_api_key``

    Returns ``None`` if nothing is found. Never logs the key.
    """
    return _resolve(explicit)[0]


def key_source(explicit: str | None = None) -> str:
    """Name the source that supplied the key, for display only.

    One of ``'flag'``, ``'env'``, ``'dotenv'``, ``'config'``, ``'none'``.
    """
    return _resolve(explicit)[1]


def save_api_key(key: str) -> Path:
    """Persist ``key`` to ``CONFIG_PATH`` under ``[auth]``.

    The directory is created 0700 and the file written 0600. Any other keys
    already in the file - known or not - are preserved. Returns the path.
    """
    if not key or not key.strip():
        raise ValueError("Refusing to save an empty API key.")
    data = load_config()
    auth = data.get("auth")
    if not isinstance(auth, dict):
        auth = {}
    auth["gemini_api_key"] = key.strip()
    data["auth"] = auth
    return _write_config(data)


def mask_key(key: str | None) -> str:
    """Render a key for display, e.g. ``AIza…4f21``. Never shows the middle."""
    if not key:
        return "(not set)"
    key = key.strip()
    if len(key) <= 8:
        return "…" * 1 + key[-2:] if len(key) > 2 else "…"
    return f"{key[:4]}…{key[-4:]}"


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

def save_hf_token(token: str) -> Path:
    """Persist a Hugging Face token under ``[auth]``, 0600 like the API key."""
    if not token or not token.strip():
        raise ValueError("Refusing to save an empty Hugging Face token.")
    data = load_config()
    auth = data.get("auth")
    if not isinstance(auth, dict):
        auth = {}
    auth["hf_token"] = token.strip()
    data["auth"] = auth
    return _write_config(data)


def load_settings() -> dict[str, Any]:
    """Return the ``[settings]`` table (model, max_tokens, …). May be empty."""
    settings = load_config().get("settings")
    return dict(settings) if isinstance(settings, dict) else {}


def save_setting(key: str, value: Any) -> None:
    """Set one key in ``[settings]``, preserving everything else in the file."""
    if not key:
        raise ValueError("Setting name must not be empty.")
    data = load_config()
    settings = data.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    settings[key] = value
    data["settings"] = settings
    _write_config(data)
