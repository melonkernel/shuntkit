#!/usr/bin/env bash
# Show what changed in upstream's plugins/shunt since we last reviewed it.
#
#   scripts/sync-upstream.sh            # print diff summary + full diff
#   scripts/sync-upstream.sh --update   # move upstream/UPSTREAM.lock to upstream/main
#   scripts/sync-upstream.sh --check    # exit 1 if there are unreviewed changes (for CI)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$REPO_ROOT/upstream/UPSTREAM.lock"
UPSTREAM_URL="https://github.com/spotify/portal-ai-plugins.git"
UPSTREAM_PATH="plugins/shunt"

cd "$REPO_ROOT"

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "$UPSTREAM_URL"
fi
git fetch --quiet upstream main

locked_sha="$(head -n1 "$LOCK" | tr -d '[:space:]')"
latest_sha="$(git rev-parse upstream/main)"

if [ "$locked_sha" = "$latest_sha" ]; then
  echo "Up to date with upstream ($latest_sha)."
  exit 0
fi

changed="$(git diff --stat "$locked_sha".."$latest_sha" -- "$UPSTREAM_PATH")"
if [ -z "$changed" ]; then
  echo "Upstream moved to $latest_sha but $UPSTREAM_PATH is unchanged."
  if [ "${1:-}" = "--update" ]; then
    printf '%s\n%s\n' "$latest_sha" "$(date -u +%Y-%m-%d)" > "$LOCK"
    echo "Lock updated."
  fi
  exit 0
fi

case "${1:-}" in
  --check)
    echo "Unreviewed upstream changes in $UPSTREAM_PATH ($locked_sha..$latest_sha):"
    echo "$changed"
    exit 1
    ;;
  --update)
    printf '%s\n%s\n' "$latest_sha" "$(date -u +%Y-%m-%d)" > "$LOCK"
    echo "Lock updated to $latest_sha. Remember to note the review in CHANGELOG.md."
    ;;
  *)
    echo "Upstream $UPSTREAM_PATH changed ($locked_sha..$latest_sha):"
    echo
    echo "$changed"
    echo
    git log --oneline "$locked_sha".."$latest_sha" -- "$UPSTREAM_PATH"
    echo
    git diff "$locked_sha".."$latest_sha" -- "$UPSTREAM_PATH"
    ;;
esac
