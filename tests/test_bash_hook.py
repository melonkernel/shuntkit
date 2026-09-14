"""Bash-hook decisions.

Ported from upstream ``plugins/shunt/evals/bash-hook-evals.json``. Two cases
deliberately diverge from upstream and are marked as such:

* ``head -100 big`` and plain ``head big`` are allowed here. They print a
  bounded slice, which is exactly what the Read hook allows for offset/limit.
* ``head -n 5 big`` is allowed here on purpose, not by a parser accident.
"""

from __future__ import annotations

import pytest

from shuntkit.config import Config
from shuntkit.hooks import decide_bash


def payload(command: str, cwd: str | None = None) -> dict:
    p = {"tool_name": "Bash", "session_id": "s1", "tool_input": {"command": command}}
    if cwd:
        p["cwd"] = cwd
    return p


def test_cat_large_blocks(files, config):
    assert decide_bash(payload(f"cat {files['large']}"), config).blocked


def test_cat_small_allows(files, config):
    assert decide_bash(payload(f"cat {files['small']}"), config).allow


def test_cat_with_flag_blocks(files, config):
    assert decide_bash(payload(f"cat -n {files['large']}"), config).blocked


@pytest.mark.parametrize("cmd", ["less", "more", "bat"])
def test_pagers_block(files, config, cmd):
    assert decide_bash(payload(f"{cmd} {files['large']}"), config).blocked


def test_pipe_allows(files, config):
    assert decide_bash(payload(f"cat {files['large']} | grep export"), config).allow


def test_redirect_allows(files, config):
    assert decide_bash(payload(f"cat {files['large']} > /tmp/out.txt"), config).allow


def test_non_read_command_allows(config):
    assert decide_bash(payload("git status"), config).allow


def test_grep_allows(files, config):
    assert decide_bash(payload(f"grep -n export {files['large']}"), config).allow


def test_quoted_path_blocks(files, config):
    assert decide_bash(payload(f'cat "{files["large"]}"'), config).blocked


def test_nonexistent_allows(config):
    assert decide_bash(payload("cat /tmp/shuntkit-does-not-exist.txt"), config).allow


def test_empty_and_missing_command_allow(config):
    assert decide_bash(payload(""), config).allow
    assert decide_bash({"tool_input": {}}, config).allow


# --- deliberate divergences from upstream -------------------------------------


def test_head_default_is_bounded_and_allowed(files, config):
    """Upstream blocked this; ten lines is a targeted read."""
    assert decide_bash(payload(f"head {files['large']}"), config).allow


def test_head_with_count_under_threshold_allows(files, config):
    assert decide_bash(payload(f"head -100 {files['large']}"), config).allow
    assert decide_bash(payload(f"head -n 5 {files['large']}"), config).allow
    assert decide_bash(payload(f"tail -n 20 {files['large']}"), config).allow


def test_head_with_count_over_threshold_blocks(files, config):
    assert decide_bash(payload(f"head -n 1000 {files['large']}"), config).blocked
    assert decide_bash(payload(f"head -1000 {files['large']}"), config).blocked


def test_tail_from_line_is_unbounded_and_blocks(files, config):
    assert decide_bash(payload(f"tail -n +5 {files['large']}"), config).blocked


# --- extra coverage -------------------------------------------------------------


def test_multiple_files_sum(files, config):
    two = f"cat {files['medium']} {files['medium']}"  # 500 lines total
    assert decide_bash(payload(two), config).blocked


def test_relative_path_uses_cwd(files, config):
    assert decide_bash(payload("cat large.txt", cwd=str(files["large"].parent)), config).blocked


def test_chained_command_inspects_first(files, config):
    assert decide_bash(payload(f"cat {files['large']} && echo done"), config).blocked
    assert decide_bash(payload(f"echo start && cat {files['large']}"), config).allow


def test_env_prefix_and_sudo_skipped(files, config):
    assert decide_bash(payload(f"LC_ALL=C cat {files['large']}"), config).blocked
    assert decide_bash(payload(f"sudo cat {files['large']}"), config).blocked


def test_unbalanced_quotes_allow(config):
    assert decide_bash(payload('cat "unterminated'), config).allow


def test_disabled(files, monkeypatch):
    monkeypatch.setenv("SHUNTKIT_DISABLED", "true")
    assert decide_bash(payload(f"cat {files['huge']}"), Config.from_env()).allow


def test_reason_names_command(files, config):
    d = decide_bash(payload(f"cat {files['large']}"), config)
    assert "`cat`" in d.reason
    assert "1200 lines" in d.reason


def test_subagent_exempt(files, config):
    p = payload(f"cat {files['huge']}")
    p["agent_type"] = "shuntkit:bulk-reader"
    assert decide_bash(p, config).allow


def test_head_slices_are_charged_to_budget(files, config):
    """Six head -n 200 calls on a 1200-line file = 1200 lines > 700 budget."""
    for _ in range(3):
        assert decide_bash(payload(f"head -n 200 {files['large']}"), config).allow
    d = decide_bash(payload(f"head -n 200 {files['large']}"), config)
    assert d.blocked
    assert "in slices this session" in d.reason
