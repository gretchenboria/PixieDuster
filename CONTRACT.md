# PixieDuster CLI — Module Interface Contract

**This file is authoritative.** Every agent implements to these signatures exactly.
Do not change a signature another module depends on. If a signature is wrong,
implement it as written and note the problem in your final report.

Package root: `/Users/dr.gretchenboria/PersonaPromptGenerator/pixieduster/`
Python: 3.11+ (dev machine runs 3.14). Use `from __future__ import annotations`.

## File ownership (do NOT write outside your own files)

| Module | Owner | Depends on |
|---|---|---|
| `pixieduster/core.py`, `pixieduster/prompts.py`, `pixieduster/config.py` | agent-core | — |
| `pixieduster/mining.py` | agent-mining | (types only) |
| `pixieduster/ui.py` | agent-ui | — |
| `pixieduster/safety.py` | agent-safety | — |
| `pixieduster/cli.py`, `pyproject.toml`, `pixieduster/__init__.py` | integrator | all |

Shared dataclasses live in `pixieduster/types.py`, written by **agent-core** FIRST
(it is a tiny file — write it before anything else so others can read it).

## `pixieduster/types.py` (agent-core writes this first)

```python
@dataclass
class Sample:
    kind: str          # "commit" | "doc" | "comment" | "pr" | "file"
    origin: str        # human-readable source, e.g. "git log a1b2c3d" or "README.md"
    text: str
    author: str | None = None   # email if known
    tokens: int = 0             # filled by safety.estimate_tokens

@dataclass
class Question:
    question: str
    options: list[str]

@dataclass
class Finding:            # a potential secret found in outbound text
    rule: str             # e.g. "aws-access-key"
    origin: str           # which Sample.origin it came from
    line: int
    excerpt: str          # ALREADY REDACTED, safe to print
    severity: str         # "high" | "medium" | "low"
```

## `pixieduster/config.py` (agent-core)

```python
CONFIG_DIR: Path      # ~/.config/pixieduster  (respects XDG_CONFIG_HOME)
CONFIG_PATH: Path     # CONFIG_DIR/config.toml

def resolve_api_key(explicit: str | None = None) -> str | None:
    """Resolution order, first hit wins:
       1. explicit (--api-key flag)
       2. env GEMINI_API_KEY
       3. .env in cwd (python-dotenv, override=False)
       4. CONFIG_PATH -> [auth] gemini_api_key
       Returns None if nothing found. NEVER logs the key."""

def save_api_key(key: str) -> Path:
    """Write to CONFIG_PATH under [auth]. mkdir 0700, file 0600.
       Preserve any other existing keys in the toml. Returns CONFIG_PATH."""

def key_source(explicit: str | None = None) -> str:
    """Which of the 4 sources supplied the key: 'flag'|'env'|'dotenv'|'config'|'none'.
       For display only."""

def load_settings() -> dict:   # [settings] table: model, max_tokens, etc. Empty dict ok.
def save_setting(key: str, value) -> None:
```

## `pixieduster/core.py` (agent-core)

Lift the two API functions out of `app.py` verbatim-in-behavior, then generalize.

```python
DEFAULT_MODEL: str    # read app.py:31 for current value; make it overridable

class GeminiError(RuntimeError):
    """Never include the api key in str(self)."""

def call_gemini(api_key, model, prompt, *, files=None, inline_texts=None,
                schema: dict | None = None, timeout: int = 120) -> str:
    """files: list of (filename, mimetype, bytes) tuples (NOT streamlit objects).
       inline_texts: list of (label, text) appended as text parts.
       schema: if given, sets responseMimeType=application/json + responseSchema.
       Raises GeminiError with the API's message but the key stripped from any URL."""

def chat_gemini(api_key, model, sys_prompt, history, user_input, *, timeout=120) -> str:
    """history: list of {"role": "user"|"assistant", "content": str}"""

def list_models(api_key) -> list[str]:
    """GET .../v1beta/models. Used to validate DEFAULT_MODEL. Returns bare ids."""

def generate_questions(api_key, model, target_name, samples: list[Sample],
                       n: int = 3) -> list[Question]:
    """Uses prompts.QUESTIONS_INSTRUCTION + prompts.QUESTION_SCHEMA.
       Handles BOTH shapes the API returns: a bare JSON array, and
       {"questions":[...]}. Strips ```json fences. Raises GeminiError on
       malformed JSON with a retry-suggesting message."""

def generate_persona(api_key, model, target_name, samples: list[Sample],
                     answers: list[tuple[str, str]], humor_level: int) -> str:
    """answers: list of (question, chosen_option).
       Returns the FULL final document (rubric output already wrapped in
       prompts.ANTI_AI_PROMPT_TEMPLATE)."""
```

## `pixieduster/prompts.py` (agent-core)

Move these out of `app.py` unchanged in substance:
- `ANTI_AI_PROMPT_TEMPLATE` (verbatim from app.py)
- `QUESTIONS_INSTRUCTION` — the profiling-question instruction, `{target_name}`/`{n}` placeholders
- `PERSONA_RUBRIC` — the big LIWC / Big-Five / cognitive-style / sociolinguistics block, verbatim
- `HUMOR_INSTRUCTION` — the Benign Violation Theory block, `{humor_level}` placeholder
- `QUESTION_SCHEMA` — the strict responseSchema dict from app.py
- `AGENTS_MD_HEADER` — new: a short preamble for when output is written as AGENTS.md/CLAUDE.md,
  explaining to a coding agent that this describes the voice to write in (prose/docs/commits),
  NOT the code style.
- `DIFF_INSTRUCTION` — new: given a persona doc + a draft, score how well the draft matches the
  voice and list concrete deviations. Placeholders `{persona}`, `{draft}`.

## `pixieduster/mining.py` (agent-mining)

```python
def is_git_repo(path: Path) -> bool

def list_authors(repo: Path) -> list[tuple[str, str, int]]
    """(email, name, commit_count) sorted desc. From `git log --format=%aE|%aN`."""

def mine_commits(repo, author=None, limit=200, min_chars=40) -> list[Sample]
    """Commit BODIES not just subjects (--format=%B). Skip merge commits,
       revert/bump/dependabot noise, and anything under min_chars. Strip
       trailers (Co-Authored-By, Signed-off-by, Claude-Session, 🤖 Generated with)."""

def mine_docs(repo, limit=20) -> list[Sample]
    """*.md / *.rst / *.txt tracked by git. Prefer README, CONTRIBUTING, docs/**.
       Strip code fences, badge lines, link-reference blocks, and HTML. Skip
       CHANGELOG and LICENSE (not voice)."""

def mine_comments(repo, limit=150) -> list[Sample]
    """Docstrings + comment runs >= 2 lines from tracked source files.
       Python via ast where possible; regex fallback for js/ts/go/rs/java.
       Skip licence headers, shebangs, type stubs, and generated files."""

def mine_prs(repo, author=None, limit=30) -> list[Sample]
    """`gh pr list --json` for PR bodies + review comments. If gh is missing or
       unauthenticated, return [] SILENTLY — never raise, never block."""

def mine_all(repo, author=None, *, budget_chars=180_000) -> list[Sample]
    """Run all four, then balance across kinds so one source can't dominate:
       aim roughly 40% commits / 25% docs / 20% comments / 15% prs, trimming
       longest-first within a kind until under budget_chars."""
```

Every miner must respect `.gitignore` (operate on `git ls-files` output) and must
never read files outside `repo`.

## `pixieduster/safety.py` (agent-safety)

```python
SECRET_RULES: list[tuple[str, str, str]]   # (rule_name, regex, severity)

def scan(samples: list[Sample]) -> list[Finding]
    """Regex-based secret detection over outbound text. Cover at minimum:
       AWS access key/secret, Google API key (AIza...), OpenAI/Anthropic keys,
       GitHub PAT (ghp_/gho_/github_pat_), Slack token, private key PEM blocks,
       JWTs, generic 'password|passwd|secret|token|api[_-]?key' assignments,
       connection strings with inline creds, and .env-style KEY=<40+ chars>.
       Excerpt MUST be redacted before it goes in the Finding."""

def redact(text: str) -> str
    """Replace every SECRET_RULES match with <REDACTED:rule>. Used for --dry-run
       display AND as the last-resort scrub before send when --scrub is on."""

def estimate_tokens(text: str) -> int      # ~len/4, documented as an estimate
def estimate_cost(tokens_in: int, tokens_out: int, model: str) -> float | None
    """Return USD estimate, or None if the model's pricing is unknown.
       Put the price table in one dict at module top with a 'last verified'
       comment. Do NOT invent prices for a model you're unsure about — return None."""

def dry_run_report(samples, findings) -> str
    """Plain-text (no rich markup) description of exactly what would be sent:
       per-sample origin, kind, token count, and every finding. Piped to stdout
       by `--dry-run`."""
```

## `pixieduster/ui.py` (agent-ui)

Rich only — **no Textual**. Must degrade to plain text when
`not sys.stdout.isatty()` or `NO_COLOR` is set or `--plain` sets `ui.PLAIN=True`.

Palette (from the web app): gold `#ffd700`, dim gold `#daa520`, lilac `#e2d1f9`,
mauve text `#d1c4e9`, deep purple bg `#2b1845` → `#0f081c`.

```python
console: rich.console.Console

def banner() -> None
    """Gold→purple gradient ASCII wordmark 'PIXIEDUSTER' + the tagline
       'Your Fairy Prompt-Mother'. Must fit 80 cols."""

@contextmanager
def dust(): ...
    """Live falling-pixie-dust background region, ~10fps, drifting · ✦ * ✧
       glyphs in gold/white. No-op when PLAIN."""

@contextmanager
def stages(title: str): ...
    """Yields a callable stage(text, icon=None). Renders the running step list
       the web app does (Inspecting samples / Formulating questions /
       Evaluating Big Five / LIWC / cognitive style / sociolinguistics),
       ticking each to ✓ as the next starts."""

def ask_choice(question: str, options: list[str], index: int, total: int) -> str
    """Arrow-key single-select. Falls back to numbered input when PLAIN."""

def ask_slider(label: str, lo: int, hi: int, default: int, help: str) -> int
    """Gold ━━━●━━━ bar, left/right arrows, enter to accept."""

def ask_text(label, default=None, password=False) -> str
def confirm(question: str, default: bool = True) -> bool

def certificate(persona_md: str, target_name: str) -> None
    """The Panel version of the web certificate: double gold border, centred
       'CERTIFICATE OF PERSONA' heading, 'Officially cloned for: NAME', the
       rendered markdown body, and the 'Authorized by PixieDuster' footer."""

def samples_table(samples) -> None      # kind / origin / tokens, with totals
def findings_table(findings) -> None    # severity-coloured; red for high
def error(msg: str) -> None
def success(msg: str) -> None
def hint(msg: str) -> None
```

## `pixieduster/cli.py` (integrator, after the rest land)

Typer app, four commands:

- `clone` — mine → safety gate → questions → answers → humor → persona → write file
  Flags: `--repo/-r`, `--author/-a`, `--output/-o` (default `AGENTS.md`),
  `--name/-n` (persona name), `--model`, `--api-key`, `--humor N`,
  `--dry-run`, `--yes/-y`, `--plain`, `--no-pr`, `--max-tokens N`
- `chat` — REPL against a persona file (`--persona`, default `AGENTS.md`)
- `diff <file>` — score a draft against the persona
- `config` — `config set-key`, `config show` (key shown as `AIza…4f21`, never whole)

Entry point: `pixieduster = "pixieduster.cli:app"`, plus alias `pxd`.

## Hard rules for every agent

1. **Never print, log, or write an API key.** Not in errors, not in `--dry-run`,
   not in tracebacks. `str(GeminiError)` must be safe to paste in a GitHub issue.
2. No network calls at import time. No network calls in `mining.py` or `safety.py` at all.
3. Nothing writes to the user's repo except `cli.py` writing the output file.
4. Type-hint everything. Docstrings on public functions.
5. Write your own tests in `tests/test_<yourmodule>.py`. They must pass offline —
   mock `requests.post`, never hit the real API.
6. Run `python -m pytest tests/test_<yourmodule>.py` before you finish and report the result honestly.
7. Do not edit `app.py` unless you are agent-core (which rewires it to import from
   core/prompts while keeping the Streamlit app working).
8. Do not create files outside your ownership row. Do not `git commit`.
