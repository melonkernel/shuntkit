from __future__ import annotations

from pathlib import Path

import pytest

from shuntkit import budget
from shuntkit.config import READER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT, Config
from shuntkit.delegate import (
    build_read_message,
    build_write_message,
    bulk_read,
    code_write,
    strip_fences,
)
from shuntkit.transports import Answer, TransportError, Usage


class FakeTransport:
    name = "fake"

    def __init__(self, reply: str = "- it adds numbers"):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def check(self):
        return []

    def invoke(self, system_prompt: str, message: str) -> Answer:
        self.calls.append((system_prompt, message))
        return Answer(text=self.reply, usage=Usage(input_tokens=10, output_tokens=5, model="fake"))


def test_read_message_wraps_files_and_question(tmp_path: Path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n")
    msg = build_read_message([a], "what is x?")
    assert f'<file path="{a}">' in msg
    assert "x = 1" in msg
    assert msg.rstrip().endswith("Question: what is x?")


def test_bulk_read_uses_reader_prompt_records_bytes_and_sanctions(tmp_path: Path, config: Config):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n" * 100)
    t = FakeTransport()
    result = bulk_read(t, config, [a], "q")
    assert t.calls[0][0] == READER_SYSTEM_PROMPT
    assert result.answer.text == "- it adds numbers"
    assert result.corpus_bytes > 600
    assert result.approx_corpus_tokens == result.corpus_bytes // 4
    assert budget.is_sanctioned(config, a)


def test_bulk_read_annotates_citations(tmp_path: Path, config: Config):
    a = tmp_path / "a.py"
    a.write_text("def compute_total(items):\n    return sum(items)\n")
    t = FakeTransport(reply="- Entry point: `def compute_total(items):`")
    result = bulk_read(t, config, [a], "q")
    assert result.answer.text == "- Entry point: `def compute_total(items):` (a.py:1)"
    assert result.citations_added == 1


def test_bulk_read_citations_can_be_disabled(tmp_path: Path, state_dir: Path):
    a = tmp_path / "a.py"
    a.write_text("def compute_total(items):\n    return sum(items)\n")
    t = FakeTransport(reply="- `def compute_total(items):`")
    result = bulk_read(t, Config(state_dir=state_dir, citations=False), [a], "q")
    assert result.answer.text == "- `def compute_total(items):`"


def test_bulk_read_missing_file_fails_loudly(tmp_path: Path, config: Config):
    with pytest.raises(TransportError, match="not found"):
        bulk_read(FakeTransport(), config, [tmp_path / "nope.py"], "q")


def test_bulk_read_duplicate_paths_rejected(tmp_path: Path, config: Config):
    a = tmp_path / "a.py"
    a.write_text("x\n")
    with pytest.raises(TransportError, match="Duplicate"):
        bulk_read(FakeTransport(), config, [a, a], "q")


def test_payload_cap(tmp_path: Path, state_dir: Path):
    a = tmp_path / "a.py"
    a.write_text("x" * 1000)
    with pytest.raises(TransportError, match="over the 500 byte cap"):
        bulk_read(FakeTransport(), Config(state_dir=state_dir, max_payload_bytes=500), [a], "q")


def test_write_uses_writer_prompt_and_strips_fence(tmp_path: Path, config: Config):
    ref = tmp_path / "ref.test.ts"
    ref.write_text("describe('ref', () => {});\n")
    t = FakeTransport(reply="```ts\nexport const x = 1;\n```")
    result = code_write(t, config, "make x", ref)
    assert t.calls[0][0] == WRITER_SYSTEM_PROMPT
    assert "Spec: make x" in t.calls[0][1]
    assert "describe('ref'" in t.calls[0][1]
    assert result.answer.text == "export const x = 1;\n"
    assert result.warnings and "--context" in result.warnings[0]


def test_write_with_context_includes_sources_and_no_warning(tmp_path: Path, config: Config):
    ref = tmp_path / "test_other.py"
    ref.write_text("def test_other(): ...\n")
    src = tmp_path / "orders.py"
    src.write_text("def cancel(order): ...\n")
    t = FakeTransport(reply="def test_cancel(): ...\n")
    result = code_write(t, config, "tests for orders", ref, [src])
    msg = t.calls[0][1]
    assert f'<file path="{src}">' in msg
    assert "def cancel(order)" in msg
    assert msg.index("def cancel(order)") < msg.index("Reference file whose conventions")
    assert result.warnings == []
    assert result.files == [ref, src]


def test_write_message_shape(tmp_path: Path):
    ref = tmp_path / "ref.py"
    ref.write_text("REF\n")
    msg = build_write_message("spec here", ref)
    assert msg.startswith("Spec: spec here\n")
    assert "Reference file whose conventions the output must match (ref.py):\nREF" in msg


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("code\n", "code\n"),
        ("code", "code\n"),
        ("```\ncode\n```", "code\n"),
        ("```python\ncode\n```\n", "code\n"),
        ("```python\na\n```inner```\nb\n```", "a\n```inner```\nb\n"),
    ],
)
def test_strip_fences(raw, expected):
    assert strip_fences(raw) == expected
