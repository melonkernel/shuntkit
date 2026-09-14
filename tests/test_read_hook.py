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
from shuntkit.hooks import decide_read, delegation_hint, to_hook_output


def payload(path: Path | str, **extra) -> dict:
    return {"tool_name": "Read", "session_id": "s1", "tool_input": {"file_path": str(path), **extra}}


# (fixture key, extra tool_input, expected allow, upstream case name)
# Two expectations differ from upstream on purpose, see the divergence tests.
UPSTREAM_CASES = [
    ("small", {}, True, "small-file"),
    ("boundary", {}, True, "boundary-exact-350"),
    ("over", {}, False, "just-over-threshold"),
    ("large", {}, False, "large-file"),
    ("huge", {}, False, "very-large-file"),
    ("empty", {}, True, "empty-file"),
    ("large", {"limit": 50}, True, "targeted-read-limit"),
    ("large", {"offset": 100, "limit": 50}, True, "targeted-read-both"),
    ("large", {"limit": 0}, True, "limit-zero"),
]


@pytest.mark.parametrize("key,extra,expected,name", UPSTREAM_CASES, ids=[c[3] for c in UPSTREAM_CASES])
def test_upstream_cases(files, config, key, extra, expected, name):
    decision = decide_read(payload(files[key], **extra), config)
    assert decision.allow is expected, name


def test_nonexistent_file_allows(config):
    assert decide_read(payload("/tmp/shuntkit-does-not-exist.txt"), config).allow


def test_empty_and_missing_path_allow(config):
    assert decide_read(payload(""), config).allow
    assert decide_read({"tool_input": {}}, config).allow
    assert decide_read({}, config).allow


def test_env_override_lower(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "200")
    assert decide_read(payload(files["medium"]), Config.from_env()).blocked


def test_env_override_higher(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "500")
    assert decide_read(payload(files["over"]), Config.from_env()).allow


def test_upstream_env_name_still_honoured(files, monkeypatch):
    monkeypatch.setenv("SHUNT_MIN_LINES", "200")
    assert decide_read(payload(files["medium"]), Config.from_env()).blocked


def test_env_non_numeric_falls_back(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_MIN_LINES", "abc")
    assert decide_read(payload(files["over"]), Config.from_env()).blocked


def test_disabled_allows_everything(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_DISABLED", "1")
    assert decide_read(payload(files["huge"]), Config.from_env()).allow


def test_relative_path_resolved_against_cwd(files, config):
    p = {"tool_input": {"file_path": "large.txt"}, "cwd": str(files["large"].parent)}
    assert decide_read(p, config).blocked


def test_tilde_expanded(files, config, monkeypatch):
    monkeypatch.setenv("HOME", str(files["large"].parent))
    assert decide_read(payload("~/large.txt"), config).blocked


def test_non_text_suffix_allowed(files, config):
    assert decide_read(payload(files["image"]), config).allow


def test_block_reason_mentions_lines_threshold_and_hint(files, config):
    d = decide_read(payload(files["large"]), config)
    assert "1200 lines" in d.reason
    assert "threshold: 350" in d.reason
    assert "shuntkit read" in d.reason
    assert "offset/limit" in d.reason


def test_hint_variants(config, monkeypatch):
    assert delegation_hint(config).startswith("use the /bulk-reader skill: shuntkit read")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/plugins/shuntkit")
    assert 'PYTHONPATH="/plugins/shuntkit/src" python3 -m shuntkit read' in delegation_hint(config)
    sub = Config(delegate="subagent", state_dir=config.state_dir)
    assert 'subagent_type "shuntkit:bulk-reader"' in delegation_hint(sub)
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    assert 'subagent_type "bulk-reader"' in delegation_hint(sub)


def test_hook_output_shape(files, config):
    d = decide_read(payload(files["large"]), config)
    out = to_hook_output(d)
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": d.reason,
        }
    }
    assert to_hook_output(decide_read(payload(files["small"]), config)) is None
    json.dumps(out)  # serialisable


def test_state_dir_from_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("SHUNTKIT_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert Config.from_env().state_dir == tmp_path / "shuntkit"
    assert os.path.isabs(Config.from_env().state_dir)


# --- deliberate divergences from upstream -------------------------------------


def test_offset_without_limit_is_a_whole_file_read(files, config):
    """Upstream allowed ``offset`` alone ("targeted-read-offset"). It returns up
    to 2000 lines, so on a 1200-line file it is the whole file minus 99 lines."""
    d = decide_read(payload(files["large"], offset=100), config)
    assert d.blocked
    assert "1101 lines" in d.reason
    assert "offset/limit" in d.reason


def test_offset_zero_bypass_is_closed(files, config):
    """Upstream's own eval labels ``offset: 0`` a "known bypass"."""
    assert decide_read(payload(files["large"], offset=0), config).blocked


def test_offset_near_end_is_a_genuine_slice(files, config):
    """offset 1001 of 1200 leaves 200 lines: allowed and charged."""
    assert decide_read(payload(files["large"], offset=1001), config).allow


def test_limit_over_threshold_blocks(files, config):
    assert decide_read(payload(files["large"], offset=1, limit=800), config).blocked
    assert decide_read(payload(files["large"], offset=1, limit=350), config).allow


# --- subagent exemption ---------------------------------------------------------


@pytest.mark.parametrize("agent", ["bulk-reader", "shuntkit:bulk-reader"])
def test_bulk_reader_subagent_is_exempt(files, config, agent):
    p = payload(files["huge"])
    p["agent_type"] = agent
    p["agent_id"] = "abc"
    assert decide_read(p, config).allow


def test_other_subagents_are_not_exempt(files, config):
    p = payload(files["huge"])
    p["agent_type"] = "Explore"
    assert decide_read(p, config).blocked
