# Brief: make PixieDuster genuinely easy, and hard to break

Two agents work on this at once. **Read this whole file first.** It is the
contract between you; the file ownership table is not negotiable.

## What the product is

You give it evidence of how someone writes, or a sentence describing a
character. It measures that against four empirical rubrics plus humor
(Benign Violation Theory) and writes **one file**: a specification of that
voice, which any AI can then write in.

Three ways in:
- `--from <folder>` — **the main one.** A folder of the person's writing:
  notes, screenshots of texts, photos of handwriting, saved emails, essays,
  PDFs. Not a code repo. This is how normal people use it.
- `--describe "a friendly desktop robot with great humor"` — invent a character.
- `--repo <path>` — advanced; mines commit bodies, README, docstrings.

Output: `persona.md` by default, or `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`,
which those tools read automatically.

## The state of things

- 446 tests, all offline, `.venv-cli/bin/python -m pytest tests/ -q`
- Deployed: a Cloudflare Worker (`worker/`) meters a shared Gemini key per
  Hugging Face account (5/day) and per anonymous browser visitor (2/day), under
  a global ceiling. Users need no key of their own.
- The browser app (`web/app.py`, stlite/Pyodide) and the CLI share prompts.
- `pixieduster/`: `cli.py` `core.py` `sources.py` `mining.py` `safety.py`
  `ui.py` `config.py` `hosted.py` `prompts.py` `types.py`

## The two problems to solve

**1. It is not easy enough.** The owner's words: "it just all has to be ultra
user friendly. If you can make it easier, do." Assume a user who is not a
developer, has never used a terminal flag, and has a folder of their own
writing they care about.

**2. It sends everything it finds.** `sources.load()` takes every supported
file in a folder, in `sorted()` order, capped at 60 files and 8 MB each. Point
it at `~/Documents` and it will happily send a tax return, a rental agreement
and a shopping list as "writing samples". The owner asked: "even parse things
in the folder so as to analyze only what is relevant?" That is the ask.

## File ownership - do NOT write outside your row

| Agent | Owns |
|---|---|
| **architect** | `pixieduster/relevance.py` (new), `pixieduster/sources.py`, `pixieduster/core.py`, `tests/test_relevance.py`, `tests/test_sources.py` |
| **ux** | `pixieduster/cli.py`, `pixieduster/ui.py`, `tests/test_ui.py`, `tests/test_cli_flow.py` (new) |
| neither | `web/`, `worker/`, `prompts.py`, `safety.py`, `mining.py`, `config.py`, `hosted.py`, `docs/`, `scripts/`, `README*` |

Both of you may READ anything. Only write your own row.

## The seam between you

**architect** defines and implements this. **ux** calls it and must not
reimplement it:

```python
# pixieduster/relevance.py
@dataclass
class Scored:
    sample: Sample | None          # None for a binary file
    file: tuple[str, str, bytes] | None
    origin: str
    score: float                   # 0.0 - 1.0, higher = more like personal writing
    reason: str                    # one short human sentence, shown to the user
    verdict: str                   # "keep" | "unsure" | "drop"

def triage(samples, files, *, budget_chars=180_000) -> tuple[list[Scored], list[Scored]]:
    """Return (kept, rejected), best first. Pure, offline, no network."""
```

`ux` shows the user what was kept and dropped and lets them override.
Do not change this signature without telling the other agent through me.

## Rules for both

1. **Offline tests only.** Mock `requests`. No network, no API key.
2. **American spellings. No em dashes** anywhere, in code, comments or output.
3. Every public function gets a type hint and a docstring.
4. Run `.venv-cli/bin/python -m pytest tests/ -q` before you finish and report
   the true number. Do not report a number you did not see.
5. Do not `git commit`. Do not touch `.env`, `.dev.vars`, or any credential.
6. If something in this brief is wrong or impossible, implement what you can
   and say so plainly in your report. Do not paper over it.
7. Prefer deleting a confusing thing over adding an explanation for it.
