"""PixieDuster command line interface.

Commands:
    login   sign in with Hugging Face (free tier)
    clone   build a persona - from a description, from writing samples, or from a repo
    chat    talk to a generated persona
    diff    score a draft against a persona
    config  manage the stored API key and settings
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from . import __version__, config, core, hosted, mining, prompts, safety, sources, ui
from .types import Sample

try:  # relevance triage is a nicety: the CLI still works without it
    from . import relevance
except ImportError:  # pragma: no cover - only while relevance.py is being written
    relevance = None  # type: ignore[assignment]

app = typer.Typer(
    name="pixieduster",
    help="Turn your own writing into a persona prompt any AI can write in. New here? Just run  pixieduster  with nothing after it.",
    add_completion=False,
    no_args_is_help=False,
    invoke_without_command=True,
    rich_markup_mode=None,
)
config_app = typer.Typer(help="Manage the stored API key and settings.", no_args_is_help=True)
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    plain: bool = typer.Option(False, "--plain", help="No color or animation."),
) -> None:
    """Build an AI persona prompt from your own writing.

    Run ``pixieduster`` with nothing after it and it will walk you through it.
    """
    _apply_plain(plain)
    if ctx.invoked_subcommand is not None:
        return
    _first_run()


def _first_run() -> None:
    """What a bare ``pixieduster`` does: guide, rather than list flags.

    On a real terminal this is the whole guided build. Anywhere a question
    cannot be answered (a pipe, a script, CI) it prints the three ways in and
    exits cleanly, instead of dumping a wall of flags at someone.
    """
    if not ui.is_plain():
        ui.banner()
    ui.welcome()

    if not _can_ask():
        ui.note(
            "Three ways to start",
            [
                "pixieduster clone --from ~/Documents/my-writing",
                "    read a folder of your own notes, emails, screenshots, essays",
                "",
                'pixieduster clone --describe "a friendly desktop robot"',
                "    invent a character from a sentence",
                "",
                "pixieduster clone --repo /path/to/a/git/repo",
                "    advanced: read a codebase's commits and docs",
                "",
                "Every flag:  pixieduster --help",
            ],
        )
        raise typer.Exit(code=0)

    _run_clone(guided=True)



# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def _apply_plain(plain: bool) -> None:
    if plain:
        ui.PLAIN = True


def _can_ask() -> bool:
    """True when there is a human at a keyboard who can answer a question.

    Everything that prompts checks this first, so ``--yes``, pipes, scripts and
    CI never block on a question.
    """
    try:
        return sys.stdin.isatty()
    except Exception:  # pragma: no cover - exotic stdin replacements
        return False


def _preferred_model(available: list[str]) -> str | None:
    """Pick the best available fast model, newest major version first."""
    flash = [m for m in available if "flash" in m and "thinking" not in m and "live" not in m]
    if not flash:
        flash = [m for m in available if "pro" in m]
    if not flash:
        return None

    def score(name: str) -> tuple[float, int]:
        import re
        match = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
        version = float(match.group(1)) if match else 0.0
        # prefer a plain "-flash" over "-flash-8b"/"-flash-lite" at the same version
        plain = 1 if name.rstrip("0123456789.-").endswith("flash") else 0
        return (version, plain)

    return max(flash, key=score)


def _verify_model(key: str, model: str, base_url: str | None = None) -> str:
    """Check the model exists, falling back to the best available one if not.

    The default was never validated against a live model list, so an invalid id
    would otherwise surface as an opaque 404 on the first real call. Result is
    cached in settings so this costs one cheap GET, once.
    """
    settings = config.load_settings()
    if settings.get("verified_model") == model:
        return model

    try:
        available = core.list_models(key, base_url=base_url)
    except core.GeminiError:
        return model  # network trouble is the caller's problem to report, not ours

    if model in available:
        config.save_setting("verified_model", model)
        return model

    replacement = _preferred_model(available)
    if replacement is None:
        ui.error(f"Model '{model}' is not available to your key, and no alternative was found.")
        ui.hint("See what you can reach with:  pixieduster config models")
        raise typer.Exit(code=1)

    ui.hint(
        f"Model '{model}' is not available to your API key. Using '{replacement}' instead.\n"
        f"Make it permanent with:  pixieduster config set-model {replacement}"
    )
    config.save_setting("verified_model", replacement)
    return replacement


def _resolve_repo(repo: Path | None) -> Path:
    path = (repo or Path.cwd()).resolve()
    if not path.exists():
        ui.error(f"No such path: {path}")
        raise typer.Exit(code=2)
    if not mining.is_git_repo(path):
        ui.error(f"Not a git repository: {path}")
        ui.hint("PixieDuster mines git history for writing samples. Try --repo /path/to/repo")
        raise typer.Exit(code=2)
    return path


def _safety_gate(
    samples: list[Sample],
    model: str,
    *,
    assume_yes: bool,
    scrub: bool,
) -> list[Sample]:
    """Stop if the outbound text contains something that looks like a secret.

    The "is it fine to send this at all" question is asked earlier, by
    :func:`_confirm_send`. This is only about passwords and keys that happen to
    be sitting in the writing.
    """
    findings = safety.scan(samples)
    if not findings:
        return samples

    high = [f for f in findings if f.severity == "high"]
    ui.error(
        f"{len(findings)} thing(s) in your writing look like passwords or keys"
        + (f" - {len(high)} of them strongly." if high else ".")
    )
    ui.findings_table(findings)

    if scrub:
        ui.hint("--scrub is on: these will be replaced with <REDACTED:rule> before sending.")
        return [
            Sample(
                kind=s.kind,
                origin=s.origin,
                text=safety.redact(s.text),
                author=s.author,
                tokens=s.tokens,
            )
            for s in samples
        ]

    if assume_yes or not _can_ask():
        return samples

    choice = ui.ask_choice(
        "What should happen to those?",
        [
            "Black them out before sending (recommended)",
            "Send them as they are",
            "Stop, I want to take them out of the folder myself",
        ],
        1, 1,
    )
    if choice.startswith("Black"):
        return [
            Sample(
                kind=s.kind,
                origin=s.origin,
                text=safety.redact(s.text),
                author=s.author,
                tokens=s.tokens,
            )
            for s in samples
        ]
    if choice.startswith("Stop"):
        ui.hint("Nothing was sent. The files listed above are the ones to look at.")
        raise typer.Exit(code=1)
    return samples


def _credentials(api_key: str | None, *, prefer_own: bool = False) -> tuple[str, str | None]:
    """Work out what to authenticate with.

    Returns ``(credential, base_url)``. A ``base_url`` of None means we are
    talking to Google directly with the user's own Gemini key; otherwise the
    credential is a Hugging Face token and the request goes through the hosted
    Space, which supplies the Gemini key on its side.

    Preference order: an explicit --api-key always wins, then a stored Gemini
    key if the user has chosen to use their own, then hosted, then any Gemini
    key we can find, then an offer to sign in.
    """
    if api_key:
        return api_key, None

    own_first = prefer_own or config.load_settings().get("mode") == "byok"
    if own_first:
        key = config.resolve_api_key(None)
        if key:
            return key, None

    token = hosted.resolve_token()
    if token:
        return token, hosted.endpoint()

    key = config.resolve_api_key(None)
    if key:
        return key, None

    # Nothing at all. Offer the one-time sign-in.
    if not _can_ask():
        ui.dead_end(
            "PixieDuster does not know who you are yet, so it cannot do the reading.",
            [
                "Sign in once, free, with a Hugging Face account:  pixieduster login",
                "Or use your own Gemini key:  pixieduster config set-key",
                "Then run the same command again.",
            ],
        )
        raise typer.Exit(code=2)

    ui.hint(
        "PixieDuster is free to use with a Hugging Face account.\n"
        "You can also bring your own Gemini key instead."
    )
    if ui.confirm("Sign in with Hugging Face now?", default=True):
        return _do_login(None), hosted.endpoint()

    entered = ui.ask_text("Gemini API key", password=True).strip()
    if not entered:
        ui.error("No key entered.")
        raise typer.Exit(code=2)
    if ui.confirm("Save this key for next time?", default=True):
        path = config.save_api_key(entered)
        ui.success(f"Saved to {path} (permissions 0600).")
    return entered, None


def _do_login(token: str | None) -> str:
    """Verify a Hugging Face token, store it, and report the quota."""
    if token is None:
        token = hosted.resolve_token()

    if not token:
        ui.hint(
            "PixieDuster needs a Hugging Face token to know who you are.\n"
            f"Make one (read access is enough) at:  {hosted.TOKEN_PAGE}"
        )
        try:
            import webbrowser

            webbrowser.open(hosted.TOKEN_PAGE)
        except Exception:  # pragma: no cover - headless machines
            pass
        token = ui.ask_text("Paste your Hugging Face token", password=True).strip()

    if not token:
        ui.error("No token entered.")
        raise typer.Exit(code=2)

    try:
        info = hosted.check(token)
    except hosted.HostedError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1)

    config.save_setting("mode", "hosted")
    path = config.save_hf_token(token)
    ui.success(hosted.quota_message(info))
    ui.hint(f"Token saved to {path} (permissions 0600).")
    return token


#: Filenames that a coding agent reads automatically.
#:   AGENTS.md   the cross-tool convention (Claude Code, Cursor, and others)
#:   CLAUDE.md   Claude Code specifically
#:   GEMINI.md   the Gemini CLI
#: Any other name is just a file you paste in yourself.
AGENT_FILENAMES = {"agents.md", "claude.md", "gemini.md"}


def _default_persona(explicit):
    """persona.md, AGENTS.md, or CLAUDE.md - whichever exists."""
    if explicit is not None:
        return explicit
    for candidate in (Path("persona.md"), Path("AGENTS.md"),
                      Path("CLAUDE.md"), Path("GEMINI.md")):
        if candidate.exists():
            return candidate
    return Path("persona.md")


# --------------------------------------------------------------------------
# clone
# --------------------------------------------------------------------------

#: What the user wants to happen, in their words, and the filename that does it.
#: The filename is an implementation detail; the outcome is what gets asked.
OUTPUT_CHOICES: list[tuple[str, str]] = [
    ("Just give me the file. I will paste it into ChatGPT, Claude or Gemini myself.",
     "persona.md"),
    ("Make Claude Code write like this whenever I work in this folder.",
     "CLAUDE.md"),
    ("Make Cursor, Copilot or another coding tool write like this in this folder.",
     "AGENTS.md"),
    ("Make the Gemini CLI write like this in this folder.",
     "GEMINI.md"),
]


def _ask_output(assume_yes: bool, use_repo: bool) -> Path:
    """Ask what the user wants to happen, and turn that into a filename."""
    if assume_yes or not _can_ask():
        return Path("AGENTS.md") if use_repo else Path("persona.md")

    labels = [label for label, _ in OUTPUT_CHOICES]
    picked = ui.ask_choice("When this is finished, what do you want to happen?",
                           labels, 1, 1)
    return Path(dict(OUTPUT_CHOICES)[picked])


def _pick_source(assume_yes: bool) -> tuple[str | None, list[Path], Path | None]:
    """Ask what to learn from. Returns ``(describe, from_, repo)``."""
    picked = ui.ask_choice(
        "What should PixieDuster learn from?",
        [
            "A folder of my writing (notes, screenshots, emails, essays)",
            "Nothing - invent a character from a description",
            "A git repo (commits, README, docstrings)",
        ],
        1, 1,
    )
    if picked.startswith("A folder"):
        ui.note(
            "Point it at a folder",
            [
                "Anything with your voice in it counts: photos of handwritten",
                "notes, screenshots of texts, saved emails, old essays, notes.",
                "",
                "Tip: you can drag the folder from Finder into this window and",
                "its path will be typed for you.",
            ],
        )
        entered = ui.ask_text("Folder (or file) to read").strip().strip("'\"")
        if not entered:
            ui.dead_end(
                "No folder given, so there is nothing to read.",
                [
                    "Run  pixieduster  again and drag a folder into the window.",
                    "Or run:  pixieduster clone --from ~/Documents/my-writing",
                    "Or invent a character instead:  pixieduster clone "
                    "--describe \"a warm, blunt science teacher\"",
                ],
            )
            raise typer.Exit(code=2)
        return None, [Path(entered).expanduser()], None

    if picked.startswith("Nothing"):
        described = ui.ask_text(
            "Describe the persona", default="a friendly desktop robot with great humor"
        ).strip()
        return described, [], None

    return None, [], Path.cwd()


def _triage_samples(
    samples: list[Sample],
    files: list[tuple[str, str, bytes]],
    *,
    max_chars: int,
    assume_yes: bool,
    all_files: bool,
) -> tuple[list[Sample], list[tuple[str, str, bytes]]]:
    """Show what looks like the user's writing, and let them put things back.

    Nothing is dropped silently. Everything left out is named, with the reason,
    and the user can tick any of it back in. Falls back to using everything if
    the relevance module is unavailable or errors.
    """
    if all_files or relevance is None or (not samples and not files):
        return samples, files

    try:
        kept, rejected = relevance.triage(samples, files, budget_chars=max_chars)
    except Exception:  # pragma: no cover - never fail a run over a nicety
        return samples, files

    if not kept and not rejected:
        return samples, files

    ui.triage_report(kept, rejected)

    if rejected and not assume_yes and _can_ask():
        labels = [
            f"{ui.origin_of(s)}  -  {getattr(s, 'reason', '')}" for s in rejected
        ]
        picked = ui.ask_multi("Put any of these back in?", labels)
        kept = list(kept) + [rejected[i] for i in picked]

    if not kept:
        return [], []

    out_samples = [s.sample for s in kept if getattr(s, "sample", None) is not None]
    out_files = [s.file for s in kept if getattr(s, "file", None) is not None]
    return out_samples, out_files


def _confirm_send(
    samples: list[Sample],
    files: list[tuple[str, str, bytes]],
    binary_notes: list[str],
    describe: str | None,
    model: str,
    *,
    assume_yes: bool,
) -> None:
    """Say plainly what leaves the machine, and offer to show it, before sending.

    This is what ``--dry-run`` used to be: a flag nobody would ever discover.
    Now inspecting the payload is one of the answers to the question.
    """
    tokens_in = sum(s.tokens or safety.estimate_tokens(s.text) for s in samples)
    est = safety.estimate_cost(tokens_in, 2000, model)
    count = len(samples) + len(files)

    if not count:  # nothing but a --describe sentence: nothing personal leaves
        return

    if assume_yes or not _can_ask():
        ui.hint(f"Sending {count} file(s) to Google's Gemini model to be read.")
        return

    lines = [
        f"{count} file(s) are about to be copied over the internet to Google's",
        "Gemini model, which reads them and writes back a description of how",
        "you write.",
        "",
        "Your files are not moved, changed or deleted. PixieDuster keeps no",
        "copy of them.",
    ]
    if est is not None:
        lines += ["", f"Roughly {tokens_in:,} words' worth of text. Estimated cost: ${est:.4f}."]
    ui.note("This is the part that leaves your computer", lines)

    while True:
        answer = ui.ask_choice(
            "Send it?",
            [
                "Yes, read my writing and build the persona",
                "Show me exactly what would be sent, first",
                "No, stop here",
            ],
            1, 1,
        )
        if answer.startswith("Yes"):
            return
        if answer.startswith("No"):
            ui.hint("Nothing was sent. Nothing was changed.")
            raise typer.Exit(code=1)
        print(_dry_run_report(samples, binary_notes, describe, model))


def _dry_run_report(
    samples: list[Sample],
    binary_notes: list[str],
    describe: str | None,
    model: str,
) -> str:
    """The exact outbound payload, rendered for a human to read."""
    report = safety.dry_run_report(samples, safety.scan(samples), model)
    if describe:
        report += f"\n\nPERSONA DESCRIPTION (sent as text)\n{'-' * 60}\n  {describe}\n"
    if binary_notes:
        report += ("\n\nDOCUMENTS AND IMAGES\n" + "-" * 60 + "\n"
                   + "\n".join(f"  {line}" for line in binary_notes) + "\n")
    return report


@app.command()
def clone(
    describe: str = typer.Option(None, "--describe", "-d", help="Invent a persona from a description, e.g. \"a friendly desktop robot with great humor\"."),
    from_: list[Path] = typer.Option(None, "--from", "-f", help="A folder of your writing: notes, screenshots, photos of handwriting, emails, essays. Repeatable."),
    repo: Path = typer.Option(None, "--repo", "-r", help="Advanced: read writing out of a git repo instead (commits, README, docstrings)."),
    author: str = typer.Option(None, "--author", "-a", help="With --repo: email to clone. Omit for the collective voice."),
    output: Path = typer.Option(None, "--output", "-o", help="Where to write it. Name it AGENTS.md, CLAUDE.md or GEMINI.md and that tool picks it up automatically. Default: persona.md (AGENTS.md for --repo)."),
    name: str = typer.Option(None, "--name", "-n", help="Name for the persona."),
    model: str = typer.Option(None, "--model", help=f"Gemini model (default: {core.DEFAULT_MODEL})."),
    api_key: str = typer.Option(None, "--api-key", help="Use this Gemini key instead of the free hosted service.", show_default=False),
    byok: bool = typer.Option(False, "--byok", help="Use your own stored Gemini key rather than the hosted service."),
    questions: int = typer.Option(3, "--questions", "-q", min=0, max=8, help="Profiling questions to ask."),
    max_chars: int = typer.Option(180_000, "--max-chars", help="Cap on mined characters."),
    no_pr: bool = typer.Option(False, "--no-pr", help="Skip GitHub PR mining."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be sent, then exit."),
    scrub: bool = typer.Option(False, "--scrub", help="Redact detected secrets instead of asking."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    all_files: bool = typer.Option(False, "--all-files", help="Send every readable file, without checking which look like your own writing."),
    plain: bool = typer.Option(False, "--plain", help="No color or animation."),
) -> None:
    """Build a persona prompt: from a description, from writing samples, or from a repo."""
    _run_clone(
        describe=describe, from_=list(from_ or []), repo=repo, author=author,
        output=output, name=name, model=model, api_key=api_key, byok=byok,
        questions=questions, max_chars=max_chars, no_pr=no_pr, dry_run=dry_run,
        scrub=scrub, assume_yes=assume_yes, all_files=all_files, plain=plain,
    )


def _run_clone(
    *,
    describe: str | None = None,
    from_: list[Path] | None = None,
    repo: Path | None = None,
    author: str | None = None,
    output: Path | None = None,
    name: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    byok: bool = False,
    questions: int = 3,
    max_chars: int = 180_000,
    no_pr: bool = False,
    dry_run: bool = False,
    scrub: bool = False,
    assume_yes: bool = False,
    all_files: bool = False,
    plain: bool = False,
    guided: bool = False,
) -> None:
    """The whole clone flow, callable with ordinary Python defaults.

    ``clone()`` is the flag-driven front door; the bare ``pixieduster`` command
    calls this directly with ``guided=True`` so a first-time user never has to
    know a flag exists.
    """
    _apply_plain(plain)
    model = model or config.load_settings().get("model") or core.DEFAULT_MODEL
    from_ = list(from_ or [])

    if not guided and not ui.is_plain():
        ui.banner()

    # No source given. Most people mean "a folder of my writing", so ask rather
    # than quietly mining whatever repo they happen to be standing in.
    if not describe and not from_ and repo is None:
        if not _can_ask() or assume_yes:
            ui.dead_end(
                "PixieDuster was not told what to learn from.",
                [
                    "Point it at a folder of your writing:  pixieduster clone "
                    "--from ~/Documents/my-writing",
                    "Or invent a character:  pixieduster clone --describe "
                    "\"a friendly desktop robot with great humor\"",
                    "Or, in a terminal you can type into, just run:  pixieduster",
                ],
            )
            raise typer.Exit(code=2)
        describe, from_, repo = _pick_source(assume_yes)

    use_repo = repo is not None and not from_

    samples: list[Sample] = []
    files: list[tuple[str, str, bytes]] = []
    binary_notes: list[str] = []
    target_name = name

    # --- gather evidence, if there is any ---------------------------------
    if from_:
        where = ", ".join(str(p) for p in from_)
        try:
            samples, files = sources.load(from_)
        except sources.SourceError as exc:
            ui.dead_end(
                str(exc),
                [
                    f"Check the folder is the one you meant: {where}",
                    "PixieDuster reads text notes, emails, PDFs, screenshots and "
                    "photos. It cannot read Word or Pages documents: export those "
                    "as PDF first.",
                    "Or invent a character instead:  pixieduster clone --describe "
                    "\"a warm, blunt science teacher\"",
                ],
            )
            raise typer.Exit(code=2)

        ui.hint(
            f"Read {len(samples)} text file(s) and {len(files)} image(s)/document(s). "
            "Handwriting and screenshots are read by the model directly."
        )
        samples, files = _triage_samples(
            samples, files, max_chars=max_chars, assume_yes=assume_yes,
            all_files=all_files,
        )
        binary_notes = sources.describe(files)

        if not samples and not files:
            ui.dead_end(
                "Nothing in that folder looked like your own writing.",
                [
                    "Point it at a folder with more of your own words in it: "
                    "notes, essays, saved emails, screenshots of messages.",
                    "Or run it again and tick the skipped files back in when asked.",
                    "Or use everything in the folder regardless:  pixieduster clone "
                    f"--from {from_[0]} --all-files",
                ],
            )
            raise typer.Exit(code=1)

    elif use_repo:
        repo_path = _resolve_repo(repo)
        authors = mining.list_authors(repo_path)

        if author is None and authors and not assume_yes and _can_ask():
            if len(authors) > 1:
                opts = [f"{n} <{e}>  ({c} commits)" for e, n, c in authors[:8]]
                opts.append("Everyone (the repo's collective voice)")
                picked = ui.ask_choice("Whose voice are we cloning?", opts, 1, 1)
                if not picked.startswith("Everyone"):
                    author = authors[opts.index(picked)][0]

        if target_name is None:
            if author:
                target_name = next((n for e, n, _ in authors if e == author), author)
            else:
                target_name = f"the {repo_path.name} maintainers"

        with ui.stages("Reading the repository") as stage:
            stage("Inspecting your writing samples", icon="magnifier")
            samples = mining.mine_all(
                repo_path, author=author, budget_chars=max_chars, prs=not no_pr
            )
            stage("Balancing the sample set", icon="list")

    # --- name the persona --------------------------------------------------
    if target_name is None:
        if describe and _can_ask() and not assume_yes:
            target_name = ui.ask_text("What should this persona be called?",
                                      default="the persona").strip()
        elif from_ and _can_ask() and not assume_yes:
            target_name = ui.ask_text(
                "Whose voice is this? (a name, used only inside the file)",
                default="me",
            ).strip()
        else:
            target_name = "the persona"

    for sample in samples:
        if not sample.tokens:
            sample.tokens = safety.estimate_tokens(sample.text)

    if not samples and not files and not describe:
        ui.dead_end(
            "There was no usable writing in what you pointed at.",
            [
                "Try a folder with more words in it: notes, essays, saved emails, "
                "screenshots of messages, photos of handwriting.",
                "Or invent a character instead:  pixieduster clone --describe "
                "\"a friendly desktop robot with great humor\"",
                "Or read a git repo:  pixieduster clone --repo /path/to/repo",
            ],
        )
        raise typer.Exit(code=1)

    # --- dry run exits here ------------------------------------------------
    if dry_run:
        print(_dry_run_report(samples, binary_notes, describe, model))
        raise typer.Exit(code=0)

    key, base_url = _credentials(api_key, prefer_own=byok)
    model = _verify_model(key, model, base_url)

    _confirm_send(samples, files, binary_notes, describe, model, assume_yes=assume_yes)

    if samples:
        samples = _safety_gate(samples, model, assume_yes=assume_yes, scrub=scrub)

    # --- where the result should go ---------------------------------------
    if output is None:
        output = _ask_output(assume_yes, use_repo and not describe)

    # --- interview ---------------------------------------------------------
    answers: list[tuple[str, str]] = []
    if questions:
        try:
            with ui.stages("Studying the voice") as stage:
                stage("Formulating profiling questions", icon="list")
                qs = core.generate_questions(
                    key, model, target_name, samples, n=questions,
                    description=describe, files=files or None, base_url=base_url,
                )
        except core.GeminiError as exc:
            ui.dead_end(
                str(exc),
                [
                    "Wait a minute and run it again: this is usually a temporary "
                    "network or quota problem.",
                    "Check where you stand:  pixieduster status",
                    "Skip the questions entirely:  pixieduster clone --questions 0",
                ],
            )
            raise typer.Exit(code=1)

        if qs and _can_ask():
            ui.note(
                f"{len(qs)} quick question{'s' if len(qs) != 1 else ''}",
                [
                    "Your writing answered most of this already. These fill in the",
                    "parts writing cannot show.",
                    "",
                    "There are no wrong answers. Pick whichever sounds most like",
                    f"{target_name}. Arrow keys to move, enter to choose.",
                ],
            )
            for i, q in enumerate(qs, 1):
                chosen = ui.ask_choice(q.question, q.options, i, len(qs))
                answers.append((q.question, chosen))

    # --- generate ----------------------------------------------------------
    try:
        with ui.stages("Distilling the persona") as stage:
            stage("Evaluating Big Five personality traits", icon="brain")
            stage("Analyzing LIWC syntax and pronoun orientation", icon="chart")
            stage("Assessing cognitive style", icon="puzzle")
            stage("Mapping sociolinguistics", icon="comments")
            persona = core.generate_persona(
                key, model, target_name, samples, answers,
                description=describe, files=files or None, base_url=base_url,
            )
    except core.GeminiError as exc:
        ui.dead_end(
            str(exc),
            [
                "Wait a minute and run it again: this is usually a temporary "
                "network or quota problem.",
                "Check where you stand:  pixieduster status",
                "If you have your own Gemini key:  pixieduster clone --byok",
            ],
        )
        raise typer.Exit(code=1)

    # --- write -------------------------------------------------------------
    # Filenames a coding agent picks up on its own. Same persona either way --
    # these just get a preamble telling the agent it governs prose, not code.
    body = persona
    is_agent_file = output.name.lower() in AGENT_FILENAMES
    if is_agent_file:
        body = prompts.AGENTS_MD_HEADER + "\n\n" + persona

    if output.exists() and not assume_yes:
        if not ui.confirm(f"{output} already exists. Replace it?", default=False):
            output = output.with_name(output.stem + "-pixiedust" + output.suffix)
            ui.hint(f"Keeping the old one. Writing to {output} instead.")

    try:
        output.write_text(body, encoding="utf-8")
    except OSError as exc:
        ui.dead_end(
            f"Could not write {output}: {exc}",
            [
                "Run it again from a folder you can write to, for example your "
                "home folder or Desktop.",
                "Or choose the file yourself:  pixieduster clone --output "
                "~/Desktop/persona.md",
            ],
        )
        raise typer.Exit(code=1)

    ui.certificate(persona, target_name)
    ui.success(f"Persona written to {output}")
    ui.next_steps(str(output), is_agent_file, target_name)

# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------

@app.command()
def chat(
    persona: Path = typer.Option(None, "--persona", "-p", help="Persona file (default: persona.md or AGENTS.md)."),
    model: str = typer.Option(None, "--model"),
    api_key: str = typer.Option(None, "--api-key", show_default=False),
    plain: bool = typer.Option(False, "--plain"),
) -> None:
    """Chat with a generated persona to hear how it sounds."""
    _apply_plain(plain)
    persona = _default_persona(persona)
    if not persona.exists():
        ui.error(f"No persona file at {persona}")
        ui.hint("Generate one first:  pixieduster clone")
        raise typer.Exit(code=2)

    sys_prompt = persona.read_text(encoding="utf-8")
    model = model or config.load_settings().get("model") or core.DEFAULT_MODEL
    key, base_url = _credentials(api_key)
    model = _verify_model(key, model, base_url)

    if not ui.is_plain():
        ui.banner()
    ui.hint(f"Chatting as {persona}. Ctrl-D or 'exit' to leave.")

    history: list[dict[str, str]] = []
    while True:
        try:
            user_input = ui.ask_text("you").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", ":q"}:
            break

        try:
            # dust() owns a Live region; safe here because nothing else does.
            with ui.dust(height=3):
                reply = core.chat_gemini(key, model, sys_prompt, history, user_input,
                                         base_url=base_url)
        except core.GeminiError as exc:
            ui.error(str(exc))
            continue

        ui.console.print(reply if ui.is_plain() else f"[#d1c4e9]{reply}[/]")
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

@app.command()
def diff(
    draft: Path = typer.Argument(..., help="Draft to score against the persona."),
    persona: Path = typer.Option(None, "--persona", "-p"),
    model: str = typer.Option(None, "--model"),
    api_key: str = typer.Option(None, "--api-key", show_default=False),
    plain: bool = typer.Option(False, "--plain"),
) -> None:
    """Score a draft against a persona and list where the voice drifts."""
    _apply_plain(plain)
    persona = _default_persona(persona)
    for path, label in ((draft, "draft"), (persona, "persona")):
        if not path.exists():
            ui.error(f"No {label} file at {path}")
            raise typer.Exit(code=2)

    model = model or config.load_settings().get("model") or core.DEFAULT_MODEL
    key, base_url = _credentials(api_key)
    model = _verify_model(key, model, base_url)

    instruction = prompts.DIFF_INSTRUCTION.format(
        persona=persona.read_text(encoding="utf-8"),
        draft=draft.read_text(encoding="utf-8"),
    )
    try:
        with ui.stages("Comparing voices") as stage:
            stage("Reading the draft", icon="magnifier")
            stage("Scoring against the persona", icon="chart")
            result = core.call_gemini(key, model, instruction, base_url=base_url)
    except core.GeminiError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1)

    ui.console.print(result)


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------

@config_app.command("set-key")
def config_set_key(
    key: str = typer.Argument(None, help="The key. Omit to be prompted without echo."),
) -> None:
    """Store a Gemini API key at ~/.config/pixieduster/config.toml (mode 0600)."""
    value = key or ui.ask_text("Gemini API key", password=True).strip()
    if not value:
        ui.error("No key entered.")
        raise typer.Exit(code=2)
    path = config.save_api_key(value)
    ui.success(f"Key saved to {path} (permissions 0600).")
    if key:
        ui.hint("Passing the key as an argument leaves it in your shell history. Consider clearing it.")


@config_app.command("show")
def config_show() -> None:
    """Show which key is active and where it came from. Never prints the key."""
    source = config.key_source()
    resolved = config.resolve_api_key()
    ui.console.print(f"config file : {config.CONFIG_PATH}")
    ui.console.print(f"key source  : {source}")
    ui.console.print(f"key         : {config.mask_key(resolved)}")
    settings = config.load_settings()
    ui.console.print(f"model       : {settings.get('model') or core.DEFAULT_MODEL}")


@config_app.command("models")
def config_models(
    api_key: str = typer.Option(None, "--api-key", show_default=False),
) -> None:
    """List the Gemini models your key can reach."""
    key, base_url = _credentials(api_key)
    try:
        for m in core.list_models(key, base_url=base_url):
            marker = "  <- default" if m == core.DEFAULT_MODEL else ""
            ui.console.print(f"  {m}{marker}")
    except core.GeminiError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1)


@config_app.command("set-model")
def config_set_model(model: str = typer.Argument(..., help="Model id to use by default.")) -> None:
    """Set the default Gemini model."""
    config.save_setting("model", model)
    config.save_setting("verified_model", "")
    ui.success(f"Default model set to {model}.")


@app.command()
def login(
    token: str = typer.Option(None, "--token", help="Paste a token instead of being prompted.", show_default=False),
    plain: bool = typer.Option(False, "--plain"),
) -> None:
    """Sign in with Hugging Face. Free, and you only do it once."""
    _apply_plain(plain)
    _do_login(token)


@app.command()
def logout(
    plain: bool = typer.Option(False, "--plain"),
) -> None:
    """Forget the stored Hugging Face token."""
    _apply_plain(plain)
    data = config.load_config()
    auth = data.get("auth") or {}
    if auth.pop("hf_token", None) is None:
        ui.hint("No stored token to remove.")
    else:
        data["auth"] = auth
        config._write_config(data)
        ui.success("Signed out.")
    if hosted.token_source() != "none":
        ui.hint(
            f"A token is still available from: {hosted.token_source()}. "
            "PixieDuster will keep using it."
        )


@app.command()
def status(
    plain: bool = typer.Option(False, "--plain"),
) -> None:
    """Show how you are authenticated and how much free quota is left."""
    _apply_plain(plain)
    token = hosted.resolve_token()
    own = config.resolve_api_key()

    if token:
        ui.console.print(f"hosted token : from {hosted.token_source()}")
        try:
            ui.success(hosted.quota_message(hosted.check(token)))
        except hosted.HostedError as exc:
            ui.error(str(exc))
    else:
        ui.console.print("hosted token : (not signed in)")

    ui.console.print(f"your own key : {config.mask_key(own)}" if own else "your own key : (none)")
    mode = config.load_settings().get("mode") or ("hosted" if token else "byok")
    ui.console.print(f"mode         : {mode}")
    if not token and not own:
        ui.hint("Run  pixieduster login  to start using it for free.")


@app.command()
def version() -> None:
    """Print the version."""
    ui.console.print(f"pixieduster {__version__}")


if __name__ == "__main__":
    app()
