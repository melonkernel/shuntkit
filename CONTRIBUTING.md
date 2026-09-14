# Contributing

Thanks for taking the time. This is a small project and small, focused pull
requests are the easiest to review.

## Setup

```bash
git clone https://github.com/melonkernel/shuntkit
cd shuntkit
uv sync
uv run pytest
```

Try it against your own Claude Code without installing from PyPI:

```bash
uv run shuntkit install     # registers hooks pointing at the 'shuntkit' on your PATH
uv run shuntkit doctor --probe
```

or add the checkout as a local plugin: `claude --plugin-dir .`.

## Ground rules

- **Hooks must be fast and must never break a session.** They run before every
  `Read` and `Bash` call. Standard library only, no network, and any failure
  path returns "allow".
- **Never blocked, only redirected.** A block message must always tell Claude
  what to run instead, including the exact command.
- **Tests for hook behaviour.** `tests/test_read_hook.py` and
  `tests/test_bash_hook.py` mirror upstream's eval cases. Add a case for every
  new heuristic. If you diverge from upstream on purpose, say so in the test
  docstring and in the README table.
- **Skill and agent text lives in one place.** Edit `src/shuntkit/skills.py`,
  run `scripts/render-skills.py`, commit the rendered `skills/` and `agents/`
  files with it.
- **Read `docs/design.md` before changing hook semantics.** It states what
  each rule is for and what it deliberately does not cover. Update it in the
  same PR.
- **Keep the transport interface small.** A transport is `invoke(system,
  message) -> Answer` plus `check() -> list[str]`. New transports are welcome
  if they call a Claude model; this project deliberately stays Claude-only.

## Upstream

We track `plugins/shunt` in spotify/portal-ai-plugins. See
[docs/upstream.md](docs/upstream.md) for the review loop. If your change ports
an upstream change, link the upstream commit in the PR.

## Releasing (maintainers)

1. Update `__version__` in `src/shuntkit/__init__.py`, and the `version`
   fields in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`
   (a test enforces they match).
2. Move `Unreleased` in `CHANGELOG.md` to the new version with today's date.
3. Commit, tag `vX.Y.Z`, push the tag. The release workflow runs tests, builds,
   publishes to PyPI via trusted publishing, and creates a GitHub release.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
