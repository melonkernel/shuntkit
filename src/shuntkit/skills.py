"""SKILL.md templates.

The same text is rendered twice: once into the repo's ``skills/`` directory
for plugin installs (commands run via ``PYTHONPATH``), and once by
``shuntkit install`` into ``~/.claude/skills`` (commands run via the
``shuntkit`` console script). A test keeps the repo copy in sync.
"""

from __future__ import annotations

PLUGIN_COMMAND = 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit'
INSTALLED_COMMAND = "shuntkit"


def bulk_reader_skill(command: str) -> str:
    return f"""---
name: bulk-reader
description: "Delegate bulk file reading to a cheaper Claude model via shuntkit. Use when you need to read files >350 lines, answer questions across 3+ files, or summarize large diffs."
---

```bash
{command} read --question "<question>" --paths <file1> [<file2> ...]
```

Each call is independent. To ask a follow-up, ask again with the same `--paths`.
The files go to the worker model, never into your context, so re-sending them
costs you nothing here.

The worker returns bullets, not line numbers. Verify specific line numbers or
exact values with a targeted `Read` (offset/limit) before using them in edits.
"""


def code_writer_skill(command: str) -> str:
    return f"""---
name: code-writer
description: "Delegate boilerplate code generation to a cheaper Claude model via shuntkit. Use for tests, config, docstrings, type stubs, or any generation where >80% is predictable from a reference file."
---

```bash
# Generate and write directly to the target file
{command} write --spec "<what to generate>" --reference <reference-file> --target <output-path>

# Output to stdout instead (omit --target)
{command} write --spec "<what to generate>" --reference <reference-file>
```

`--reference` is required: without a file whose conventions the output should
match, the worker generates context-free code that fits nothing in the project.

Each call is independent. To build on what was just generated, pass that file
as the `--reference` for the next call.

Review the output and make surgical edits for the small share that needs
frontier-model judgment.
"""


SKILLS = {
    "bulk-reader": bulk_reader_skill,
    "code-writer": code_writer_skill,
}
