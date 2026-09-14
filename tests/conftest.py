from __future__ import annotations

from pathlib import Path

import pytest

from shuntkit.config import Config


def make_file(directory: Path, name: str, lines: int) -> Path:
    path = directory / name
    path.write_text("".join(f"line {i}\n" for i in range(lines)), encoding="utf-8")
    return path


@pytest.fixture
def config() -> Config:
    return Config()


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
