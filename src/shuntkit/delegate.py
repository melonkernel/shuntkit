"""The two delegation jobs: bulk-read and code-write.

Prompt shapes follow upstream shunt: files wrapped in ``<file path=...>`` tags
followed by the question, or a spec followed by a reference file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shuntkit.config import READER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT, Config
from shuntkit.transports import Answer, Transport, TransportError


@dataclass
class DelegationResult:
    answer: Answer
    corpus_bytes: int
    files: list[Path]

    @property
    def approx_corpus_tokens(self) -> int:
        # The usual 4-characters-per-token estimate for English and code.
        return self.corpus_bytes // 4


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TransportError(f"Cannot read {path}: {exc}") from exc


def _check_files(paths: list[Path]) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        # A typo'd path would otherwise be sent as an empty block and produce a
        # confident answer about nothing. Fail loudly instead.
        raise TransportError("File not found or unreadable: " + ", ".join(missing))


def build_read_message(paths: list[Path], question: str) -> str:
    parts = []
    for path in paths:
        parts.append(f'<file path="{path}">\n{_read_text(path)}\n</file>\n')
    parts.append(f"Question: {question}\n")
    return "\n".join(parts)


def build_write_message(spec: str, reference: Path) -> str:
    return f"Spec: {spec}\n\nReference ({reference.name}):\n{_read_text(reference)}\n"


def _enforce_payload_cap(message: str, config: Config) -> None:
    size = len(message.encode("utf-8"))
    if size > config.max_payload_bytes:
        raise TransportError(
            f"Request is {size} bytes, over the {config.max_payload_bytes} byte cap. "
            "Send fewer or smaller files, or raise SHUNTKIT_MAX_PAYLOAD_BYTES."
        )


def bulk_read(transport: Transport, config: Config, paths: list[Path], question: str) -> DelegationResult:
    _check_files(paths)
    message = build_read_message(paths, question)
    _enforce_payload_cap(message, config)
    answer = transport.invoke(READER_SYSTEM_PROMPT, message)
    return DelegationResult(answer=answer, corpus_bytes=len(message.encode("utf-8")), files=paths)


def strip_fences(text: str) -> str:
    """Remove a single wrapping markdown fence if the model added one.

    Only the outermost fence goes; fences inside the code (e.g. in a
    docstring) are left alone.
    """
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.split("\n")
        if len(lines) >= 2:
            body = "\n".join(lines[1:-1])
            return body.strip("\n") + "\n"
    return text if text.endswith("\n") else text + "\n"


def code_write(transport: Transport, config: Config, spec: str, reference: Path) -> DelegationResult:
    _check_files([reference])
    message = build_write_message(spec, reference)
    _enforce_payload_cap(message, config)
    answer = transport.invoke(WRITER_SYSTEM_PROMPT, message)
    answer.text = strip_fences(answer.text)
    return DelegationResult(answer=answer, corpus_bytes=len(message.encode("utf-8")), files=[reference])
