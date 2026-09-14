---
name: code-writer
description: "Delegate boilerplate code generation to a cheaper Claude model via shuntkit. Use for tests, config, docstrings, type stubs, or any generation where >80% is predictable from a reference file."
---

```bash
# Generate and write directly to the target file
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit write --spec "<what to generate>" --reference <reference-file> --target <output-path>

# Output to stdout instead (omit --target)
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit write --spec "<what to generate>" --reference <reference-file>
```

`--reference` is required: without a file whose conventions the output should
match, the worker generates context-free code that fits nothing in the project.

Each call is independent. To build on what was just generated, pass that file
as the `--reference` for the next call.

Review the output and make surgical edits for the small share that needs
frontier-model judgment.
