# Tracking upstream

shuntkit is a rewrite, not a git fork, of `plugins/shunt` in
[spotify/portal-ai-plugins](https://github.com/spotify/portal-ai-plugins).
The code shares no lines with upstream, so `git merge upstream/main` is not
meaningful. What we track instead are **behavioural changes**: hook
heuristics, threshold defaults, skill wording, prompt text, and eval cases.

## How it works

- `upstream/UPSTREAM.lock` records the upstream commit whose `plugins/shunt`
  directory this repo was last reviewed against.
- `scripts/sync-upstream.sh` fetches upstream and shows the diff of
  `plugins/shunt` between the locked commit and upstream `main`.
- `.github/workflows/upstream-watch.yml` runs that check weekly and opens (or
  updates) an issue titled **"Upstream shunt changed"** with the diff summary
  when there is something new.

## Reviewing an upstream change

1. Run `scripts/sync-upstream.sh` (or read the issue the workflow opened).
2. For each upstream change decide: port it, skip it, or port with a
   deliberate difference. Record deliberate differences in the README's
   "Differences from upstream" table.
3. Port the change with tests. Upstream's `evals/*.json` cases map onto
   `tests/test_read_hook.py` and `tests/test_bash_hook.py`.
4. Run `scripts/sync-upstream.sh --update` to move the lock to the reviewed
   commit, and mention it in `CHANGELOG.md` under "Upstream".
5. Close the issue.

## Local remote

For convenience the repo keeps upstream as a plain git remote so the diff
command works offline once fetched:

```bash
git remote add upstream https://github.com/spotify/portal-ai-plugins.git
git fetch upstream
git diff $(cat upstream/UPSTREAM.lock | head -1)..upstream/main -- plugins/shunt
```

`scripts/sync-upstream.sh` does exactly this and adds the remote if missing.
