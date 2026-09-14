"""Configuration, read from environment variables.

Every knob has a ``SHUNTKIT_`` prefix. The upstream ``SHUNT_MIN_LINES`` name is
honoured as a fallback so existing setups keep working.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MIN_LINES = 350
DEFAULT_TRANSPORT = "claude"
DEFAULT_MODEL = "haiku"
DEFAULT_TIMEOUT_SECONDS = 180
# Haiku 4.5 has a 200k-token window; ~4 bytes per token puts 600 kB at roughly
# 150k tokens, leaving room for the system prompt and the answer.
DEFAULT_MAX_PAYLOAD_BYTES = 600_000
DEFAULT_MAX_OUTPUT_TOKENS = 8192
# Cumulative targeted-read lines allowed per file per session before the hook
# insists on one delegation.
DEFAULT_SLICE_BUDGET_FACTOR = 2
# After a file has been delegated, targeted reads of it are unrestricted for
# this long.
DEFAULT_SANCTION_TTL_SECONDS = 4 * 3600
DEFAULT_DELEGATE = "cli"
# Which coding agent the hooks are talking to. Changes the wording of block
# messages (Codex has no Read tool, no skills and no Agent tool).
DEFAULT_HOST = "claude"
HOSTS = ("claude", "codex")

READER_SYSTEM_PROMPT = (
    "You are a precise code analyst. Read the provided files and answer the "
    "question concisely. Output structured bullets only. When you refer to "
    "specific code, quote a distinctive fragment of it verbatim in backticks "
    "(a few words, exactly as written) so the caller can locate it; the caller "
    "attaches line numbers to verified quotes. Quote identifiers exactly as "
    "they appear. If the files do not contain the answer, say so."
)

WRITER_SYSTEM_PROMPT = (
    "You are a code generator. You receive a specification and a reference "
    "file. Generate code that fulfils the specification and matches the "
    "reference file's conventions (naming, imports, formatting, test style). "
    "Output only the code. No explanations, no markdown fences unless asked."
)


def _int_env(name: str, default: int, *fallback_names: str) -> int:
    for key in (name, *fallback_names):
        raw = os.environ.get(key)
        if raw is None or raw == "":
            continue
        if raw.isdigit():
            return int(raw)
        # Non-numeric value: ignore it and fall back, matching upstream.
    return default


def _flag_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    min_lines: int = DEFAULT_MIN_LINES
    transport: str = DEFAULT_TRANSPORT
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    claude_bin: str = "claude"
    state_dir: Path = Path.home() / ".local" / "state" / "shuntkit"
    disabled: bool = False
    # 0 disables the slice budget.
    slice_budget_lines: int = DEFAULT_MIN_LINES * DEFAULT_SLICE_BUDGET_FACTOR
    sanction_ttl_seconds: int = DEFAULT_SANCTION_TTL_SECONDS
    # "cli": hook messages point at the shuntkit command. "subagent": they point
    # at the bulk-reader subagent (Agent tool) instead.
    delegate: str = DEFAULT_DELEGATE
    host: str = DEFAULT_HOST
    secret_guard: bool = True
    citations: bool = True

    @classmethod
    def from_env(cls) -> Config:
        state_dir = os.environ.get("SHUNTKIT_STATE_DIR")
        xdg = os.environ.get("XDG_STATE_HOME")
        if state_dir:
            state = Path(state_dir)
        elif xdg:
            state = Path(xdg) / "shuntkit"
        else:
            state = Path.home() / ".local" / "state" / "shuntkit"
        min_lines = _int_env("SHUNTKIT_MIN_LINES", DEFAULT_MIN_LINES, "SHUNT_MIN_LINES")
        return cls(
            min_lines=min_lines,
            transport=os.environ.get("SHUNTKIT_TRANSPORT", DEFAULT_TRANSPORT).strip().lower(),
            model=os.environ.get("SHUNTKIT_MODEL", DEFAULT_MODEL).strip(),
            timeout_seconds=_int_env("SHUNTKIT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
            max_payload_bytes=_int_env("SHUNTKIT_MAX_PAYLOAD_BYTES", DEFAULT_MAX_PAYLOAD_BYTES),
            max_output_tokens=_int_env("SHUNTKIT_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
            claude_bin=os.environ.get("SHUNTKIT_CLAUDE_BIN", "claude").strip() or "claude",
            state_dir=state,
            disabled=_flag_env("SHUNTKIT_DISABLED", default=False),
            slice_budget_lines=_int_env(
                "SHUNTKIT_SLICE_BUDGET_LINES", min_lines * DEFAULT_SLICE_BUDGET_FACTOR
            ),
            sanction_ttl_seconds=_int_env("SHUNTKIT_SANCTION_TTL_SECONDS", DEFAULT_SANCTION_TTL_SECONDS),
            delegate=os.environ.get("SHUNTKIT_DELEGATE", DEFAULT_DELEGATE).strip().lower()
            or DEFAULT_DELEGATE,
            host=os.environ.get("SHUNTKIT_HOST", DEFAULT_HOST).strip().lower() or DEFAULT_HOST,
            secret_guard=_flag_env("SHUNTKIT_SECRET_GUARD", default=True),
            citations=_flag_env("SHUNTKIT_CITATIONS", default=True),
        )
