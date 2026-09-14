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

The worker returns bullets, not line numbers. Verify specific line numbers or
exact values with a targeted `Read` (offset/limit) before using them in edits.
