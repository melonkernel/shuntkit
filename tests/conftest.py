from __future__ import annotations

from pathlib import Path

import pytest

from shuntkit.config import Config


def make_file(directory: Path, name: str, lines: int) -> Path:
    path = directory / name
    path.write_text("".join(f"line {i}\n" for i in range(lines)), encoding="utf-8")
    return path


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


@pytest.fixture
def config(state_dir: Path) -> Config:
    """Default config with hook state redirected away from the real home dir."""
    return Config(state_dir=state_dir)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, state_dir: Path):
    """Config.from_env() in tests must never touch ~/.local/state."""
    monkeypatch.setenv("SHUNTKIT_STATE_DIR", str(state_dir))
    for var in (
        "SHUNTKIT_MIN_LINES",
        "SHUNT_MIN_LINES",
        "SHUNTKIT_DISABLED",
        "SHUNTKIT_DELEGATE",
        "SHUNTKIT_SLICE_BUDGET_LINES",
        "CLAUDE_PLUGIN_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    return {
        "small": make_file(tmp_path, "small.txt", 100),
        "medium": make_file(tmp_path, "medium.txt", 250),
        "boundary": make_file(tmp_path, "boundary.txt", 350),
        "over": make_file(tmp_path, "over.txt", 351),
        "large": make_file(tmp_path, "large.txt", 1200),
        "huge": make_file(tmp_path, "huge.txt", 5000),
        "empty": make_file(tmp_path, "empty.txt", 0),
        "image": make_file(tmp_path, "diagram.png", 900),
    }
