"""Offline tests for pixieduster.config. No network, no real key."""

from __future__ import annotations

import os
import stat

import pytest

from pixieduster import config

KEY = "AIza" + "SyD-FAKE-KEY-FOR-TESTS-0123456789"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Isolate CONFIG_DIR, cwd, and GEMINI_API_KEY for one test."""
    cfg_home = tmp_path / "xdg"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.chdir(work)
    return work


# --------------------------------------------------------------------------- #
# Paths and permissions
# --------------------------------------------------------------------------- #

def test_config_path_follows_xdg(sandbox, tmp_path):
    path = config.save_api_key(KEY)
    assert path == tmp_path / "xdg" / "pixieduster" / "config.toml"


def test_save_api_key_permissions_are_private(sandbox):
    path = config.save_api_key(KEY)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


def test_saved_key_round_trips(sandbox):
    config.save_api_key(KEY)
    assert config.resolve_api_key() == KEY
    assert config.key_source() == "config"


def test_save_api_key_rejects_empty(sandbox):
    with pytest.raises(ValueError):
        config.save_api_key("   ")


def test_no_temp_file_is_left_behind(sandbox):
    path = config.save_api_key(KEY)
    assert not list(path.parent.glob("*.tmp"))


# --------------------------------------------------------------------------- #
# Round-tripping unknown content
# --------------------------------------------------------------------------- #

def test_unknown_keys_are_preserved(sandbox):
    cfg_file = config.save_api_key("first")
    cfg_file.write_text(
        cfg_file.read_text()
        + '\n[future]\nsomething = "keep me"\ncount = 3\nflag = true\nlist = ["a", "b"]\n',
        encoding="utf-8",
    )
    config.save_api_key(KEY)
    data = config.load_config()
    assert data["auth"]["gemini_api_key"] == KEY
    assert data["future"] == {
        "something": "keep me",
        "count": 3,
        "flag": True,
        "list": ["a", "b"],
    }


def test_settings_and_auth_coexist(sandbox):
    config.save_api_key(KEY)
    config.save_setting("model", "gemini-3.6-flash")
    config.save_setting("max_tokens", 4096)
    assert config.load_settings() == {"model": "gemini-3.6-flash", "max_tokens": 4096}
    assert config.resolve_api_key() == KEY


def test_load_settings_empty_when_no_file(sandbox):
    assert config.load_settings() == {}
    assert config.load_config() == {}


def test_save_setting_rejects_empty_name(sandbox):
    with pytest.raises(ValueError):
        config.save_setting("", 1)


def test_corrupt_config_does_not_explode(sandbox, tmp_path):
    directory = tmp_path / "xdg" / "pixieduster"
    directory.mkdir(parents=True)
    (directory / "config.toml").write_text("this is not [valid toml", encoding="utf-8")
    assert config.load_config() == {}
    assert config.resolve_api_key() is None
    assert config.key_source() == "none"


def test_strings_with_quotes_round_trip(sandbox):
    config.save_setting("note", 'he said "hi" \\ then left')
    assert config.load_settings()["note"] == 'he said "hi" \\ then left'


# --------------------------------------------------------------------------- #
# Resolution order
# --------------------------------------------------------------------------- #

def test_nothing_found(sandbox):
    assert config.resolve_api_key() is None
    assert config.key_source() == "none"


def test_explicit_flag_wins(sandbox, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    config.save_api_key("from-config")
    assert config.resolve_api_key("from-flag") == "from-flag"
    assert config.key_source("from-flag") == "flag"


def test_env_beats_dotenv_and_config(sandbox, monkeypatch):
    (sandbox / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    config.save_api_key("from-config")
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert config.resolve_api_key() == "from-env"
    assert config.key_source() == "env"


def test_dotenv_beats_config(sandbox):
    (sandbox / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    config.save_api_key("from-config")
    assert config.resolve_api_key() == "from-dotenv"
    assert config.key_source() == "dotenv"


def test_dotenv_is_not_leaked_into_environ(sandbox):
    (sandbox / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
    config.resolve_api_key()
    assert "GEMINI_API_KEY" not in os.environ


def test_blank_env_falls_through(sandbox, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    config.save_api_key("from-config")
    assert config.resolve_api_key() == "from-config"
    assert config.key_source() == "config"


def test_whitespace_is_trimmed(sandbox):
    config.save_api_key(f"  {KEY}  ")
    assert config.resolve_api_key() == KEY


# --------------------------------------------------------------------------- #
# Display
# --------------------------------------------------------------------------- #

def test_mask_key_hides_the_middle():
    masked = config.mask_key(KEY)
    assert masked.startswith("AIza")
    assert masked.endswith(KEY[-4:])
    assert KEY not in masked
    assert "…" in masked


def test_mask_key_handles_none_and_short():
    assert config.mask_key(None) == "(not set)"
    assert KEY not in config.mask_key("abc")
