"""SKILL.md and agent templates.

The same text is rendered twice: once into the repo's ``skills/`` and
``agents/`` directories for plugin installs (commands run via ``PYTHONPATH``),
and once by ``shuntkit install`` into ``~/.claude`` (commands run via the
``shuntkit`` console script). A test keeps the repo copies in sync.
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

The answer is bullets. Backticked quotes that shuntkit could locate exactly
once in the files carry a verified `(file:line)` suffix; you can rely on those.
Anything without a suffix is unverified: confirm with a targeted `Read`
(offset/limit) before editing.

shuntkit refuses files that look like secrets (`.env`, keys, credentials).
Read those directly if you must.
"""


def code_writer_skill(command: str) -> str:
    return f"""---
name: code-writer
description: "Delegate boilerplate code generation to a cheaper Claude model via shuntkit. Use for tests, config, docstrings, type stubs, or any generation where >80% is predictable from a reference file."
---

```bash
# Generate and write directly to the target file
{command} write --spec "<what to generate>" \\
  --reference <file-whose-style-to-match> \\
  --context <source-file-the-output-is-about> [<more>] \\
  --target <output-path>

# Output to stdout instead (omit --target)
{command} write --spec "<what to generate>" --reference <ref> --context <src>
```

`--reference` is required: it is the file whose conventions (imports, naming,
test style) the output must match.

`--context` is the code the output is *about*, for example the module under
test. Without it the worker only sees a style example and will invent names,
signatures and expected values. Always pass it when the output must be correct
against existing code.

Each call is independent. To build on what was just generated, pass that file
as the `--reference` for the next call.

Review the output and make surgical edits for the small share that needs
frontier-model judgment.
"""


def bulk_reader_agent() -> str:
    return """---
name: bulk-reader
description: "Reads large files or many files and answers a question about them, keeping the corpus out of the caller's context. Use for files over 350 lines or questions spanning 3+ files. Returns structured bullets with file:line citations."
model: haiku
tools: Read, Glob, Grep
disallowedTools: Agent, Bash, Write, Edit, NotebookEdit, WebFetch, WebSearch
maxTurns: 12
---

You are a precise code analyst working as a delegated reader. The caller has
handed you file paths and a question because loading the files into its own
context would be expensive.

- Read every file you are asked about in full. Use Grep and Glob if the
  question needs you to find more.
- Answer the question concisely as structured bullets. No preamble.
- Every claim about specific code gets a citation: quote a short distinctive
  fragment in backticks and give `path:line` (the Read tool shows line numbers).
- Quote identifiers exactly as written. Do not paraphrase code.
- If the files do not contain the answer, say so plainly.
- Never modify anything. Never spawn other agents.
"""


SKILLS = {
    "bulk-reader": bulk_reader_skill,
    "code-writer": code_writer_skill,
}

AGENTS = {
    "bulk-reader": bulk_reader_agent,
}
