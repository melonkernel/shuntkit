"""Worker-model transports.

A transport takes a system prompt and a user message and returns the worker's
answer plus usage. Two are built in:

* ``claude``: shells out to the Claude Code CLI in headless mode. Uses the
  user's existing login and plan, needs no API key. Default.
* ``anthropic``: calls the Anthropic Messages API through the official SDK.
  Needs ``pip install shuntkit[anthropic]`` and ``ANTHROPIC_API_KEY`` (or a
  profile from ``ant auth login``).

Both keep the file corpus out of the parent Claude Code session's context:
only the answer text comes back.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Protocol

from shuntkit.config import Config


class TransportError(RuntimeError):
    """Raised when the worker call fails. The message is shown to the user."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float | None = None
    model: str = ""
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class Answer:
    text: str
    usage: Usage


class Transport(Protocol):
    name: str

    def invoke(self, system_prompt: str, message: str) -> Answer: ...

    def check(self) -> list[str]:
        """Return a list of problems, empty when the transport is ready."""
        ...


# Model aliases the Claude CLI understands. The API transport needs full ids.
_ALIAS_TO_API_ID = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}


def api_model_id(model: str) -> str:
    return _ALIAS_TO_API_ID.get(model.lower(), model)


class ClaudeCLITransport:
    """Run ``claude -p`` as a stateless worker.

    Flags matter here. Without ``--setting-sources ""``, ``--tools ""`` and
    ``--strict-mcp-config`` the nested session loads the parent's CLAUDE.md,
    skills and MCP tool schemas and burns tens of thousands of tokens before
    reading a single file. Measured on a one-line file: 62k tokens without
    these flags, 1.4k with them.
    """

    name = "claude"

    def __init__(self, config: Config):
        self.config = config

    def _argv(self, system_prompt: str) -> list[str]:
        return [
            self.config.claude_bin,
            "-p",
            "--model",
            self.config.model,
            "--output-format",
            "json",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
            "--max-turns",
            "1",
            "--system-prompt",
            system_prompt,
        ]

    def check(self) -> list[str]:
        problems: list[str] = []
        if shutil.which(self.config.claude_bin) is None:
            problems.append(
                f"Claude CLI not found as '{self.config.claude_bin}'. Install Claude Code "
                "or set SHUNTKIT_CLAUDE_BIN."
            )
        return problems

    @staticmethod
    def _env() -> dict[str, str]:
        # Drop the markers that tell a CLI it is running inside Claude Code, so
        # the worker behaves like a fresh headless session.
        return {k: v for k, v in os.environ.items() if k not in {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}

    def invoke(self, system_prompt: str, message: str) -> Answer:
        try:
            # Run in an empty scratch directory so no project CLAUDE.md or
            # .claude/ settings can be picked up, whatever future defaults are.
            with tempfile.TemporaryDirectory(prefix="shuntkit-") as scratch:
                proc = subprocess.run(
                    self._argv(system_prompt),
                    input=message,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout_seconds,
                    check=False,
                    cwd=scratch,
                    env=self._env(),
                )
        except FileNotFoundError as exc:
            raise TransportError(
                f"Claude CLI not found ('{self.config.claude_bin}'). Set SHUNTKIT_CLAUDE_BIN."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TransportError(
                f"Worker call exceeded {self.config.timeout_seconds}s. Raise "
                "SHUNTKIT_TIMEOUT_SECONDS or split the files across calls."
            ) from exc

        if proc.returncode != 0 and not proc.stdout.strip():
            raise TransportError(
                f"claude exited with {proc.returncode}: {proc.stderr.strip() or 'no output'}"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise TransportError("claude returned non-JSON output: " + proc.stdout[:400].strip()) from exc

        text = str(data.get("result") or "").strip()
        if data.get("is_error") or not text:
            raise TransportError(f"Worker returned an error: {text or proc.stderr.strip() or 'empty result'}")
        usage = _usage_from_claude_json(data)
        return Answer(text=text, usage=usage)


def _usage_from_claude_json(data: dict) -> Usage:
    usage = Usage(cost_usd=data.get("total_cost_usd"), duration_ms=int(data.get("duration_api_ms") or 0))
    raw = data.get("usage") or {}
    usage.input_tokens = int(raw.get("input_tokens") or 0)
    usage.output_tokens = int(raw.get("output_tokens") or 0)
    usage.cache_read_input_tokens = int(raw.get("cache_read_input_tokens") or 0)
    usage.cache_creation_input_tokens = int(raw.get("cache_creation_input_tokens") or 0)
    model_usage = data.get("modelUsage") or {}
    if model_usage:
        usage.model = next(iter(model_usage))
    return usage


class AnthropicAPITransport:
    """Call the Messages API through the official ``anthropic`` SDK."""

    name = "anthropic"

    def __init__(self, config: Config):
        self.config = config

    def check(self) -> list[str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return ["The 'anthropic' package is missing. Run: pip install 'shuntkit[anthropic]'"]
        return []

    def invoke(self, system_prompt: str, message: str) -> Answer:
        try:
            import anthropic
        except ImportError as exc:
            raise TransportError(
                "The 'anthropic' package is missing. Run: pip install 'shuntkit[anthropic]'"
            ) from exc

        client = anthropic.Anthropic(timeout=float(self.config.timeout_seconds))
        model = api_model_id(self.config.model)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=self.config.max_output_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            )
        except anthropic.AuthenticationError as exc:
            raise TransportError(
                "Anthropic API authentication failed. Set ANTHROPIC_API_KEY or run 'ant auth login'."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise TransportError("Anthropic API rate limit hit. Retry shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise TransportError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise TransportError(f"Could not reach the Anthropic API: {exc}") from exc

        if response.stop_reason == "refusal":
            raise TransportError("The worker model refused the request.")
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        if not text:
            raise TransportError("The worker model returned no text.")
        u = response.usage
        usage = Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_input_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            model=response.model,
        )
        return Answer(text=text, usage=usage)


def get_transport(config: Config) -> Transport:
    if config.transport == "claude":
        return ClaudeCLITransport(config)
    if config.transport == "anthropic":
        return AnthropicAPITransport(config)
    raise TransportError(f"Unknown SHUNTKIT_TRANSPORT '{config.transport}'. Use 'claude' or 'anthropic'.")
