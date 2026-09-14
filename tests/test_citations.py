from __future__ import annotations

from pathlib import Path

from shuntkit.citations import annotate

SRC = """import os

def load_config(path):
    with open(path) as fh:
        return parse(fh.read())

def parse(text):
    return dict(line.split("=", 1) for line in text.splitlines())

def save_config(path, data):
    with open(path, "w") as fh:
        fh.write(render(data))
"""


def test_unique_quote_gets_file_and_line(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text(SRC)
    out = annotate("- Entry point is `def load_config(path):` which opens the file", [f])
    assert "`def load_config(path):` (config.py:3)" in out


def test_ambiguous_quote_left_alone(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text(SRC)
    out = annotate("- Both use `with open(path` to read", [f])
    assert "(config.py:" not in out


def test_missing_quote_left_alone(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text(SRC)
    out = annotate("- It calls `def delete_config(path):` too", [f])
    assert out == "- It calls `def delete_config(path):` too"


def test_short_or_low_signal_spans_skipped(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text(SRC)
    assert annotate("- see `import os`", [f]) == "- see `import os`"  # under 12 chars
    assert annotate('- see `("=", 1) for `', [f]) == '- see `("=", 1) for `'  # too few alnum


def test_already_annotated_not_doubled(tmp_path: Path):
    f = tmp_path / "config.py"
    f.write_text(SRC)
    text = "- `def load_config(path):` (config.py:3)"
    assert annotate(text, [f]) == text


def test_multiple_files_use_basename_unless_ambiguous(tmp_path: Path):
    a = tmp_path / "a" / "util.py"
    b = tmp_path / "b" / "util.py"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("def alpha_function_one():\n    pass\n")
    b.write_text("def beta_function_two():\n    pass\n")
    out = annotate("- `def alpha_function_one():` and `def beta_function_two():`", [a, b])
    assert f"({a}:1)" in out
    assert f"({b}:1)" in out


def test_quote_present_in_two_files_is_ambiguous(tmp_path: Path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("shared_helper_name = 1\n")
    b.write_text("shared_helper_name = 2\n")
    out = annotate("- `shared_helper_name = ` is set", [a, b])
    assert "(a.py" not in out and "(b.py" not in out


def test_unreadable_file_ignored(tmp_path: Path):
    assert annotate("- `something long enough`", [tmp_path / "nope.py"]) == "- `something long enough`"
