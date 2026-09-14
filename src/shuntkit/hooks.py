"""PreToolUse hook decisions.

Two pure-ish functions decide whether a Read or Bash tool call should be
blocked and redirected to delegation. They take the parsed hook payload and a
:class:`Config` and return a :class:`Decision`. I/O is limited to counting
lines in the target file and to the small slice-budget state files.

Semantics follow the upstream shunt hooks, with these deliberate differences:

* ``head``/``tail`` with an explicit line count are treated as targeted reads
  and allowed (upstream blocked ``head -100 big.txt``).
* ``cat a b c`` sums the line counts of all files (upstream checked the first).
* A targeted read must itself be at or under the threshold. ``offset`` with
  no ``limit`` returns up to 2000 lines and is treated as a whole-file read
  (upstream allowed it and documented it as a known bypass).
* Targeted reads are charged against a per-session slice budget so a blocked
  file cannot be reassembled from many small reads.
* Calls made by the ``bulk-reader`` subagent are exempt (and sanction the
  file), so the subagent delegation mode works without a network round trip.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shuntkit import budget
from shuntkit.config import Config

# Commands that dump a whole file into the transcript.
FULL_READ_COMMANDS = frozenset({"cat", "less", "more", "bat", "batcat"})
# Commands that read a bounded slice unless told otherwise.
SLICE_COMMANDS = frozenset({"head", "tail"})

# Files the Read tool renders specially (images, PDFs, notebooks). A line count
# is meaningless for these, so let them through.
NON_TEXT_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".ipynb"})

# Subagent names whose tool calls bypass the hooks. The plugin form is
# ``shuntkit:bulk-reader``; ``shuntkit install`` writes a user-level agent
# named ``bulk-reader``.
EXEMPT_AGENT_TYPES = frozenset({"bulk-reader", "shuntkit:bulk-reader"})

# The Read tool reads at most this many lines when no limit is given.
READ_DEFAULT_LIMIT = 2000


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


def delegation_hint(config: Config) -> str:
    """Tell Claude exactly how to delegate, for use inside block messages."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if config.delegate == "subagent":
        agent = "shuntkit:bulk-reader" if root else "bulk-reader"
        return (
            f'use the Agent tool with subagent_type "{agent}" and ask it your question about the '
            f"file(s); it reads them in its own context and returns only the answer"
        )
    if root:
        cmd = f'PYTHONPATH="{root}/src" python3 -m shuntkit read --question "<q>" --paths <files>'
    else:
        cmd = 'shuntkit read --question "<q>" --paths <files>'
    return f"use the /bulk-reader skill: {cmd}"


def block_reason(lines: int, config: Config, *, via: str) -> str:
    return (
        f"File is {lines} lines (threshold: {config.min_lines}). shuntkit blocked this {via} "
        f"so the whole file does not enter your context. Instead, {delegation_hint(config)}. "
        f"If you need exact content for editing, re-read with offset/limit for just the section you need."
    )


def budget_reason(state: budget.SliceState, path: Path, config: Config) -> str:
    return (
        f"You have read {state.total} lines of {path.name} in slices this session "
        f"(budget: {state.budget}). shuntkit blocked this slice: reassembling a large file piece by "
        f"piece costs the same as reading it whole. Instead, {delegation_hint(config)}. After the "
        f"file has been delegated once, targeted reads of it are unrestricted for "
        f"{config.sanction_ttl_seconds // 3600} hours."
    )


def _is_exempt_agent(payload: Mapping[str, Any]) -> bool:
    return str(payload.get("agent_type") or "") in EXEMPT_AGENT_TYPES


def _charge(payload: Mapping[str, Any], config: Config, path: Path, lines: int) -> Decision:
    state = budget.charge_slice(config, payload.get("session_id"), path, lines)
    if state.exceeded:
        return Decision(allow=False, lines=lines, reason=budget_reason(state, path, config))
    return Decision(allow=True, lines=lines)


def decide_read(payload: Mapping[str, Any], config: Config) -> Decision:
    """Decide a Read tool call."""
    if config.disabled:
        return ALLOW
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    path = resolve_path(str(file_path), payload.get("cwd"))
    if path is None or not path.is_file() or path.suffix.lower() in NON_TEXT_SUFFIXES:
        return ALLOW

    offset = tool_input.get("offset")
    limit = tool_input.get("limit")
    targeted = offset is not None or limit is not None

    if _is_exempt_agent(payload):
        # The bulk-reader subagent is doing the delegated read. Let it through
        # and treat the file as delegated for the parent's slice budget.
        if not targeted:
            budget.sanction(config, [path])
        return ALLOW

    lines = count_lines(path)
    if not targeted:
        if lines <= config.min_lines:
            return Decision(allow=True, lines=lines)
        return Decision(allow=False, lines=lines, reason=block_reason(lines, config, via="Read"))

    # Targeted read: Claude already knows what it needs. Small files are
    # never restricted. For large files, work out how many lines the slice
    # would actually return: ``offset`` without ``limit`` reads up to 2000
    # lines, which is a whole-file read in disguise (upstream's evals call
    # this a "known bypass"; we close it). A genuine slice is charged to the
    # session budget so the file cannot be reassembled piecemeal.
    if lines <= config.min_lines:
        return Decision(allow=True, lines=lines)
    start = _as_int(offset, 0)
    wanted = _as_int(limit, READ_DEFAULT_LIMIT)
    slice_lines = max(0, min(wanted, lines - max(start - 1, 0)))
    if slice_lines > config.min_lines:
        return Decision(
            allow=False,
            lines=slice_lines,
            reason=block_reason(slice_lines, config, via="Read (offset/limit)"),
        )
    return _charge(payload, config, path, slice_lines)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


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


def _slice_count(args: list[str]) -> int | None:
    """Lines ``head``/``tail`` would print; ``None`` when unbounded."""
    count: int | None = 10  # default for both commands
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
        elif arg in {"-c", "--bytes"} or arg.startswith(("--bytes=", "-c")):
            # Byte-bounded output. Roughly 40 bytes per line of code.
            raw = args[i + 1] if arg in {"-c", "--bytes"} and i + 1 < len(args) else arg.split("=", 1)[-1]
            n = _parse_count(raw.lstrip("-c"))
            return None if n is None else max(1, n // 40)
        i += 1
    return count


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


def decide_bash(payload: Mapping[str, Any], config: Config) -> Decision:
    """Decide a Bash tool call that might dump a large file."""
    if config.disabled or _is_exempt_agent(payload):
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
    if cmd not in SLICE_COMMANDS and cmd not in FULL_READ_COMMANDS:
        return ALLOW

    cwd = payload.get("cwd")
    files: list[tuple[Path, int]] = []
    for raw in _file_args(cmd, args):
        path = resolve_path(raw, cwd)
        if path is None or not path.is_file() or path.suffix.lower() in NON_TEXT_SUFFIXES:
            continue
        files.append((path, count_lines(path)))
    if not files:
        return ALLOW

    if cmd in SLICE_COMMANDS:
        count = _slice_count(args)
        if count is not None and count <= config.min_lines:
            # Bounded slice: allow, but charge it against the budget for any
            # file that is itself over the threshold.
            for path, lines in files:
                if lines > config.min_lines:
                    decision = _charge(payload, config, path, min(count, lines))
                    if decision.blocked:
                        return decision
            return Decision(allow=True, lines=count)

    total = sum(lines for _, lines in files)
    if total <= config.min_lines:
        return Decision(allow=True, lines=total)
    return Decision(allow=False, lines=total, reason=block_reason(total, config, via=f"`{cmd}`"))


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
