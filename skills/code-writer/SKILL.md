---
name: code-writer
description: "Delegate boilerplate code generation to a cheaper Claude model via shuntkit. Use for tests, config, docstrings, type stubs, or any generation where >80% is predictable from a reference file."
---

```bash
# Generate and write directly to the target file
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit write --spec "<what to generate>" \
  --reference <file-whose-style-to-match> \
  --context <source-file-the-output-is-about> [<more>] \
  --target <output-path>

# Output to stdout instead (omit --target)
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m shuntkit write --spec "<what to generate>" --reference <ref> --context <src>
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
