# shuntkit

**Route bulk file reads and boilerplate generation from Claude Code to a cheaper Claude model.**
A vendor-free port of Spotify's [shunt](https://github.com/spotify/portal-ai-plugins/tree/main/plugins/shunt) plugin: same hooks, same skills, no Portal account required.

[![CI](https://github.com/melonkernel/shuntkit/actions/workflows/ci.yml/badge.svg)](https://github.com/melonkernel/shuntkit/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shuntkit.svg)](https://pypi.org/project/shuntkit/)
[![Python](https://img.shields.io/pypi/pyversions/shuntkit.svg)](https://pypi.org/project/shuntkit/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

---

## Why

Spotify's engineering team [reported a roughly 90% cut in Claude Code token usage](https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90) on bulk-read scenarios by intercepting large file reads with a `PreToolUse` hook and handing them to a cheaper worker model. The worker reads the file in its own disposable context and returns only an answer. The file never enters the expensive model's context window.

Their plugin, `shunt`, is open source, but its transport is hard-wired to Spotify's Portal CLI and AiKA modes. If you are not a Portal customer you cannot use it.

**shuntkit keeps the hooks and skills and replaces the transport.** The default worker is Claude Haiku 4.5, called through the Claude Code CLI you already have logged in. No new vendor, no new API key, no new bill.

## How it works

```
Claude (Opus / Sonnet)                        shuntkit                      Worker (Haiku)
────────────────────────                      ────────                      ──────────────
Read big_file.py  ─────────►  PreToolUse hook: 1200 lines > 350
                  ◄─────────  deny: "use /bulk-reader"
/bulk-reader
  --question "..."
  --paths big_file.py ──────►  shuntkit read  ──── files + question ──────►  claude -p --model haiku
                                                                              (isolated session,
                                                                               no tools, no CLAUDE.md)
                  ◄─────────  answer (bullets)  ◄─── answer only ──────────┘
```

Two hooks fire before every tool call:

| Hook | Intercepts | Lets through |
|------|-----------|--------------|
| `Read` | Whole-file reads over the line threshold (default 350) | Reads with `offset`/`limit`, small files, images, PDFs |
| `Bash` | `cat`, `less`, `more`, `bat` on large files | Pipes, redirects, `head`/`tail` with a bounded count, `grep` |

When a read is blocked, the hook's message tells Claude exactly which command to run instead. Claude does not need to have read the skill description for the redirect to work.

## Install

You need Claude Code installed and logged in. Python 3.10 or newer.

### Option A: pip / uv (recommended)

```bash
uv tool install shuntkit        # or: pipx install shuntkit / pip install shuntkit
shuntkit install                # registers hooks + skills in ~/.claude
shuntkit doctor --probe         # one tiny Haiku call to confirm it works
```

Restart Claude Code. Done.

### Option B: Claude Code plugin

Inside Claude Code:

```
/plugin marketplace add melonkernel/shuntkit
/plugin install shuntkit@shuntkit
```

The plugin form needs only `python3` on your `PATH`; nothing is pip-installed.

### Uninstall

```bash
shuntkit uninstall              # removes exactly what 'install' added
```

## Usage

You mostly do nothing. Claude hits a large file, gets redirected, and calls the skill. The skills are also usable directly:

```bash
# Ask a question across files without loading them into Claude's context
shuntkit read --question "Which functions mutate global state?" --paths src/*.py

# Generate boilerplate that matches an existing file's conventions
shuntkit write --spec "Unit tests for OrderService covering cancel and refund" \
               --reference tests/test_user_service.py \
               --target tests/test_order_service.py
```

Each call prints a one-line summary to stderr:

```
[shuntkit: ~18,400 tokens kept out of context | worker claude-haiku-4-5 used 19,812 in / 310 out | worker cost $0.0214]
```

`shuntkit stats` totals these over time.

## Configuration

Everything is an environment variable. Set them in your shell, or under `"env"` in `~/.claude/settings.json`.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SHUNTKIT_MIN_LINES` | `350` | Files at or under this many lines are read directly. `SHUNT_MIN_LINES` (upstream's name) is honoured too. |
| `SHUNTKIT_MODEL` | `haiku` | Worker model. Any alias or id the Claude CLI accepts (`haiku`, `sonnet`, `claude-haiku-4-5`, ...). |
| `SHUNTKIT_TRANSPORT` | `claude` | `claude` (Claude Code CLI, uses your login) or `anthropic` (Anthropic API via the official SDK). |
| `SHUNTKIT_TIMEOUT_SECONDS` | `180` | Ceiling for one worker call. |
| `SHUNTKIT_MAX_PAYLOAD_BYTES` | `600000` | Refuse requests larger than this (about 150k tokens, under Haiku's 200k window). |
| `SHUNTKIT_CLAUDE_BIN` | `claude` | Path to the Claude CLI if it is not on `PATH`. |
| `SHUNTKIT_DISABLED` | unset | Set to `1` to make both hooks allow everything. |
| `SHUNTKIT_STATE_DIR` | `~/.local/state/shuntkit` | Where `usage.jsonl` is written. |

### Using the Anthropic API instead of the CLI

```bash
pip install 'shuntkit[anthropic]'
export SHUNTKIT_TRANSPORT=anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # or: ant auth login
```

Useful if you want worker calls billed to an API key rather than your Claude Code plan, or if you run shuntkit outside Claude Code.

## What to expect

**Where it helps.** First reads of large files, and questions that span several files. The worker's answer is typically a few hundred tokens; the corpus it replaced is typically tens of thousands.

**Where it does not.** Files under the threshold, edit-heavy work that needs exact line numbers, and anything requiring frontier-model reasoning. Spotify's own write-up notes the worker "found surface-level patterns but missed a subtle thread-safety bug". Debugging, architecture, and safety-critical code stay with Claude.

**Latency.** Each delegation is a separate model call, typically 3 to 15 seconds through the CLI. For one moderately large file a direct read is often faster in wall-clock terms even though it costs more tokens.

**The 90% figure.** It is Spotify's mean over four bulk-read scenarios in a Java monorepo, not a whole-session number. Your mileage depends on how often you hit large files.

### Why the nested CLI call is cheap

A naive `claude -p --model haiku` inherits the parent session's `CLAUDE.md`, skills, and MCP tool schemas. On a one-line test file that came to 62,549 input tokens before the worker read anything. shuntkit passes `--setting-sources ""`, `--tools ""`, `--strict-mcp-config` and a short custom system prompt, which brought the same call down to 1,367 tokens.

## Differences from upstream shunt

| | upstream `shunt` | `shuntkit` |
|---|---|---|
| Transport | Spotify Portal CLI, AiKA modes, Gemini 2.5 Flash | Claude Code CLI (default) or Anthropic API |
| Language | bash + `jq` | Python, standard library only |
| Install | Plugin marketplace | `pip`/`uv`/`pipx` **or** plugin marketplace |
| `head -100 big.txt` | blocked | allowed (bounded slice, same as `Read` with `limit`) |
| `cat a.py b.py` | checks first file | sums all files |
| Hook output | deprecated `decision: block` | current `hookSpecificOutput.permissionDecision` |
| Usage tracking | stderr line | stderr line plus `shuntkit stats` |
| Tests | shell eval runner | `pytest`, upstream eval cases ported one-to-one |

See [docs/upstream.md](docs/upstream.md) for how this repo tracks upstream changes.

## Development

```bash
git clone https://github.com/melonkernel/shuntkit
cd shuntkit
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Editing skill text: change `src/shuntkit/skills.py`, then run `scripts/render-skills.py`. A test fails if the checked-in `skills/` directory is stale.

## Credits

The hook design, skill concepts, prompt shapes, and hook evaluation cases come from the [`shunt` plugin](https://github.com/spotify/portal-ai-plugins/tree/main/plugins/shunt) in `spotify/portal-ai-plugins`, Copyright Spotify AB, Apache-2.0. Read the [engineering post](https://engineering.atspotify.com/2026/9/portal-by-spotify-cut-my-claude-code-token-usage-by-90) that started it. See [NOTICE](NOTICE).

shuntkit is not affiliated with Spotify or Anthropic.

## License

[Apache-2.0](LICENSE)
