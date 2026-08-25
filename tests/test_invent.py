"""Inventing a persona from a description, with no writing samples at all.

The point of the product is being true to an identity. That identity can be a
real person reconstructed from their prose, or a character described in a
sentence: "a friendly desktop robot with great humor". These cover the second
case, which has no samples to reason from.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pixieduster import core, prompts
from pixieduster.types import Sample

ROBOT = "a friendly desktop robot with great humor"
KEY = "AIzaTESTKEYTESTKEYTESTKEYTESTKEYTEST123"


def _reply(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _sent(mock) -> str:
    """The prompt text actually put on the wire."""
    payload = mock.call_args.kwargs["json"]
    return "\n".join(
        part["text"] for part in payload["contents"][0]["parts"] if "text" in part
    )


@patch("pixieduster.core.requests.post")
def test_persona_is_designed_when_there_are_no_samples(post):
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("A cheerful machine.")
    post.return_value.raise_for_status.return_value = None

    out = core.generate_persona(KEY, "m", "Bolt", [], [], description=ROBOT)

    prompt = _sent(post)
    assert "PERSONA DESIGN RUBRIC" in prompt
    assert ROBOT in prompt
    assert "Bolt" in prompt
    # The extraction rubric is for reverse-engineering a real author.
    assert "Here are the original writing samples" not in prompt
    assert "A cheerful machine." in out


@patch("pixieduster.core.requests.post")
def test_humor_is_derived_not_dialled(post):
    """Humor is a finding of the analysis, not a setting handed to it."""
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("x")
    post.return_value.raise_for_status.return_value = None

    core.generate_persona(KEY, "m", "Bolt", [], [], description=ROBOT)
    prompt = _sent(post)
    assert "Benign Violation Theory" in prompt
    # The model is told to work it out, not told what the answer is.
    assert "Work out from the evidence" in prompt
    assert "out of 10" not in prompt
    assert "humor level" not in prompt.lower()


@patch("pixieduster.core.requests.post")
def test_answers_are_folded_into_an_invented_persona(post):
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("x")
    post.return_value.raise_for_status.return_value = None

    core.generate_persona(
        KEY, "m", "Bolt", [], [("How does it handle being wrong?", "Owns it instantly")], description=ROBOT,
    )
    assert "Owns it instantly" in _sent(post)


@patch("pixieduster.core.requests.post")
def test_questions_are_about_character_when_inventing(post):
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply(
        '[{"question": "How does Bolt react to a bad joke?", "options": ["Laughs", "Groans"]}]'
    )
    post.return_value.raise_for_status.return_value = None

    qs = core.generate_questions(KEY, "m", "Bolt", [], n=1, description=ROBOT)

    prompt = _sent(post)
    assert "designing a fictional persona" in prompt
    assert ROBOT in prompt
    assert qs[0].options == ["Laughs", "Groans"]


@patch("pixieduster.core.requests.post")
def test_description_steers_extraction_when_samples_exist(post):
    """A description plus samples: honor the description, use samples as evidence."""
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("x")
    post.return_value.raise_for_status.return_value = None

    core.generate_persona(
        KEY, "m", "Bolt", [Sample("file", "essay.txt", "I write in bursts.")],
        [], description=ROBOT,
    )
    prompt = _sent(post)
    assert ROBOT in prompt
    # Samples present, so the extraction rubric is the right one.
    assert "PSYCHOLOGICAL & EMPIRICAL PROFILING RUBRIC" in prompt
    assert "I write in bursts." in prompt


@patch("pixieduster.core.requests.post")
def test_uploaded_documents_reach_the_model(post):
    post.return_value.status_code = 200
    post.return_value.json.return_value = _reply("x")
    post.return_value.raise_for_status.return_value = None

    core.generate_persona(
        KEY, "m", "Sarah", [], [],
        files=[("scan.png", "image/png", b"\x89PNG binary")],
    )
    parts = post.call_args.kwargs["json"]["contents"][0]["parts"]
    assert any(p.get("inlineData", {}).get("mimeType") == "image/png" for p in parts)


def test_invent_prompts_carry_the_same_empirical_dimensions():
    """Designing a voice should be as rigorous as reconstructing one."""
    for dimension in ("LIWC", "Big Five", "Cognitive Style", "Sociolinguistics"):
        assert dimension in prompts.INVENT_RUBRIC
