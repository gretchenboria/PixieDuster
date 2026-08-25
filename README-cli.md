# PixieDuster CLI

Clone a writing voice out of a git repo into an AI persona prompt — from the terminal.

The web app takes uploaded essays. The CLI mines writing that already exists in your
repo: multi-line commit bodies, README and docs prose, docstrings and comment runs,
and PR descriptions. Then it interviews you about the quirks the text can't reveal,
and writes a persona prompt you can drop in as `AGENTS.md` or `CLAUDE.md` so your
coding agent writes in your voice instead of generic LLM house style.

## Install

```bash
uvx pixieduster clone          # no install
# or
uv tool install pixieduster
```

## Use

```bash
pixieduster clone                      # mine the current repo, write AGENTS.md
pixieduster clone --author you@x.com   # clone one person
pixieduster clone --dry-run            # print exactly what would be sent, send nothing
pixieduster chat                       # talk to the persona
pixieduster diff draft.md              # does this draft sound like me?
```

`pxd` is a shorter alias for the same commands.

## Your API key

PixieDuster is bring-your-own-key. It never ships with one, and it never sends your
key anywhere except Google's API.

Setup is a one-time thing:

```bash
pixieduster config set-key      # prompts without echo, stores at 0600
```

The key is resolved in this order, first hit wins:

1. `--api-key` on the command line
2. `GEMINI_API_KEY` in the environment
3. a `.env` file in the current directory
4. `~/.config/pixieduster/config.toml` (directory `0700`, file `0600`)

Get a key at <https://aistudio.google.com/apikey>.

`pixieduster config show` tells you which source is active and prints the key masked
(`AIza…4f21`). The key is never written to a log, never included in an error message,
and never placed in a URL — it goes in the `x-goog-api-key` header, so it can't leak
through a URL echoed in an API error.

## What leaves your machine

Your repo's text goes to Google's Gemini API. That's the whole point of the tool, but
it deserves to be visible, so:

- **`--dry-run`** prints every sample, its origin, its token count, and the secret-scan
  results, then exits without making a network request.
- **Secret scanning** runs before every send — AWS keys, GitHub PATs, PEM blocks,
  connection strings with inline credentials, high-entropy `.env` values and more.
  Findings are shown with the secret already redacted.
- **`--scrub`** replaces detected secrets with `<REDACTED:rule>` instead of asking.
- **A cost estimate** and a confirmation prompt precede the send. `--yes` skips the
  prompt for scripted use.
- **`.gitignore` is respected** — mining runs over `git ls-files`, so ignored files are
  never read. Nothing outside the repo is read, and symlinks out are refused.

Secret detection is best-effort pattern matching, not a guarantee. Review the
`--dry-run` output before pointing this at a sensitive repo.

## Flags worth knowing

| Flag | Effect |
|---|---|
| `--repo, -r` | Repo to mine (default: cwd) |
| `--author, -a` | Clone one person; omit for the repo's collective voice |
| `--output, -o` | Where to write (default `AGENTS.md`) |
| `--humor N` | Humor level 0–10, skips the interactive slider |
| `--questions, -q` | How many profiling questions (0 to skip the interview) |
| `--no-pr` | Skip GitHub PR mining |
| `--plain` | No colour or animation |
| `--yes, -y` | Skip confirmations |

`--plain` is applied automatically when output is piped or `NO_COLOR` is set, so
running this in CI produces readable plain text.

## Requirements

Python 3.11+. `gh` is optional — PR mining is skipped silently without it.
