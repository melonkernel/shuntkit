"""Read-hook decisions.

The first block of cases is ported one-to-one from upstream
``plugins/shunt/evals/hook-evals.json`` so behaviour stays comparable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from shuntkit.config import Config
from shuntkit.hooks import decide_read, to_hook_output

HINT = "shuntkit read ..."


def payload(path: Path | str, **extra) -> dict:
    return {"tool_name": "Read", "tool_input": {"file_path": str(path), **extra}}


# (fixture key, extra tool_input, expected allow, upstream case name)
UPSTREAM_CASES = [
    ("small", {}, True, "small-file"),
    ("boundary", {}, True, "boundary-exact-350"),
    ("over", {}, False, "just-over-threshold"),
    ("large", {}, False, "large-file"),
    ("huge", {}, False, "very-large-file"),
    ("empty", {}, True, "empty-file"),
    ("large", {"offset": 100}, True, "targeted-read-offset"),
    ("large", {"limit": 50}, True, "targeted-read-limit"),
    ("large", {"offset": 100, "limit": 50}, True, "targeted-read-both"),
    ("large", {"offset": 0}, True, "offset-zero"),
    ("large", {"limit": 0}, True, "limit-zero"),
]


@pytest.mark.parametrize("key,extra,expected,name", UPSTREAM_CASES, ids=[c[3] for c in UPSTREAM_CASES])
def test_upstream_cases(files, config, key, extra, expected, name):
    decision = decide_read(payload(files[key], **extra), config, HINT)
    assert decision.allow is expected, name


def test_nonexistent_file_allows(config):
    assert decide_read(payload("/tmp/shuntkit-does-not-exist.txt"), config, HINT).allow


def test_empty_and_missing_path_allow(config):
    assert decide_read(payload(""), config, HINT).allow
    assert decide_read({"tool_input": {}}, config, HINT).allow
    assert decide_read({}, config, HINT).allow


def test_env_override_lower(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "200")
    assert decide_read(payload(files["medium"]), Config.from_env(), HINT).blocked


def test_env_override_higher(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "500")
    assert decide_read(payload(files["over"]), Config.from_env(), HINT).allow


def test_upstream_env_name_still_honoured(files, monkeypatch):
    monkeypatch.delenv("SHUNTKIT_MIN_LINES", raising=False)
    monkeypatch.setenv("SHUNT_MIN_LINES", "200")
    assert decide_read(payload(files["medium"]), Config.from_env(), HINT).blocked


def test_env_non_numeric_falls_back(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "abc")
    assert decide_read(payload(files["over"]), Config.from_env(), HINT).blocked


def test_disabled_allows_everything(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_DISABLED", "1")
    assert decide_read(payload(files["huge"]), Config.from_env(), HINT).allow


def test_relative_path_resolved_against_cwd(files, config):
    p = {"tool_input": {"file_path": "large.txt"}, "cwd": str(files["large"].parent)}
    assert decide_read(p, config, HINT).blocked


def test_tilde_expanded(files, config, monkeypatch):
    monkeypatch.setenv("HOME", str(files["large"].parent))
    assert decide_read(payload("~/large.txt"), config, HINT).blocked


def test_non_text_suffix_allowed(files, config):
    assert decide_read(payload(files["image"]), config, HINT).allow


def test_block_reason_mentions_lines_threshold_and_hint(files, config):
    d = decide_read(payload(files["large"]), config, HINT)
    assert "1200 lines" in d.reason
    assert "threshold: 350" in d.reason
    assert HINT in d.reason
    assert "offset/limit" in d.reason


def test_hook_output_shape(files, config):
    d = decide_read(payload(files["large"]), config, HINT)
    out = to_hook_output(d)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": d.reason,
        }
    }
    assert to_hook_output(decide_read(payload(files["small"]), config, HINT)) is None
    json.dumps(out)  # serialisable


def test_state_dir_from_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("SHUNTKIT_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert Config.from_env().state_dir == tmp_path / "shuntkit"
    assert os.path.isabs(Config.from_env().state_dir)
