"""The persona has to be able to say "I don't know".

Four short samples used to produce the same confident output as forty. A reader
could not tell a claim resting on one sentence from one seen throughout. These
cover the signalling that fixes that: every claim carries a confidence marker,
the model is told how much evidence it actually had, and it must name what the
writing does not cover.
"""

from __future__ import annotations

from unittest.mock import patch

from pixieduster import core, prompts
from pixieduster.types import Sample

KEY = "AIza" + "TESTKEYTESTKEYTESTKEYTESTKEYTEST123"


def _reply(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _sent(mock) -> str:
    payload = mock.call_args.kwargs["json"]
    return "\n".join(p["text"] for p in payload["contents"][0]["parts"] if "text" in p)


def _ok(post) -> None:
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("persona")
    post.return_value.raise_for_status.return_value = None


def _samples(n: int, words: int) -> list[Sample]:
    body = " ".join(["word"] * words)
    return [Sample("file", f"note{i}.txt", body) for i in range(n)]


@patch("pixieduster.core.requests.post")
def test_the_model_is_told_how_much_evidence_it_had(post):
    _ok(post)
    core.generate_persona(KEY, "m", "A", _samples(3, 40), [])
    prompt = _sent(post)
    assert "EVIDENCE AVAILABLE" in prompt
    assert "3 text sample(s)" in prompt
    assert "120 words" in prompt


@patch("pixieduster.core.requests.post")
def test_thin_evidence_is_called_thin(post):
    """Under 400 words, the model is told outright to expect provisional claims."""
    _ok(post)
    core.generate_persona(KEY, "m", "A", _samples(2, 30), [])
    assert "That is very little" in _sent(post)


@patch("pixieduster.core.requests.post")
def test_ample_evidence_is_not_called_thin(post):
    _ok(post)
    core.generate_persona(KEY, "m", "A", _samples(6, 200), [])
    prompt = _sent(post)
    assert "That is very little" not in prompt
    assert "1,200 words" in prompt


@patch("pixieduster.core.requests.post")
def test_images_are_counted_as_evidence_the_model_must_read(post):
    _ok(post)
    core.generate_persona(
        KEY, "m", "A", _samples(1, 50), [],
        files=[("scan.png", "image/png", b"x")],
    )
    assert "1 image(s) or document(s)" in _sent(post)


@patch("pixieduster.core.requests.post")
def test_no_samples_at_all_is_stated_plainly(post):
    _ok(post)
    core.generate_persona(KEY, "m", "A", [], [], description="a calm librarian")
    # The invent path does not claim evidence it never had.
    assert "EVIDENCE AVAILABLE" not in _sent(post)


def test_every_confidence_marker_is_defined():
    for marker in ("[clear]", "[likely]", "[provisional]"):
        assert marker in prompts.CONFIDENCE_INSTRUCTION


def test_markers_are_scoped_to_claims_not_to_gaps():
    """A confidence marker on something you do not know is meaningless."""
    assert "Never put a marker on an item in the" in prompts.CONFIDENCE_INSTRUCTION


def test_the_rubric_demands_a_gaps_section():
    text = prompts.PERSONA_RUBRIC
    assert "CONFIDENCE AND GAPS" in text
    assert "could NOT determine" in text
    assert "would settle those gaps" in text


def test_a_voiceless_corpus_may_be_reported_as_voiceless():
    """Manufacturing a voice out of bland writing is the failure to avoid."""
    assert "no distinctive voice" in prompts.CONFIDENCE_INSTRUCTION


def test_the_rubric_demands_scored_traits_and_negative_space():
    assert "score out of 5" in prompts.PERSONA_RUBRIC
    assert "Never write the five as a single paragraph" in prompts.PERSONA_RUBRIC
    assert "NEVER list" in prompts.PERSONA_RUBRIC


def test_an_invented_persona_separates_implied_from_invented():
    """Its creator should see what they specified and what was decided for them."""
    assert "[implied]" in prompts.INVENT_RUBRIC
    assert "[invented]" in prompts.INVENT_RUBRIC
    assert "WHAT I DECIDED FOR YOU" in prompts.INVENT_RUBRIC
