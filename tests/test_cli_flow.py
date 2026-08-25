"""End-to-end CLI tests driven through typer's CliRunner.

Everything here is offline: the two network-touching functions in ``core`` and
the credential lookup are replaced with fakes. The assertions are deliberately
about what the user actually sees on screen, not about internal state:

* a bare ``pixieduster`` guides instead of dumping flags,
* every failure names a next action,
* ``--yes`` and non-interactive runs never block on a question,
* piped output carries no ANSI bytes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from typer.testing import CliRunner

from pixieduster import cli, core, relevance, ui
from pixieduster.types import Question

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

PERSONA_MD = "# Voice Profile\n\nWry, precise, allergic to filler.\n"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network, no key lookup, no writing outside the temp directory."""
    monkeypatch.setattr(cli, "_credentials", lambda *a, **k: ("test-key", None))
    monkeypatch.setattr(cli, "_verify_model", lambda key, model, base=None: model)
    monkeypatch.setattr(core, "generate_questions", lambda *a, **k: [])
    monkeypatch.setattr(core, "generate_persona", lambda *a, **k: PERSONA_MD)
    monkeypatch.setattr(cli.config, "load_settings", lambda: {})
    monkeypatch.setattr(ui, "PLAIN", False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def writing(tmp_path) -> Path:
    """A small folder that looks like a person's own writing."""
    folder = tmp_path / "my-writing"
    folder.mkdir()
    (folder / "morning-note.txt").write_text(
        "I woke up early again and I could not tell you why. I made coffee, I "
        "sat by the window, and I thought about how much I miss the noise of a "
        "house with other people in it. I think I am getting used to it. I do "
        "not think I want to be.\n" * 3,
        encoding="utf-8",
    )
    (folder / "letter.md").write_text(
        "Dear Ellen, I have been meaning to write for weeks and I keep not "
        "doing it, which you will recognize as entirely typical of me. Things "
        "here are good. I have been walking a lot and reading badly.\n" * 3,
        encoding="utf-8",
    )
    return folder


# --------------------------------------------------------------------------
# a bare run guides
# --------------------------------------------------------------------------


def test_bare_run_guides_instead_of_dumping_flags(runner):
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0
    out = result.output
    assert "What this does" in out
    # The old behavior: typer's help screen, a wall of flags.
    assert "Usage:" not in out
    assert "--max-chars" not in out
    assert "--dry-run" not in out


def test_bare_run_says_what_you_get(runner):
    out = runner.invoke(cli.app, []).output
    assert "writes one file" in out
    assert "Nothing is deleted" in out


def test_bare_run_offers_the_three_ways_in(runner):
    out = runner.invoke(cli.app, []).output
    assert "--from" in out
    assert "--describe" in out
    assert "--repo" in out


def test_bare_run_has_no_ansi_when_piped(runner):
    out = runner.invoke(cli.app, []).output
    assert ANSI_RE.search(out) is None
    assert "\x1b" not in out


def test_help_still_lists_every_flag(runner):
    out = runner.invoke(cli.app, ["clone", "--help"]).output
    for flag in ("--from", "--describe", "--repo", "--dry-run", "--scrub",
                 "--max-chars", "--yes", "--plain", "--all-files"):
        assert flag in out


# --------------------------------------------------------------------------
# failures name a next action
# --------------------------------------------------------------------------


def _actions(output: str) -> list[str]:
    """The numbered next actions printed by ui.dead_end."""
    return re.findall(r"^\s*\d+\.\s+(.*)$", output, flags=re.M)


def test_no_source_names_next_actions(runner):
    result = runner.invoke(cli.app, ["clone"])
    assert result.exit_code == 2
    actions = _actions(result.output)
    assert actions, result.output
    assert any("--from" in a for a in actions)
    assert any("--describe" in a for a in actions)


def test_missing_folder_names_next_actions(runner, tmp_path):
    result = runner.invoke(cli.app, ["clone", "--from", str(tmp_path / "nope"), "--yes"])
    assert result.exit_code == 2
    actions = _actions(result.output)
    assert actions, result.output
    assert any("folder" in a.lower() for a in actions)


def test_unreadable_file_type_explains_the_alternative(runner, tmp_path):
    doc = tmp_path / "essay.docx"
    doc.write_bytes(b"not really a docx")
    result = runner.invoke(cli.app, ["clone", "--from", str(doc), "--yes"])
    assert result.exit_code == 2
    assert "PDF" in result.output


def test_empty_folder_names_next_actions(runner, tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    (folder / "notes.txt").write_text("   \n", encoding="utf-8")
    result = runner.invoke(cli.app, ["clone", "--from", str(folder), "--yes"])
    assert result.exit_code != 0
    assert _actions(result.output)


def test_api_failure_names_next_actions(runner, writing, monkeypatch):
    def boom(*a, **k):
        raise core.GeminiError("the model is busy")

    monkeypatch.setattr(core, "generate_persona", boom)
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"])
    assert result.exit_code == 1
    actions = _actions(result.output)
    assert any("pixieduster status" in a for a in actions)


def test_every_dead_end_prints_at_least_two_actions(runner, tmp_path):
    """A failure with one option is a dead end wearing a hat."""
    for argv in (["clone"], ["clone", "--from", str(tmp_path / "nope"), "--yes"]):
        result = runner.invoke(cli.app, argv)
        assert len(_actions(result.output)) >= 2, argv


# --------------------------------------------------------------------------
# --yes and non-interactive runs never block
# --------------------------------------------------------------------------


def test_yes_completes_without_a_single_prompt(runner, writing, tmp_path):
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"], input="")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "persona.md").read_text(encoding="utf-8") == PERSONA_MD


def test_non_interactive_run_never_blocks(runner, writing, tmp_path):
    """No --yes, no TTY: still must not wait for an answer."""
    result = runner.invoke(cli.app, ["clone", "--from", str(writing)], input="")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "persona.md").exists()


def test_yes_overwrites_without_asking(runner, writing, tmp_path):
    (tmp_path / "persona.md").write_text("old", encoding="utf-8")
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "persona.md").read_text(encoding="utf-8") == PERSONA_MD


def test_questions_are_never_asked_without_a_tty(runner, writing, monkeypatch):
    monkeypatch.setattr(
        core, "generate_questions",
        lambda *a, **k: [Question(question="How direct are you?", options=["Very", "Not"])],
    )
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"])
    assert result.exit_code == 0, result.output
    assert "How direct are you?" not in result.output


def test_full_run_has_no_ansi_when_piped(runner, writing):
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"])
    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.output


# --------------------------------------------------------------------------
# what happens next
# --------------------------------------------------------------------------


def test_finish_tells_you_where_the_file_is_and_what_to_do(runner, writing):
    out = runner.invoke(cli.app, ["clone", "--from", str(writing), "--yes"]).output
    assert "persona.md" in out
    assert "paste" in out.lower()
    assert "pixieduster chat --persona" in out


def test_agent_filename_says_there_is_nothing_else_to_do(runner, writing, tmp_path):
    out = runner.invoke(
        cli.app,
        ["clone", "--from", str(writing), "--yes", "--output", str(tmp_path / "CLAUDE.md")],
    ).output
    assert "automatically" in out
    assert "nothing else to do" in out.lower()
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8").endswith(PERSONA_MD)


def test_output_question_is_about_outcomes_not_filenames():
    labels = [label for label, _ in cli.OUTPUT_CHOICES]
    assert all(not label.endswith(".md") for label in labels)
    assert any("Claude Code" in label for label in labels)
    assert dict(cli.OUTPUT_CHOICES)[labels[0]] == "persona.md"


def test_output_choice_is_asked_when_someone_can_answer(runner, writing, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    asked: list[str] = []

    def fake_choice(question, options, index, total):
        asked.append(question)
        if question.startswith("When this is finished"):
            return options[1]  # "Make Claude Code write like this ..."
        return options[0]

    monkeypatch.setattr(ui, "ask_choice", fake_choice)
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    result = runner.invoke(cli.app, ["clone", "--from", str(writing)])
    assert result.exit_code == 0, result.output
    assert any(q.startswith("When this is finished") for q in asked)
    assert (tmp_path / "CLAUDE.md").exists()


# --------------------------------------------------------------------------
# sending is confirmed in plain language, and inspectable
# --------------------------------------------------------------------------


def test_send_confirmation_is_plain_language(runner, writing, monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    seen: list[str] = []

    def fake_choice(question, options, index, total):
        seen.append(question)
        return options[0]

    monkeypatch.setattr(ui, "ask_choice", fake_choice)
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    monkeypatch.setattr(ui, "ask_multi", lambda *a, **k: [])
    out = runner.invoke(cli.app, ["clone", "--from", str(writing)]).output
    assert "leaves your computer" in out
    assert "Send it?" in seen


def test_send_confirmation_can_show_the_payload(runner, writing, monkeypatch):
    """The old --dry-run, now reachable without knowing the flag exists."""
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    replies = iter(["show", "yes"])

    def fake_choice(question, options, index, total):
        if question == "Send it?":
            return options[1] if next(replies) == "show" else options[0]
        return options[0]

    monkeypatch.setattr(ui, "ask_choice", fake_choice)
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    monkeypatch.setattr(ui, "ask_multi", lambda *a, **k: [])
    result = runner.invoke(cli.app, ["clone", "--from", str(writing)])
    assert result.exit_code == 0, result.output
    assert "morning-note.txt" in result.output


def test_saying_no_sends_nothing(runner, writing, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)

    def fake_choice(question, options, index, total):
        return options[2] if question == "Send it?" else options[0]

    monkeypatch.setattr(ui, "ask_choice", fake_choice)
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    monkeypatch.setattr(ui, "ask_multi", lambda *a, **k: [])
    result = runner.invoke(cli.app, ["clone", "--from", str(writing)])
    assert result.exit_code == 1
    assert "Nothing was sent" in result.output
    assert not (tmp_path / "persona.md").exists()


def test_dry_run_flag_still_works(runner, writing):
    result = runner.invoke(cli.app, ["clone", "--from", str(writing), "--dry-run"])
    assert result.exit_code == 0
    assert "morning-note.txt" in result.output


# --------------------------------------------------------------------------
# relevance triage: nothing is dropped silently
# --------------------------------------------------------------------------


@pytest.fixture
def mixed(writing) -> Path:
    """The same writing folder, with two things that are plainly not writing."""
    (writing / "invoice-2411.txt").write_text(
        "INVOICE 2411\nDUE DATE 2024-11-30\nSubtotal $1,240.00\nVAT $248.00\n"
        "TOTAL DUE $1,488.00\nPAYMENT TERMS NET 30\nACCOUNT 0084 2213\n",
        encoding="utf-8",
    )
    (writing / "shopping.txt").write_text(
        "milk\neggs\nbread\ncoffee\nbin bags\nolive oil\n", encoding="utf-8"
    )
    return writing


def test_skipped_files_are_named_with_a_reason(runner, mixed):
    out = runner.invoke(cli.app, ["clone", "--from", str(mixed), "--yes"]).output
    kept, rejected = relevance.triage(*_load(mixed))
    if not rejected:
        pytest.skip("triage kept everything in this folder")
    for item in rejected:
        assert ui.origin_of(item) in out
        assert item.reason.split()[0] in out
    assert "Nothing was deleted" in out


def test_triage_report_lists_what_will_be_used(runner, mixed):
    out = runner.invoke(cli.app, ["clone", "--from", str(mixed), "--yes"]).output
    assert "morning-note.txt" in out
    assert re.search(r"Using \d+ of \d+ file", out)


def test_all_files_skips_triage_entirely(runner, mixed):
    out = runner.invoke(cli.app, ["clone", "--from", str(mixed), "--yes", "--all-files"]).output
    assert "Left out" not in out


def test_rejected_files_can_be_put_back(runner, mixed, monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    monkeypatch.setattr(ui, "ask_choice", lambda q, o, i, t: o[0])
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    offered: list[list[str]] = []

    def fake_multi(question, options):
        offered.append(options)
        return list(range(len(options)))  # put everything back

    monkeypatch.setattr(ui, "ask_multi", fake_multi)

    sent: dict[str, int] = {}

    def capture(key, model, name, samples, answers, **kwargs):
        sent["samples"] = len(samples)
        return PERSONA_MD

    monkeypatch.setattr(core, "generate_persona", capture)

    result = runner.invoke(cli.app, ["clone", "--from", str(mixed)])
    assert result.exit_code == 0, result.output
    if not offered:
        pytest.skip("triage kept everything in this folder")
    assert sent["samples"] == 4


def test_triage_failure_falls_back_to_using_everything(runner, mixed, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("triage exploded")

    monkeypatch.setattr(cli.relevance, "triage", boom)
    result = runner.invoke(cli.app, ["clone", "--from", str(mixed), "--yes"])
    assert result.exit_code == 0, result.output


def _load(folder: Path):
    from pixieduster import sources

    return sources.load([folder])


# --------------------------------------------------------------------------
# the interview is framed
# --------------------------------------------------------------------------


def test_questions_are_introduced_before_they_are_asked(runner, writing, monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    monkeypatch.setattr(
        core, "generate_questions",
        lambda *a, **k: [
            Question(question="How direct are you?", options=["Very", "Not"]),
            Question(question="Do you swear?", options=["Often", "Never"]),
        ],
    )
    order: list[str] = []

    def fake_choice(question, options, index, total):
        order.append(question)
        return options[0]

    monkeypatch.setattr(ui, "ask_choice", fake_choice)
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "me")
    monkeypatch.setattr(ui, "ask_multi", lambda *a, **k: [])

    out = runner.invoke(cli.app, ["clone", "--from", str(writing)]).output
    assert "2 quick questions" in out
    assert "no wrong answers" in out
    assert order[-2:] == ["How direct are you?", "Do you swear?"]


# --------------------------------------------------------------------------
# --describe still works end to end
# --------------------------------------------------------------------------


def test_describe_still_works(runner, tmp_path):
    result = runner.invoke(
        cli.app, ["clone", "--describe", "a friendly desktop robot", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "persona.md").exists()


# --------------------------------------------------------------------------
# the single Live region is respected
# --------------------------------------------------------------------------


def test_no_prompt_is_nested_inside_a_live_widget():
    """Every ask_* call must sit outside the stages() blocks that own Live."""
    import inspect

    src = inspect.getsource(cli._run_clone)
    depth = 0
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith("with ui.stages("):
            depth = len(line) - len(line.lstrip())
            continue
        if depth and stripped and (len(line) - len(line.lstrip())) <= depth:
            depth = 0
        if depth:
            assert "ui.ask_" not in stripped, stripped
            assert "ui.confirm(" not in stripped, stripped
    assert "ui.dust(" not in src


def test_run_clone_is_callable_with_plain_defaults(runner, writing, tmp_path):
    """The bare `pixieduster` path calls _run_clone() directly, not via typer."""
    cli._run_clone(from_=[writing], assume_yes=True)
    assert (tmp_path / "persona.md").exists()


def test_describe_only_does_not_claim_files_are_being_sent(runner, monkeypatch):
    monkeypatch.setattr(cli, "_can_ask", lambda: True)
    monkeypatch.setattr(ui, "ask_choice", lambda q, o, i, t: o[0])
    monkeypatch.setattr(ui, "ask_text", lambda *a, **k: "Robbie")
    out = runner.invoke(cli.app, ["clone", "--describe", "a desktop robot"]).output
    assert "leaves your computer" not in out


def test_plain_flag_works_before_and_after_the_subcommand(runner, writing, monkeypatch):
    for argv in (["--plain", "clone", "--from", str(writing), "--yes"],
                 ["clone", "--from", str(writing), "--yes", "--plain"]):
        monkeypatch.setattr(ui, "PLAIN", False)
        result = runner.invoke(cli.app, argv)
        assert result.exit_code == 0, (argv, result.output)
        assert "\x1b" not in result.output
