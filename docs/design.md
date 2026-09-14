# How shuntkit works

This document explains each mechanism, why it exists, and where it stops
working. Read it before changing hook behaviour.

## The problem being solved

Claude Code reads files by putting their full text into the model's context.
For a frontier model that is the most expensive thing a coding session does,
and most of those tokens are never looked at again. Spotify's shunt plugin
showed that intercepting large reads and handing them to a cheap worker model
cuts bulk-read token usage by around 90% in their tests. shuntkit does the
same without Spotify's backend.

Two constraints shape everything below:

1. **Hooks must never break a session.** They run before every Read and Bash
   call. Any exception, any missing state, any malformed input must result in
   "allow". A hook that crashes is worse than no hook.
2. **Blocks must always say what to do instead.** Claude cannot ask a human.
   Every deny message contains the exact command or tool call to use.

## 1. Read hook

`shuntkit hook read` receives the PreToolUse JSON on stdin and decides:

```
file missing / not a regular file / image, PDF, notebook  -> allow
no offset and no limit:
    lines <= min_lines                                    -> allow
    lines >  min_lines                                    -> DENY (delegate)
offset and/or limit present:
    lines <= min_lines                                    -> allow
    slice the call would return > min_lines               -> DENY (delegate)
    otherwise                                             -> charge slice budget (see 3)
```

"Slice the call would return" is `min(limit or 2000, lines - offset + 1)`.
The Read tool returns up to 2000 lines when `limit` is omitted, so `offset`
alone on a 1200-line file returns 1101 lines. Upstream allowed this and
labelled it a known bypass in its own evals. shuntkit treats it as the
whole-file read it is.

Line counting is `wc -l` semantics on bytes, 1 MB at a time. A 500 MB log
counts in well under a second.

## 2. Bash hook

`shuntkit hook bash` handles the ways Claude dumps files through the shell.

```
command contains | or >                                   -> allow (output goes elsewhere)
shlex fails (unbalanced quotes)                           -> allow
first simple command (before && ; ||), after env/sudo:
    not in {cat less more bat batcat head tail}           -> allow
    head/tail with bounded count <= min_lines             -> charge slice budget per large file
    head/tail unbounded (-n +5, -c huge, 10k)             -> treat as full read
    full read: sum of lines over all file args
        <= min_lines                                      -> allow
        >  min_lines                                      -> DENY (delegate)
```

Only the first command in a chain is inspected. `echo x && cat big.txt` gets
through. This matches upstream and is a deliberate trade against parsing
every shell construct; the Read tool is what Claude reaches for by default.

## 3. Slice budget

Blocking the whole-file read is pointless if Claude can read the file in
four `limit: 300` pieces. The budget closes that.

- Every allowed slice of a **large** file (over `min_lines`) is charged to a
  counter keyed by `(session_id, resolved path)`.
- Default budget is `2 x min_lines` (700 lines). `SHUNTKIT_SLICE_BUDGET_LINES`
  overrides it; `0` disables.
- When the counter exceeds the budget, further slices are denied with a
  message that names the file, the tally, the budget, and the delegation
  command.
- A **sanction** lifts the restriction. `shuntkit read` sanctions every file it
  delegated, and a whole-file Read by the bulk-reader subagent sanctions the
  file too. A sanction lasts `SHUNTKIT_SANCTION_TTL_SECONDS` (4 hours). This
  keeps the natural workflow, delegate first, then take targeted reads for
  editing, free of interruptions.

State lives in `~/.local/state/shuntkit/slices/<session>.json` and
`sanctions.json`. Writes are atomic (temp file plus rename). Two hooks racing
on the same session can lose one increment; the counter is a deterrent, not
an audit log, so that is accepted. Session files are pruned after 7 days once
there are more than 200 of them. Any I/O failure means "allow".

Small files are never charged. Claude reading a 200-line file in ten slices
is wasteful but harmless.

## 4. Delegation, CLI mode (default)

`shuntkit read --question Q --paths F...` does, in order:

1. Existence, duplicate and **secret guard** checks (section 6).
2. Builds one message: each file in `<file path="...">` tags, then the
   question. Refuses over `SHUNTKIT_MAX_PAYLOAD_BYTES` (600 kB, roughly 150k
   tokens, inside Haiku's 200k window with room for the answer).
3. Calls the transport (section 5).
4. Attaches **citations** (section 7).
5. Records a sanction for the files and appends one line to `usage.jsonl`.
6. Prints the answer to stdout and a one-line usage summary to stderr.

`shuntkit write --spec S --reference R [--context C...]` builds a message
with the spec, the context files, and the reference file, calls the transport
with the writer prompt, strips a single wrapping markdown fence, and writes to
`--target` or stdout.

**Why `--context` exists.** The upstream design gives the worker only a
reference file, the one whose style to copy. If the spec is "tests for
OrderService" and the reference is `test_user_service.py`, the worker never
sees `OrderService` and invents method names and expected values. `--context`
carries the source the output is about. `shuntkit write` warns on stderr
when it is omitted.

## 5. Transports

A transport is `invoke(system_prompt, message) -> Answer` plus
`check() -> list[str]`.

### `claude` (default)

Runs the Claude Code CLI headless:

```
claude -p --model haiku --output-format json --tools "" --strict-mcp-config
       --setting-sources "" --no-session-persistence --max-turns 1
       --system-prompt "<short prompt>"
```

with the message on stdin, in an empty scratch directory, with `CLAUDECODE`
and `CLAUDE_CODE_ENTRYPOINT` removed from the environment.

Each flag earns its place. Measured on Claude Code 2.1.270 with a one-line
prompt:

| Invocation | Input tokens | Cost |
|---|---|---|
| `claude -p --model haiku` in a project dir | 62,549 | $0.127 |
| with the flags above | 399 to 1,367 | $0.002 |

Without `--setting-sources ""` and `--tools ""` the worker loads the parent's
`CLAUDE.md`, skills, and every MCP tool schema before it reads a byte of your
file. `--bare` would be cleaner but only accepts API-key auth, so it breaks
for OAuth and Max-plan users.

Usage and cost come from the CLI's JSON envelope (`usage`, `total_cost_usd`,
`modelUsage`). Latency is 3 to 15 seconds including CLI startup.

### `anthropic`

Calls `client.messages.create` through the official SDK with the same system
prompt and message. Model aliases map to API ids (`haiku` to
`claude-haiku-4-5`). Needs `pip install 'shuntkit[anthropic]'` and API
credentials. Use it to bill worker calls to an API key instead of a Claude
Code plan.

### Why no Gemini, OpenAI-compatible, or Ollama transport

shuntkit assumes you are already a Claude user. A Claude worker needs no new
vendor, key, or data-processing agreement. Other clones of the shunt idea
route to Gemini or local models; if you want that, they exist. The transport
interface is two methods if you want to add one here.

## 6. Secret guard

Delegation sends whole files off the machine under your Claude terms. Some
files should never go by accident. Before any transport call, every path is
checked against:

- name patterns: `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `credentials*`,
  `secrets.*`, `*.tfstate`, `.npmrc`, `.netrc`, service-account JSON, and so on
  (full list in `secrets.py`);
- parent directories: `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.docker`;
- content: the first 8 kB containing a PEM `PRIVATE KEY` block.

A match refuses the whole call and names the files. This is a guard rail. It
does not scan for tokens inside ordinary source files. `SHUNTKIT_SECRET_GUARD=off`
disables it.

The hooks themselves send nothing anywhere. They only count lines locally.

## 7. Citations

The standing complaint about delegated summaries is that they come without
line numbers, so Claude has to read the file anyway before editing.

The reader prompt asks the worker to quote distinctive fragments verbatim in
backticks. After the answer comes back, every backticked span of 12 to 240
characters with at least six alphanumerics is searched for in the delegated
files. A span found **exactly once** gets `(file:line)` appended. Found zero
or several times, it is left alone. Nothing the worker wrote is removed or
altered; only suffixes are added.

The result: `def load_config(path):` (config.py:3) is a line number Claude
can trust without reading the file, because shuntkit computed it, not the
worker. The skill text tells Claude that unsuffixed quotes are unverified.

## 8. Subagent mode

`SHUNTKIT_DELEGATE=subagent` changes what the deny messages say. Instead of
the `shuntkit read` command, they point at the `bulk-reader` subagent
(`shuntkit:bulk-reader` when installed as a plugin). The agent definition
pins `model: haiku`, allows only Read, Glob and Grep, and forbids Agent,
Bash, Write and Edit.

The hook recognises tool calls whose `agent_type` is `bulk-reader` or
`shuntkit:bulk-reader` and lets them through unconditionally. A whole-file
Read by that agent sanctions the file for the parent's slice budget.

Trade-offs against CLI mode:

| | CLI mode | Subagent mode |
|---|---|---|
| Round trip | new `claude` process, 3 to 15 s | in-process, usually faster |
| Worker context | ~400 to 1,400 tokens of scaffolding | full subagent system prompt, several thousand tokens |
| Secret guard, payload cap, citations, usage log | yes | no (the agent reads files itself) |
| Works outside Claude Code | yes | no |

CLI mode is the default because the guards apply. Subagent mode is there
for people who prefer Claude Code's native mechanism.

## 9. Install modes

**pip / uv / pipx.** `shuntkit install` writes two PreToolUse entries into
`~/.claude/settings.json`, the two SKILL.md files into `~/.claude/skills/`,
and the agent into `~/.claude/agents/`. The hook command uses the absolute
path of the `shuntkit` executable, because hooks run in a non-login shell
where `~/.local/bin` is frequently absent from `PATH`. `shuntkit uninstall`
removes exactly those entries and files.

**Plugin.** The repo root is a Claude Code plugin. `hooks/hooks.json` runs
`python3 -m shuntkit` with `PYTHONPATH` set to the plugin's `src/`, so
nothing is pip-installed. The checked-in `skills/` and `agents/` files are
rendered from `src/shuntkit/skills.py`; a test fails when they drift.

## 10. Known limitations

- **Windows is unsupported.** Hook commands assume a POSIX shell and `python3`.
- **Shell parsing is shallow.** Heredocs, subshells, `xargs cat`, `sed -n
  '1,900p'`, `awk`, `python -c "print(open(...).read())"` are not recognised.
  The hooks target what Claude actually does, not what a determined user
  could do.
- **Slice budget races.** Parallel tool calls on the same file can each read
  the counter before either writes it. One increment is lost. Acceptable.
- **`--max-turns 1`** means the worker cannot call tools, by design. It
  answers from the corpus it was given.
- **Citations need distinctive quotes.** A quote like `return None` appears
  many times and is left unannotated. The prompt asks for distinctive
  fragments, but the worker does not always comply.
- **The worker is Haiku.** It finds structure and surface patterns well. It
  misses subtle bugs. Spotify's write-up says the same about their worker.
  Debugging, architecture and safety-critical review stay with the frontier
  model.
- **Savings are per bulk read, not per session.** A session that never
  touches a large file saves nothing and pays a few milliseconds per tool call
  for the hook.
