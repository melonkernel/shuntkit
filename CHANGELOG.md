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
- `bulk-reader` and `code-writer` skills.
- `claude` transport: runs `claude -p --model haiku` as an isolated worker
  using the user's existing Claude Code login.
- `anthropic` transport: calls the Messages API through the official SDK
  (`pip install shuntkit[anthropic]`).
- `shuntkit install` / `uninstall` for pip installs, and a Claude Code plugin
  manifest for marketplace installs.
- `shuntkit doctor --probe` and `shuntkit stats`.
- Test suite with upstream's hook eval cases ported one-to-one.
- Weekly upstream watch workflow and `scripts/sync-upstream.sh`.

### Changed (relative to upstream)

- `head`/`tail` with a bounded line count are allowed; upstream blocked them.
- `cat a b c` sums line counts across files; upstream checked the first.
- Hook output uses `hookSpecificOutput.permissionDecision`; upstream used the
  deprecated `decision: block`.
- Images, PDFs and notebooks are never blocked.

### Upstream

- Reviewed against `spotify/portal-ai-plugins` commit `3c24ca30` (2026-08-17).
