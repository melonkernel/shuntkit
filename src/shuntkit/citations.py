"""Attach verified line numbers to the worker's quotes.

The worker is asked to quote distinctive fragments verbatim in backticks. For
every backticked span of reasonable length we search the delegated files. A
span found exactly once gets ``(file:line)`` appended; anything else is left
untouched. Claude therefore receives line numbers it can trust without having
read the file, which is the main complaint about delegated summaries.

Disable with ``SHUNTKIT_CITATIONS=off``.
"""

from __future__ import annotations

import re
from pathlib import Path

_SPAN_RE = re.compile(r"`([^`\n]{12,240})`(?!\s*\()")
_MIN_ALNUM = 6


def _load(files: list[Path]) -> list[tuple[str, str]]:
    corpus: list[tuple[str, str]] = []
    names = [p.name for p in files]
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Use the basename unless two files share it.
        label = p.name if names.count(p.name) == 1 else str(p)
        corpus.append((label, text))
    return corpus


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def annotate(answer: str, files: list[Path]) -> str:
    corpus = _load(files)
    if not corpus:
        return answer

    def repl(match: re.Match[str]) -> str:
        span = match.group(1)
        if sum(ch.isalnum() for ch in span) < _MIN_ALNUM:
            return match.group(0)
        hits: list[tuple[str, int]] = []
        for label, text in corpus:
            start = 0
            while True:
                idx = text.find(span, start)
                if idx < 0:
                    break
                hits.append((label, _line_of(text, idx)))
                if len(hits) > 1:
                    return match.group(0)
                start = idx + 1
        if len(hits) != 1:
            return match.group(0)
        label, line = hits[0]
        return f"{match.group(0)} ({label}:{line})"

    return _SPAN_RE.sub(repl, answer)
