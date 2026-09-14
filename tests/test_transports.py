from __future__ import annotations

import json
import subprocess

import pytest

from shuntkit.config import Config
from shuntkit.transports import (
    ClaudeCLITransport,
    TransportError,
    api_model_id,
    get_transport,
)


class FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_argv_isolates_the_worker_session():
    argv = ClaudeCLITransport(Config(model="haiku"))._argv("SYS")
    assert argv[:2] == ["claude", "-p"]
    assert argv[argv.index("--model") + 1] == "haiku"
    # These three flags are what keep the nested session from loading the
    # parent's CLAUDE.md, skills and MCP schemas.
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert "--no-session-persistence" in argv
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[argv.index("--output-format") + 1] == "json"


def test_claude_transport_parses_json(monkeypatch):
    data = {
        "result": "- answer",
        "is_error": False,
        "total_cost_usd": 0.002,
        "duration_api_ms": 2758,
        "usage": {"input_tokens": 1367, "output_tokens": 127, "cache_read_input_tokens": 0},
        "modelUsage": {"claude-haiku-4-5-20251001": {}},
    }
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["input"] = kwargs["input"]
        return FakeProc(stdout=json.dumps(data))

    monkeypatch.setattr(subprocess, "run", fake_run)
    answer = ClaudeCLITransport(Config()).invoke("SYS", "MSG")
    assert captured["input"] == "MSG"
    assert answer.text == "- answer"
    assert answer.usage.input_tokens == 1367
    assert answer.usage.output_tokens == 127
    assert answer.usage.cost_usd == 0.002
    assert answer.usage.model == "claude-haiku-4-5-20251001"
    assert answer.usage.duration_ms == 2758


def test_claude_transport_error_result(monkeypatch):
    data = {"result": "Not logged in · Please run /login", "is_error": True}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=json.dumps(data)))
    with pytest.raises(TransportError, match="Not logged in"):
        ClaudeCLITransport(Config()).invoke("SYS", "MSG")


def test_claude_transport_nonzero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stderr="boom", returncode=1))
    with pytest.raises(TransportError, match="exited with 1: boom"):
        ClaudeCLITransport(Config()).invoke("SYS", "MSG")


def test_claude_transport_non_json(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout="<html>"))
    with pytest.raises(TransportError, match="non-JSON"):
        ClaudeCLITransport(Config()).invoke("SYS", "MSG")


def test_claude_transport_timeout(monkeypatch):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TransportError, match="exceeded 1s"):
        ClaudeCLITransport(Config(timeout_seconds=1)).invoke("SYS", "MSG")


def test_claude_transport_missing_binary(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(TransportError, match="not found"):
        ClaudeCLITransport(Config(claude_bin="nope-claude")).invoke("SYS", "MSG")


def test_check_reports_missing_binary():
    problems = ClaudeCLITransport(Config(claude_bin="definitely-not-a-binary-xyz")).check()
    assert problems and "not found" in problems[0]


def test_get_transport_names():
    assert get_transport(Config(transport="claude")).name == "claude"
    assert get_transport(Config(transport="anthropic")).name == "anthropic"
    with pytest.raises(TransportError, match="Unknown SHUNTKIT_TRANSPORT"):
        get_transport(Config(transport="portal"))


def test_api_model_alias():
    assert api_model_id("haiku") == "claude-haiku-4-5"
    assert api_model_id("sonnet") == "claude-sonnet-5"
    assert api_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
