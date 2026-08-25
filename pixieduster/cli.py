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

app = typer.Typer(
    name="pixieduster",
    help="Build an AI persona prompt: invent one, or clone a real writing voice.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
)
config_app = typer.Typer(help="Manage the stored API key and settings.", no_args_is_help=True)
app.add_typer(config_app, name="config")


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def _apply_plain(plain: bool) -> None:
    if plain:
        ui.PLAIN = True


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
    """Scan outbound text, show the cost estimate, and confirm before sending."""
    findings = safety.scan(samples)

    tokens_in = sum(s.tokens or safety.estimate_tokens(s.text) for s in samples)
    est = safety.estimate_cost(tokens_in, 2000, model)
    cost = f"~${est:.4f}" if est is not None else "unknown for this model"

    ui.samples_table(samples)
    ui.hint(f"About {tokens_in:,} tokens will be sent to Google. Estimated cost: {cost}.")

    if findings:
        high = [f for f in findings if f.severity == "high"]
        ui.error(
            f"{len(findings)} possible secret(s) found in the text that would be sent"
            + (f" — {len(high)} high severity." if high else ".")
        )
        ui.findings_table(findings)

        if scrub:
            ui.hint("--scrub is on: these matches will be replaced with <REDACTED:rule> before sending.")
            samples = [
                Sample(
                    kind=s.kind,
                    origin=s.origin,
                    text=safety.redact(s.text),
                    author=s.author,
                    tokens=s.tokens,
                )
                for s in samples
            ]
        elif not assume_yes:
            ui.hint("Re-run with --scrub to redact them, or --dry-run to inspect the payload.")
            if not ui.confirm("Send anyway?", default=False):
                raise typer.Exit(code=1)

    if not assume_yes and not findings:
        if not ui.confirm("Send this to the Gemini API?", default=True):
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
    if ui.is_plain() or not sys.stdin.isatty():
        ui.error("Not signed in, and no Gemini API key found.")
        ui.hint(
            "Either:  pixieduster login          (free, uses your Hugging Face account)\n"
            "or:      pixieduster config set-key  (use your own Gemini key)"
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
    humor: int = typer.Option(None, "--humor", min=0, max=10, help="Humor level 0-10; skips the prompt."),
    questions: int = typer.Option(3, "--questions", "-q", min=0, max=8, help="Profiling questions to ask."),
    max_chars: int = typer.Option(180_000, "--max-chars", help="Cap on mined characters."),
    no_pr: bool = typer.Option(False, "--no-pr", help="Skip GitHub PR mining."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be sent, then exit."),
    scrub: bool = typer.Option(False, "--scrub", help="Redact detected secrets instead of asking."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts."),
    plain: bool = typer.Option(False, "--plain", help="No colour or animation."),
) -> None:
    """Build a persona prompt: from a description, from writing samples, or from a repo."""
    _apply_plain(plain)
    model = model or config.load_settings().get("model") or core.DEFAULT_MODEL

    from_ = list(from_ or [])

    if not ui.is_plain():
        ui.banner()

    # No source given. Most people mean "a folder of my writing", so ask rather
    # than quietly mining whatever repo they happen to be standing in.
    if not describe and not from_ and repo is None:
        if not sys.stdin.isatty() or assume_yes:
            ui.error("Nothing to work from.")
            ui.hint(
                "Point it at your writing:\n"
                "  --from ~/my-writing        a folder of notes, screenshots, emails\n"
                "  --describe \"a friendly desktop robot with great humor\"\n"
                "  --repo .                   advanced: read a git repo"
            )
            raise typer.Exit(code=2)

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
            ui.hint(
                "Anything with your voice in it works: photos of handwritten notes, "
                "screenshots of texts, saved emails, old essays."
            )
            entered = ui.ask_text("Folder (or file) to read").strip()
            if not entered:
                ui.error("No path given.")
                raise typer.Exit(code=2)
            from_ = [Path(entered).expanduser()]
        elif picked.startswith("Nothing"):
            describe = ui.ask_text(
                "Describe the persona", default="a friendly desktop robot with great humor"
            ).strip()
        else:
            repo = Path.cwd()

    use_repo = repo is not None and not from_

    samples: list[Sample] = []
    files: list[tuple[str, str, bytes]] = []
    binary_notes: list[str] = []
    target_name = name

    # --- gather evidence, if there is any ---------------------------------
    if from_:
        try:
            samples, files = sources.load(from_)
        except sources.SourceError as exc:
            ui.error(str(exc))
            raise typer.Exit(code=2)
        binary_notes = sources.describe(files)
        ui.hint(
            f"Read {len(samples)} text file(s) and {len(files)} image(s)/document(s). "
            "Handwriting and screenshots are read by the model directly."
        )

    elif use_repo:
        repo_path = _resolve_repo(repo)
        authors = mining.list_authors(repo_path)

        if author is None and authors and not assume_yes and not ui.is_plain() and sys.stdin.isatty():
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
        if describe and sys.stdin.isatty() and not assume_yes:
            target_name = ui.ask_text("What should this persona be called?",
                                      default="the persona").strip()
        else:
            target_name = "the persona"

    for sample in samples:
        if not sample.tokens:
            sample.tokens = safety.estimate_tokens(sample.text)

    if not samples and not files and not describe:
        ui.error("Found no usable writing samples.")
        ui.hint(
            "Give it something to work from:\n"
            "  --from ~/my-writing        notes, screenshots, photos, emails, essays\n"
            "  --describe \"a friendly desktop robot with great humor\"\n"
            "  --repo /path/to/a/git/repo"
        )
        raise typer.Exit(code=1)

    # --- dry run exits here ------------------------------------------------
    if dry_run:
        report = safety.dry_run_report(samples, safety.scan(samples), model)
        if describe:
            report += f"\n\nPERSONA DESCRIPTION (sent as text)\n{'-' * 60}\n  {describe}\n"
        if binary_notes:
            report += ("\n\nDOCUMENTS AND IMAGES\n" + "-" * 60 + "\n"
                       + "\n".join(f"  {line}" for line in binary_notes) + "\n")
        print(report)
        raise typer.Exit(code=0)

    key, base_url = _credentials(api_key, prefer_own=byok)
    model = _verify_model(key, model, base_url)

    if samples:
        samples = _safety_gate(samples, model, assume_yes=assume_yes, scrub=scrub)
    elif files and not assume_yes:
        for line in binary_notes:
            ui.hint(line)
        if not ui.confirm("Send these to the Gemini API?", default=True):
            raise typer.Exit(code=1)

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
            ui.error(str(exc))
            raise typer.Exit(code=1)

        if qs and sys.stdin.isatty():
            ui.hint(f"To calibrate '{target_name}', pick the most accurate answer:")
            for i, q in enumerate(qs, 1):
                chosen = ui.ask_choice(q.question, q.options, i, len(qs))
                answers.append((q.question, chosen))

    if humor is None:
        humor = (
            ui.ask_slider(
                "Humor Level (Benign Violation Theory)", 0, 10, 5,
                "How often the persona attempts humor by violating a norm while staying benign.",
            )
            if sys.stdin.isatty() and not ui.is_plain()
            else 5
        )

    # --- generate ----------------------------------------------------------
    try:
        with ui.stages("Distilling the persona") as stage:
            stage("Evaluating Big Five personality traits", icon="brain")
            stage("Analyzing LIWC syntax and pronoun orientation", icon="chart")
            stage("Assessing cognitive style", icon="puzzle")
            stage("Mapping sociolinguistics", icon="comments")
            persona = core.generate_persona(
                key, model, target_name, samples, answers, humor,
                description=describe, files=files or None, base_url=base_url,
            )
    except core.GeminiError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1)

    # --- write -------------------------------------------------------------
    if output is None:
        output = Path("AGENTS.md") if (use_repo and not describe) else Path("persona.md")

    # Filenames a coding agent picks up on its own. Same persona either way --
    # these just get a preamble telling the agent it governs prose, not code.
    body = persona
    if output.name.lower() in AGENT_FILENAMES:
        body = prompts.AGENTS_MD_HEADER + "\n\n" + persona

    if output.exists() and not assume_yes:
        if not ui.confirm(f"{output} exists. Overwrite?", default=False):
            output = output.with_name(output.stem + "-pixiedust" + output.suffix)
            ui.hint(f"Writing to {output} instead.")

    output.write_text(body, encoding="utf-8")

    ui.certificate(persona, target_name)
    ui.success(f"Persona written to {output}")
    if output.name.lower() in AGENT_FILENAMES:
        ui.hint(f"{output.name} is read automatically by that tool. Nothing else to do.")
    else:
        ui.hint(
            f"Paste {output.name} into any AI as its system prompt.\n"
            "Or name it AGENTS.md / CLAUDE.md / GEMINI.md and the tool loads it itself."
        )
    ui.hint(f"Try it:  pixieduster chat --persona {output}")


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
