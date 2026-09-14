"""PreToolUse hook decisions.

Two pure functions decide whether a Read or Bash tool call should be blocked
and redirected to the bulk-reader skill. They take the parsed hook payload and
a :class:`Config` and return a :class:`Decision`. No I/O beyond stat/reading
the file to count lines, so they are cheap and easy to test.

Semantics follow the upstream shunt hooks, with two deliberate differences:

* ``head``/``tail`` with an explicit line count are treated as targeted reads
  and allowed (upstream blocked ``head -100 big.txt``).
* ``cat a b c`` sums the line counts of all files (upstream checked the first).
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shuntkit.config import Config

# Commands that dump a whole file into the transcript.
FULL_READ_COMMANDS = frozenset({"cat", "less", "more", "bat", "batcat"})
# Commands that read a bounded slice unless told otherwise.
SLICE_COMMANDS = frozenset({"head", "tail"})

# Files the Read tool renders specially (images, PDFs, notebooks). A line count
# is meaningless for these, so let them through.
NON_TEXT_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".ipynb"})


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
    lines: int = 0

    @property
    def blocked(self) -> bool:
        return not self.allow


ALLOW = Decision(allow=True)


def count_lines(path: Path) -> int:
    """Count newline characters, like ``wc -l``. Returns 0 on any error."""
    try:
        total = 0
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                total += chunk.count(b"\n")
        return total
    except OSError:
        return 0


def resolve_path(raw: str, cwd: str | None) -> Path | None:
    if not raw:
        return None
    expanded = os.path.expanduser(raw)
    path = Path(expanded)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    return path


def block_reason(lines: int, min_lines: int, *, via: str, command_hint: str) -> str:
    return (
        f"File is {lines} lines (threshold: {min_lines}). shuntkit blocked this {via} "
        f"so the whole file does not enter your context. Use the /bulk-reader skill "
        f"instead: {command_hint}. If you need exact content for editing, re-read "
        f"with offset/limit for just the section you need."
    )


def decide_read(payload: Mapping[str, Any], config: Config, command_hint: str) -> Decision:
    """Decide a Read tool call."""
    if config.disabled:
        return ALLOW
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    # Targeted reads: Claude already knows what it needs. Upstream treats a
    # present-but-zero offset/limit as targeted too; we keep that behaviour.
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return ALLOW
    path = resolve_path(str(file_path), payload.get("cwd"))
    if path is None or not path.is_file():
        return ALLOW
    if path.suffix.lower() in NON_TEXT_SUFFIXES:
        return ALLOW
    lines = count_lines(path)
    if lines <= config.min_lines:
        return Decision(allow=True, lines=lines)
    return Decision(
        allow=False,
        lines=lines,
        reason=block_reason(lines, config.min_lines, via="Read", command_hint=command_hint),
    )


def _split_pipeline_free(command: str) -> list[str] | None:
    """Tokenise a command, returning None when it is not a simple read."""
    # Pipes and redirects mean the output is consumed by something other than
    # the transcript (grep, a file). Let them through, as upstream does.
    if "|" in command or ">" in command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    return tokens or None


def _strip_env_and_wrappers(tokens: list[str]) -> list[str]:
    """Drop leading ``FOO=bar`` assignments and ``sudo``/``command`` wrappers."""
    i = 0
    while i < len(tokens) and ("=" in tokens[i] and not tokens[i].startswith("-")):
        i += 1
    while i < len(tokens) and tokens[i] in {"sudo", "command", "nice", "time"}:
        i += 1
    return tokens[i:]


def _slice_is_bounded(cmd: str, args: list[str], min_lines: int) -> bool:
    """True when ``head``/``tail`` would print at most ``min_lines`` lines."""
    # Default output is 10 lines.
    count: int | None = 10
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-n", "--lines"} and i + 1 < len(args):
            count = _parse_count(args[i + 1])
            i += 2
            continue
        if arg.startswith("--lines="):
            count = _parse_count(arg.split("=", 1)[1])
        elif arg.startswith("-n") and len(arg) > 2:
            count = _parse_count(arg[2:])
        elif arg.startswith("-") and arg[1:].isdigit():
            count = int(arg[1:])
        elif arg in {"-c", "--bytes"} or arg.startswith("--bytes=") or arg.startswith("-c"):
            # Byte-bounded output; treat as targeted.
            return True
        i += 1
    if count is None:
        # Something like ``tail -n +5`` prints to end of file: unbounded.
        return False
    return count <= min_lines


def _parse_count(raw: str) -> int | None:
    raw = raw.strip()
    if raw.startswith("+"):
        return None  # ``-n +N``: from line N to EOF.
    if raw.startswith("-"):
        raw = raw[1:]
    # Accept suffixes like 10k loosely: anything non-numeric is unbounded.
    return int(raw) if raw.isdigit() else None


def _file_args(cmd: str, args: list[str]) -> list[str]:
    files: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            continue
        if arg.startswith("-"):
            if cmd in SLICE_COMMANDS and arg in {"-n", "-c", "--lines", "--bytes"}:
                skip_next = True
            continue
        files.append(arg)
    return files


def decide_bash(payload: Mapping[str, Any], config: Config, command_hint: str) -> Decision:
    """Decide a Bash tool call that might dump a large file."""
    if config.disabled:
        return ALLOW
    tool_input = payload.get("tool_input") or {}
    command = (tool_input.get("command") or "").strip()
    if not command:
        return ALLOW
    tokens = _split_pipeline_free(command)
    if not tokens:
        return ALLOW
    # Only inspect the first simple command; ``a && b`` chains are rare for
    # plain reads and upstream ignores them as well.
    for sep in ("&&", ";", "||"):
        if sep in tokens:
            tokens = tokens[: tokens.index(sep)]
    tokens = _strip_env_and_wrappers(tokens)
    if not tokens:
        return ALLOW
    cmd = os.path.basename(tokens[0])
    args = tokens[1:]
    if cmd in SLICE_COMMANDS:
        if _slice_is_bounded(cmd, args, config.min_lines):
            return ALLOW
    elif cmd not in FULL_READ_COMMANDS:
        return ALLOW

    cwd = payload.get("cwd")
    total = 0
    for raw in _file_args(cmd, args):
        path = resolve_path(raw, cwd)
        if path is None or not path.is_file():
            continue
        if path.suffix.lower() in NON_TEXT_SUFFIXES:
            continue
        total += count_lines(path)
    if total == 0 or total <= config.min_lines:
        return Decision(allow=True, lines=total)
    return Decision(
        allow=False,
        lines=total,
        reason=block_reason(total, config.min_lines, via=f"`{cmd}`", command_hint=command_hint),
    )


def to_hook_output(decision: Decision) -> dict[str, Any] | None:
    """Render a decision as PreToolUse JSON. ``None`` means print nothing (allow)."""
    if decision.allow:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": decision.reason,
        }
    }
