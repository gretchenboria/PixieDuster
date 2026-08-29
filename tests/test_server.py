"""The metered proxy. These are the tests that protect the bill.

Everything runs offline: Hugging Face identity and the Gemini upstream are both
stubbed. What is being checked is the metering logic, not the network.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A fresh app with its own quota database and small limits."""
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "FAKEKEYFORTESTSONLYFAKEKEYFORTESTS")
    monkeypatch.setenv("QUOTA_DB", str(tmp_path / "quota.db"))
    monkeypatch.setenv("DAILY_PER_USER", "2")
    monkeypatch.setenv("DAILY_GLOBAL", "3")
    monkeypatch.setenv("ALLOWED_MODELS", "gemini-3.6-flash")
    monkeypatch.syspath_prepend(str(SERVER_DIR))
    sys.modules.pop("app", None)
    module = importlib.import_module("app")

    calls: list[dict] = []

    class FakeUpstream:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def fake_post(url, headers=None, data=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}})
        return FakeUpstream()

    def fake_get(url, headers=None, timeout=None):
        token = (headers or {}).get("Authorization", "").removeprefix("Bearer ")

        class R:
            status_code = 401 if token in {"", "bad"} else 200

            @staticmethod
            def json():
                return {"name": token}

        return R()

    monkeypatch.setattr(module.requests, "post", fake_post)
    monkeypatch.setattr(module.requests, "get", fake_get)
    module._identity_cache.clear()

    client = TestClient(module.app)
    client.upstream_calls = calls
    client.module = module
    return client


def _gen(client, who="alice", model="gemini-3.6-flash", op=None):
    headers = {"Authorization": f"Bearer {who}"}
    if op:
        headers["X-Op"] = op
    return client.post(
        f"/api/models/{model}:generateContent",
        headers=headers,
        json={"contents": [{"parts": [{"text": "hi"}]}]},
    )


# --- identity --------------------------------------------------------------

def test_no_token_is_rejected(server):
    assert server.post("/api/models/gemini-3.6-flash:generateContent", json={}).status_code == 401


def test_bad_token_is_rejected(server):
    assert _gen(server, "bad").status_code == 401


def test_me_reports_quota(server):
    body = server.get("/api/me", headers={"Authorization": "Bearer alice"}).json()
    assert body["user"] == "alice"
    assert body["limit"] == 2 and body["remaining"] == 2


# --- metering: the part that protects the bill -----------------------------

def test_per_user_limit_is_enforced(server):
    assert _gen(server, "alice").status_code == 200
    assert _gen(server, "alice").status_code == 200
    blocked = _gen(server, "alice")
    assert blocked.status_code == 429
    assert "own key" in blocked.json()["detail"]


def test_testing_a_persona_does_not_spend_the_persona_allowance(server):
    """The bug this guards: one persona costs two calls (interview + generate),
    which used to leave a 2-per-day visitor blocked on their first chat turn."""
    assert _gen(server, "alice", op="interview").status_code == 200
    assert _gen(server, "alice").status_code == 200
    assert _gen(server, "alice", op="chat").status_code == 200

    body = server.get("/api/me", headers={"Authorization": "Bearer alice"}).json()
    assert body["used"] == 1 and body["remaining"] == 1
    assert body["aux_used"] == 2


def test_aux_calls_have_their_own_ceiling(server):
    server.module.DAILY_AUX_PER_USER = 1
    assert _gen(server, "alice", op="chat").status_code == 200
    blocked = _gen(server, "alice", op="chat")
    assert blocked.status_code == 429
    assert "test messages" in blocked.json()["detail"]
    # The persona allowance is untouched by a chat that ran out.
    assert _gen(server, "alice").status_code == 200


def test_an_unknown_op_is_billed_as_a_persona(server):
    """The CLI sends no X-Op, so the default must be the conservative one."""
    assert _gen(server, "alice", op="nonsense").status_code == 200
    body = server.get("/api/me", headers={"Authorization": "Bearer alice"}).json()
    assert body["used"] == 1


def test_chat_cannot_starve_persona_generation(server):
    """The aux ceiling is what keeps chat traffic from eating the whole day."""
    server.module.DAILY_AUX_GLOBAL = 2
    assert _gen(server, "alice", op="chat").status_code == 200
    assert _gen(server, "bob", op="chat").status_code == 200

    blocked = _gen(server, "carol", op="chat")
    assert blocked.status_code == 429
    assert "chat has hit its shared daily limit" in blocked.json()["detail"]

    # Personas are unaffected by a chat ceiling that has been reached.
    assert _gen(server, "carol").status_code == 200


def test_persona_calls_do_not_count_against_the_chat_ceiling(server):
    server.module.DAILY_AUX_GLOBAL = 1
    assert _gen(server, "alice").status_code == 200
    assert _gen(server, "bob").status_code == 200
    # Two personas spent, but the chat ceiling still has its full room.
    assert _gen(server, "carol", op="chat").status_code == 200


def test_one_user_cannot_exhaust_another(server):
    _gen(server, "alice")
    _gen(server, "alice")
    assert _gen(server, "alice").status_code == 429
    assert _gen(server, "bob").status_code == 200


def test_global_ceiling_stops_everyone(server):
    _gen(server, "alice")
    _gen(server, "alice")
    _gen(server, "bob")          # third call, hits DAILY_GLOBAL=3
    blocked = _gen(server, "carol")
    assert blocked.status_code == 429
    assert "everyone" in blocked.json()["detail"]


def test_quota_is_charged_before_the_upstream_call(server):
    """A refused request must never reach Gemini."""
    _gen(server, "alice")
    _gen(server, "alice")
    before = len(server.upstream_calls)
    _gen(server, "alice")
    assert len(server.upstream_calls) == before


def test_upstream_failure_refunds_the_charge(server):
    def boom(url, headers=None, data=None, timeout=None):
        raise server.module.requests.RequestException("network down")

    server.module.requests.post = boom
    assert _gen(server, "alice").status_code == 502
    body = server.get("/api/me", headers={"Authorization": "Bearer alice"}).json()
    assert body["used"] == 0, "a failed call must not consume quota"


# --- guardrails ------------------------------------------------------------

def test_unlisted_model_is_refused(server):
    r = _gen(server, "alice", model="gemini-2.5-pro")
    assert r.status_code == 400
    assert "not available" in r.json()["detail"]


def test_oversized_body_is_refused(server):
    r = server.post(
        "/api/models/gemini-3.6-flash:generateContent",
        headers={"Authorization": "Bearer alice"},
        json={"contents": [{"parts": [{"text": "x" * (7 * 1024 * 1024)}]}]},
    )
    assert r.status_code == 413


def test_unknown_method_is_refused(server):
    r = server.post(
        "/api/models/gemini-3.6-flash:deleteEverything",
        headers={"Authorization": "Bearer alice"},
        json={},
    )
    assert r.status_code == 404


# --- the key must never escape ---------------------------------------------

def test_the_gemini_key_is_never_returned_to_a_caller(server):
    key = server.module.GEMINI_API_KEY

    class Failing:
        status_code = 400

        @staticmethod
        def json():
            return {"error": {"message": f"Bad key {key} supplied at ?key={key}"}}

    server.module.requests.post = lambda *a, **k: Failing()
    body = _gen(server, "alice").text
    assert key not in body
    assert "<redacted>" in body


def test_the_caller_never_sees_the_key_in_a_healthy_response(server):
    body = _gen(server, "alice").text
    assert server.module.GEMINI_API_KEY not in body


def test_upstream_receives_the_server_key_not_the_caller_token(server):
    _gen(server, "alice")
    sent = server.upstream_calls[-1]["headers"]
    assert sent["x-goog-api-key"] == server.module.GEMINI_API_KEY
    assert "alice" not in str(sent)


def test_health_does_not_leak_the_key(server):
    body = server.get("/api/health").text
    assert server.module.GEMINI_API_KEY not in body
    assert '"configured":true' in body.replace(" ", "")
