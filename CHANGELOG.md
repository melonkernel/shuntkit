# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-09-14

Initial release. A Python port of the `shunt` plugin from
`spotify/portal-ai-plugins` with the Spotify Portal transport replaced.

### Added

- `Read` and `Bash` PreToolUse hooks that block whole-file reads over a line
  threshold and redirect to the bulk-reader skill.
- Per-session slice budget: targeted reads of a large file are tallied and
  blocked once they exceed twice the threshold, until the file has been
  delegated once. Delegation sanctions the file for four hours.
- `bulk-reader` and `code-writer` skills, and a `bulk-reader` Haiku subagent
  as an alternative delegation target (`SHUNTKIT_DELEGATE=subagent`).
- `claude` transport: runs `claude -p --model haiku` as an isolated worker in
  a scratch directory using the user's existing Claude Code login.
- `anthropic` transport: calls the Messages API through the official SDK
  (`pip install shuntkit[anthropic]`).
- Secret guard: refuses to delegate `.env*`, key and credential files,
  anything under `.ssh`/`.aws`-style directories, and files containing a PEM
  private key block.
- Verified citations: backticked quotes in the worker's answer that occur
  exactly once in the delegated files get a locally computed `(file:line)`
  suffix.
- `shuntkit write --context` to give the worker the source the output is
  about, not only a style reference. A warning is printed when it is omitted.
- `shuntkit install` / `uninstall` for pip installs (writes the absolute
  executable path into hooks), and a Claude Code plugin manifest for
  marketplace installs.
- `shuntkit doctor --probe` and `shuntkit stats`.
- Test suite (140 tests) with upstream's hook eval cases ported one-to-one.
- Weekly upstream watch workflow and `scripts/sync-upstream.sh`.
- `docs/design.md` describing every mechanism and its limits.

### Changed (relative to upstream)

- `Read` with `offset` but no `limit` on a large file is blocked when the
  slice it would return exceeds the threshold. Upstream allowed it and
  documented it as a known bypass.
- `head`/`tail` with a bounded line count are allowed; upstream blocked them.
- `cat a b c` sums line counts across files; upstream checked the first.
- Hook output uses `hookSpecificOutput.permissionDecision`; upstream used the
  deprecated `decision: block`.
- Images, PDFs and notebooks are never blocked.

### Upstream

- Reviewed against `spotify/portal-ai-plugins` commit `3c24ca30` (2026-08-17).
