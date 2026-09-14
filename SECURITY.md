# Security

## What shuntkit does with your files

`shuntkit read` and `shuntkit write` send the **full contents** of the files
you name to a Claude model, through either the Claude Code CLI or the
Anthropic API. This is the whole point of the tool, but it means:

- Files go to Anthropic under whatever data terms apply to your Claude Code
  plan or API account. If a file must not leave your machine, do not pass it
  to shuntkit. The hooks only *suggest* delegation; Claude can still read a
  file with `offset`/`limit`.
- Nothing is sent by the hooks themselves. They only count lines locally.
- Usage records in `~/.local/state/shuntkit/usage.jsonl` contain file paths
  and token counts, never file contents.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability
reporting on this repository ("Security" tab, "Report a vulnerability").
You will get an acknowledgement within a week.
