# Security

## What shuntkit does with your files

`shuntkit read` and `shuntkit write` send the **full contents** of the files
you name to a Claude model, through either the Claude Code CLI or the
Anthropic API. This is the whole point of the tool, but it means:

- Files go to Anthropic under whatever data terms apply to your Claude Code
  plan or API account. If a file must not leave your machine, do not pass it
  to shuntkit. The hooks only *suggest* delegation; Claude can still read a
  file with `offset`/`limit`.
- A **secret guard** refuses files whose name, parent directory or content
  looks like a credential (`.env*`, `*.pem`, `id_rsa*`, `credentials*`,
  `.ssh/`, PEM private key blocks, and more; see `src/shuntkit/secrets.py`).
  It is a guard rail against accidents, not a scanner. It will not notice an
  API key pasted into `settings.py`. `SHUNTKIT_SECRET_GUARD=off` disables it.
- Nothing is sent by the hooks themselves. They only count lines locally and
  keep a small per-session tally of slice reads.
- State under `~/.local/state/shuntkit/` (`usage.jsonl`, `slices/`,
  `sanctions.json`) contains file paths, line counts and token counts, never
  file contents.
- The worker runs with no tools, in an empty scratch directory, with the
  parent's settings, `CLAUDE.md` and MCP servers disabled. It cannot act on
  your machine; it can only answer.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability
reporting on this repository ("Security" tab, "Report a vulnerability").
You will get an acknowledgement within a week.
