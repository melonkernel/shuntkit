"""Slice budget and sanctions."""

from __future__ import annotations

import json
import time
from pathlib import Path

from shuntkit import budget
from shuntkit.config import Config
from shuntkit.hooks import decide_read


def read(path: Path, session: str = "s1", **extra) -> dict:
    return {"session_id": session, "tool_input": {"file_path": str(path), **extra}}


def test_default_budget_is_twice_min_lines(config):
    assert config.slice_budget_lines == 700
    assert Config(min_lines=100).slice_budget_lines == 700  # dataclass default; from_env scales
    cfg = Config.from_env()
    assert cfg.slice_budget_lines == 2 * cfg.min_lines


def test_slices_accumulate_then_block(files, config):
    big = files["large"]  # 1200 lines
    for offset in (1, 301, 601):
        assert decide_read(read(big, offset=offset, limit=200), config).allow
    # 600 charged so far. This one brings it to 800 > 700.
    d = decide_read(read(big, offset=901, limit=200), config)
    assert d.blocked
    assert "800 lines" in d.reason
    assert "budget: 700" in d.reason
    assert "shuntkit read" in d.reason


def test_offset_only_counts_remaining_lines_up_to_read_default(files, config):
    big = files["large"]
    # offset 1001 on a 1200-line file leaves 200 lines, not 2000.
    assert decide_read(read(big, offset=1001), config).allow
    state = budget.charge_slice(config, "s1", big, 0)
    assert state.total == 200


def test_budget_is_per_session(files, config):
    big = files["large"]
    for offset in (1, 301, 601, 901):
        decide_read(read(big, offset=offset, limit=200, session="a"), config)
    assert decide_read(read(big, offset=1, limit=200, session="a"), config).blocked
    assert decide_read(read(big, offset=1, limit=200, session="b"), config).allow


def test_budget_is_per_file(files, config):
    for offset in (1, 301, 601, 901):
        decide_read(read(files["large"], offset=offset, limit=200), config)
    assert decide_read(read(files["huge"], offset=1, limit=200), config).allow


def test_small_files_are_never_charged(files, config):
    for _ in range(20):
        assert decide_read(read(files["medium"], offset=1, limit=100), config).allow


def test_sanction_lifts_the_block(files, config):
    big = files["large"]
    for offset in (1, 301, 601, 901):
        decide_read(read(big, offset=offset, limit=200), config)
    assert decide_read(read(big, offset=1, limit=200), config).blocked
    budget.sanction(config, [big])
    assert decide_read(read(big, offset=1, limit=200), config).allow


def test_sanction_expires(files, config, monkeypatch):
    big = files["large"]
    budget.sanction(config, [big])
    assert budget.is_sanctioned(config, big)
    monkeypatch.setattr(time, "time", lambda: 9e12)  # far future
    assert not budget.is_sanctioned(config, big)


def test_subagent_full_read_sanctions_file(files, config):
    big = files["large"]
    p = read(big)
    p["agent_type"] = "shuntkit:bulk-reader"
    assert decide_read(p, config).allow
    assert budget.is_sanctioned(config, big)


def test_zero_budget_disables(files, state_dir):
    cfg = Config(state_dir=state_dir, slice_budget_lines=0)
    for offset in range(1, 1200, 100):
        assert decide_read(read(files["large"], offset=offset, limit=100), cfg).allow
    assert not (state_dir / "slices").exists()


def test_state_files_are_json_and_keyed_by_resolved_path(files, config, state_dir):
    decide_read(read(files["large"], offset=1, limit=50), config)
    data = json.loads((state_dir / "slices" / "s1.json").read_text())
    assert data == {str(files["large"].resolve()): 50}


def test_unwritable_state_dir_fails_open(files, tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    cfg = Config(state_dir=blocker / "state")
    for offset in range(1, 1200, 100):
        assert decide_read(read(files["large"], offset=offset, limit=100), cfg).allow


def test_weird_session_ids_are_sanitised(files, config, state_dir):
    decide_read(read(files["large"], offset=1, limit=50, session="../../evil"), config)
    names = [p.name for p in (state_dir / "slices").iterdir()]
    assert names == [".._.._evil.json"]
