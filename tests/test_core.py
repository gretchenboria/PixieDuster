"""Offline tests for pixieduster.core. requests is always mocked."""

from __future__ import annotations

import base64
import json

import pytest
import requests

from pixieduster import core
from pixieduster.types import Question, Sample

FAKE_KEY = "AIza" + "SyD-FAKE-KEY-FOR-TESTS-0123456789"


class FakeResponse:
    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is _NOT_JSON:
            raise ValueError("no json")
        return self._payload


_NOT_JSON = object()


def text_reply(text: str) -> FakeResponse:
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]}}]})


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing POST and return a canned reply."""
    box: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        box["url"] = url
        box["headers"] = headers or {}
        box["payload"] = json
        box["timeout"] = timeout
        return box.get("response") or text_reply("ok")

    monkeypatch.setattr(requests, "post", fake_post)
    return box


# --------------------------------------------------------------------------- #
# call_gemini
# --------------------------------------------------------------------------- #

def test_default_model_matches_app():
    assert core.DEFAULT_MODEL == "gemini-3.6-flash"


def test_call_gemini_sends_prompt_and_key_in_header_not_url(captured):
    out = core.call_gemini(FAKE_KEY, "gemini-3.6-flash", "hello")
    assert out == "ok"
    assert captured["url"].endswith("/models/gemini-3.6-flash:generateContent")
    assert FAKE_KEY not in captured["url"]
    assert "key=" not in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == FAKE_KEY
    assert captured["payload"]["contents"][0]["parts"][0]["text"] == "hello"


def test_model_prefix_is_normalised(captured):
    core.call_gemini(FAKE_KEY, "models/gemini-3.6-flash", "hi")
    assert captured["url"].endswith("/models/gemini-3.6-flash:generateContent")


def test_schema_sets_json_response_config(captured):
    core.call_gemini(FAKE_KEY, "m", "p", schema={"type": "ARRAY"})
    cfg = captured["payload"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == {"type": "ARRAY"}


def test_no_generation_config_without_schema(captured):
    core.call_gemini(FAKE_KEY, "m", "p")
    assert "generationConfig" not in captured["payload"]


def test_text_files_are_inlined_as_text(captured):
    core.call_gemini(
        FAKE_KEY, "m", "p", files=[("notes.txt", "text/plain", b"dear diary")]
    )
    parts = captured["payload"]["contents"][0]["parts"]
    assert "dear diary" in parts[1]["text"]
    assert "notes.txt" in parts[1]["text"]


def test_binary_files_are_base64_inline_data(captured):
    core.call_gemini(FAKE_KEY, "m", "p", files=[("s.png", "image/png", b"\x89PNG")])
    part = captured["payload"]["contents"][0]["parts"][1]
    assert part["inlineData"]["mimeType"] == "image/png"
    assert base64.b64decode(part["inlineData"]["data"]) == b"\x89PNG"


def test_inline_texts_are_appended(captured):
    core.call_gemini(FAKE_KEY, "m", "p", inline_texts=[("README.md", "body text")])
    parts = captured["payload"]["contents"][0]["parts"]
    assert "README.md" in parts[1]["text"]
    assert "body text" in parts[1]["text"]


def test_multiple_text_parts_are_joined(captured):
    captured["response"] = FakeResponse(
        {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    )
    assert core.call_gemini(FAKE_KEY, "m", "p") == "ab"


def test_empty_candidates_raise(captured):
    captured["response"] = FakeResponse({"candidates": []})
    with pytest.raises(core.GeminiError):
        core.call_gemini(FAKE_KEY, "m", "p")


def test_blocked_prompt_raises(captured):
    captured["response"] = FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(core.GeminiError, match="SAFETY"):
        core.call_gemini(FAKE_KEY, "m", "p")


def test_missing_key_raises_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(core.GeminiError):
        core.call_gemini("", "m", "p")


def test_transport_failure_becomes_gemini_error(monkeypatch):
    def fake_post(*a, **k):
        raise requests.ConnectionError("name resolution failed")

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(core.GeminiError, match="Could not reach"):
        core.call_gemini(FAKE_KEY, "m", "p")


# --------------------------------------------------------------------------- #
# Key hygiene — the security contract
# --------------------------------------------------------------------------- #

def test_api_error_message_never_contains_the_key(captured):
    leaky = (
        f"API key not valid. Request URL: "
        f"https://generativelanguage.googleapis.com/v1beta/models/m:generateContent?key={FAKE_KEY}"
    )
    captured["response"] = FakeResponse(
        {"error": {"message": leaky, "status": "INVALID_ARGUMENT"}}, status_code=400
    )
    with pytest.raises(core.GeminiError) as excinfo:
        core.call_gemini(FAKE_KEY, "m", "p")
    rendered = str(excinfo.value)
    assert FAKE_KEY not in rendered
    assert "AIza" not in rendered
    assert "REDACTED" in rendered
    assert "API key not valid" in rendered  # the API's own wording survives


def test_gemini_error_strips_key_query_param_even_for_unknown_keys():
    exc = core.GeminiError("failed at https://example.com/v1beta/models?key=sekrit123&alt=json")
    assert "sekrit123" not in str(exc)
    assert "alt=json" in str(exc)


def test_gemini_error_scrubs_raw_key_passed_through():
    exc = core.GeminiError(f"boom {FAKE_KEY} boom", FAKE_KEY)
    assert FAKE_KEY not in str(exc)


def test_repr_and_args_are_also_safe(captured):
    exc = core.GeminiError(f"leak {FAKE_KEY}", FAKE_KEY)
    assert FAKE_KEY not in repr(exc)
    assert FAKE_KEY not in "".join(str(a) for a in exc.args)


def test_non_json_error_body_is_handled(captured):
    captured["response"] = FakeResponse(_NOT_JSON, status_code=500, text="upstream boom")
    with pytest.raises(core.GeminiError, match="upstream boom"):
        core.call_gemini(FAKE_KEY, "m", "p")


# --------------------------------------------------------------------------- #
# chat_gemini
# --------------------------------------------------------------------------- #

def test_chat_maps_roles_and_system_prompt(captured):
    captured["response"] = text_reply("hey")
    out = core.chat_gemini(
        FAKE_KEY,
        "m",
        "you are a persona",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}],
        "how are you",
    )
    assert out == "hey"
    payload = captured["payload"]
    assert payload["systemInstruction"]["parts"][0]["text"] == "you are a persona"
    roles = [c["role"] for c in payload["contents"]]
    assert roles == ["user", "model", "user"]
    assert payload["contents"][-1]["parts"][0]["text"] == "how are you"


def test_chat_with_empty_history(captured):
    captured["response"] = text_reply("hey")
    core.chat_gemini(FAKE_KEY, "m", "sys", [], "first")
    assert len(captured["payload"]["contents"]) == 1


# --------------------------------------------------------------------------- #
# list_models
# --------------------------------------------------------------------------- #

def test_list_models_strips_prefix(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        assert "key=" not in url
        assert headers["x-goog-api-key"] == FAKE_KEY
        return FakeResponse(
            {"models": [{"name": "models/gemini-2.5-flash"}, {"name": "models/gemini-pro"}]}
        )

    monkeypatch.setattr(requests, "get", fake_get)
    assert core.list_models(FAKE_KEY) == ["gemini-2.5-flash", "gemini-pro"]


def test_list_models_follows_pagination(monkeypatch):
    pages = [
        {"models": [{"name": "models/a"}], "nextPageToken": "t2"},
        {"models": [{"name": "models/b"}]},
    ]
    calls: list = []

    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        calls.append(params)
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr(requests, "get", fake_get)
    assert core.list_models(FAKE_KEY) == ["a", "b"]
    assert calls[1]["pageToken"] == "t2"


def test_list_models_error_is_scrubbed(monkeypatch):
    def fake_get(*a, **k):
        return FakeResponse(
            {"error": {"message": f"bad key ?key={FAKE_KEY}"}}, status_code=403
        )

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(core.GeminiError) as excinfo:
        core.list_models(FAKE_KEY)
    assert FAKE_KEY not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# generate_questions
# --------------------------------------------------------------------------- #

SAMPLES = [Sample(kind="commit", origin="git log abc123", text="fixed the thing")]

BARE_ARRAY = '[{"question": "Q1?", "options": ["a", "b"]}]'
WRAPPED = '{"questions": [{"question": "Q1?", "options": ["a", "b"]}]}'


@pytest.mark.parametrize(
    "body",
    [
        BARE_ARRAY,
        WRAPPED,
        f"```json\n{BARE_ARRAY}\n```",
        f"```json\n{WRAPPED}\n```",
        f"```\n{BARE_ARRAY}\n```",
        f"   {WRAPPED}   ",
    ],
)
def test_generate_questions_tolerates_every_shape(captured, body):
    captured["response"] = text_reply(body)
    questions = core.generate_questions(FAKE_KEY, "m", "Gretchen", SAMPLES)
    assert questions == [Question(question="Q1?", options=["a", "b"])]


def test_generate_questions_accepts_lone_object(captured):
    captured["response"] = text_reply('{"question": "solo?", "options": ["x"]}')
    assert core.generate_questions(FAKE_KEY, "m", "G", SAMPLES)[0].question == "solo?"


def test_generate_questions_sends_schema_and_samples(captured):
    captured["response"] = text_reply(BARE_ARRAY)
    core.generate_questions(FAKE_KEY, "m", "Gretchen", SAMPLES, n=5)
    payload = captured["payload"]
    assert payload["generationConfig"]["responseSchema"]["type"] == "ARRAY"
    prompt = payload["contents"][0]["parts"][0]["text"]
    assert "Gretchen" in prompt
    assert "5 highly specific multiple-choice questions" in prompt
    assert "{" in prompt and '"questions"' in prompt  # literal schema example survives
    assert "fixed the thing" in payload["contents"][0]["parts"][1]["text"]


def test_generate_questions_truncates_to_n(captured):
    many = json.dumps(
        [{"question": f"Q{i}", "options": ["a", "b"]} for i in range(6)]
    )
    captured["response"] = text_reply(many)
    assert len(core.generate_questions(FAKE_KEY, "m", "G", SAMPLES, n=3)) == 3


def test_generate_questions_drops_malformed_entries(captured):
    captured["response"] = text_reply(
        '[{"question": "ok?", "options": ["a"]}, {"question": "", "options": []}, "junk"]'
    )
    assert len(core.generate_questions(FAKE_KEY, "m", "G", SAMPLES)) == 1


def test_generate_questions_malformed_json_suggests_retry(captured):
    captured["response"] = text_reply('[{"question": "unescaped " quote"}]')
    with pytest.raises(core.GeminiError, match="retry"):
        core.generate_questions(FAKE_KEY, "m", "G", SAMPLES)


def test_generate_questions_empty_result_suggests_retry(captured):
    captured["response"] = text_reply("[]")
    with pytest.raises(core.GeminiError, match="retry"):
        core.generate_questions(FAKE_KEY, "m", "G", SAMPLES)


def test_generate_questions_error_has_no_key(captured):
    captured["response"] = text_reply("not json at all")
    with pytest.raises(core.GeminiError) as excinfo:
        core.generate_questions(FAKE_KEY, "m", "G", SAMPLES)
    assert FAKE_KEY not in str(excinfo.value)


# --------------------------------------------------------------------------- #
# generate_persona
# --------------------------------------------------------------------------- #

def test_generate_persona_wraps_in_anti_ai_template(captured):
    captured["response"] = text_reply("She writes in short bursts.")
    doc = core.generate_persona(
        FAKE_KEY, "m", "Gretchen", SAMPLES, [("Q1?", "a")]
    )
    assert doc.startswith("# AI Persona & Style Guide")
    assert "She writes in short bursts." in doc
    assert "{extracted_persona}" not in doc
    assert "delve" in doc  # the vocabulary ban list is intact


def test_generate_persona_prompt_carries_the_rubric(captured):
    captured["response"] = text_reply("persona")
    core.generate_persona(
        FAKE_KEY, "m", "Gretchen", SAMPLES, [("Q1?", "option a")]
    )
    prompt = captured["payload"]["contents"][0]["parts"][0]["text"]
    assert "Q: Q1?\nA: option a" in prompt
    # Humor is a fifth dimension of the rubric now, worked out from the
    # evidence rather than dialled in by the caller.
    assert "Benign Violation Theory" in prompt
    assert "Work out from the evidence" in prompt
    assert "Benign Violation Theory" in prompt
    assert "LIWC Lexical/Syntactic Fingerprint" in prompt
    assert "Big Five (OCEAN)" in prompt
    assert "Cognitive Style & Epistemic Stance" in prompt
    assert "Sociolinguistics" in prompt


def test_generate_persona_braces_in_output_survive(captured):
    captured["response"] = text_reply("uses {curly} braces a lot")
    doc = core.generate_persona(FAKE_KEY, "m", "G", SAMPLES, [])
    assert "uses {curly} braces a lot" in doc
