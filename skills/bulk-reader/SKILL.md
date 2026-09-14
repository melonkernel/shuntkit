---
name: bulk-reader
description: "Delegate bulk file reading to a cheaper Claude model via shuntkit. Use when you need to read files >350 lines, answer questions across 3+ files, or summarize large diffs."
---

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit read --question "<question>" --paths <file1> [<file2> ...]
```

Each call is independent. To ask a follow-up, ask again with the same `--paths`.
The files go to the worker model, never into your context, so re-sending them
costs you nothing here.

The answer is bullets. Backticked quotes that shuntkit could locate exactly
once in the files carry a verified `(file:line)` suffix; you can rely on those.
Anything without a suffix is unverified: confirm with a targeted `Read`
(offset/limit) before editing.

shuntkit refuses files that look like secrets (`.env`, keys, credentials).
Read those directly if you must.
