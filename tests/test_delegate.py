from __future__ import annotations

from pathlib import Path

import pytest

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


def test_bulk_read_uses_reader_prompt_and_records_bytes(tmp_path: Path):
    a = tmp_path / "a.py"
    a.write_text("x = 1\n" * 100)
    t = FakeTransport()
    result = bulk_read(t, Config(), [a], "q")
    assert t.calls[0][0] == READER_SYSTEM_PROMPT
    assert result.answer.text == "- it adds numbers"
    assert result.corpus_bytes > 600
    assert result.approx_corpus_tokens == result.corpus_bytes // 4


def test_bulk_read_missing_file_fails_loudly(tmp_path: Path):
    with pytest.raises(TransportError, match="not found"):
        bulk_read(FakeTransport(), Config(), [tmp_path / "nope.py"], "q")


def test_payload_cap(tmp_path: Path):
    a = tmp_path / "a.py"
    a.write_text("x" * 1000)
    with pytest.raises(TransportError, match="over the 500 byte cap"):
        bulk_read(FakeTransport(), Config(max_payload_bytes=500), [a], "q")


def test_write_message_and_prompt(tmp_path: Path):
    ref = tmp_path / "ref.test.ts"
    ref.write_text("describe('ref', () => {});\n")
    t = FakeTransport(reply="```ts\nexport const x = 1;\n```")
    result = code_write(t, Config(), "make x", ref)
    assert t.calls[0][0] == WRITER_SYSTEM_PROMPT
    assert "Spec: make x" in t.calls[0][1]
    assert "describe('ref'" in t.calls[0][1]
    assert result.answer.text == "export const x = 1;\n"


def test_write_message_shape(tmp_path: Path):
    ref = tmp_path / "ref.py"
    ref.write_text("REF\n")
    msg = build_write_message("spec here", ref)
    assert msg.startswith("Spec: spec here\n\nReference (ref.py):\nREF")


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
