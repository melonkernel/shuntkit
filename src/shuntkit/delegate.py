"""The two delegation jobs: bulk-read and code-write.

Prompt shapes follow upstream shunt: files wrapped in ``<file path=...>`` tags
followed by the question, or a spec followed by a reference file. On top of
that, this module runs the secret guard before anything leaves the machine,
attaches verified line numbers to the worker's quotes, and records a
sanction for delegated files so the slice budget relaxes for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shuntkit import budget, citations, secrets
from shuntkit.config import READER_SYSTEM_PROMPT, WRITER_SYSTEM_PROMPT, Config
from shuntkit.transports import Answer, Transport, TransportError


@dataclass
class DelegationResult:
    answer: Answer
    corpus_bytes: int
    files: list[Path]
    citations_added: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def approx_corpus_tokens(self) -> int:
        # The usual 4-characters-per-token estimate for English and code.
        return self.corpus_bytes // 4


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TransportError(f"Cannot read {path}: {exc}") from exc


def _check_files(paths: list[Path], config: Config) -> None:
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        # A typo'd path would otherwise be sent as an empty block and produce a
        # confident answer about nothing. Fail loudly instead.
        raise TransportError("File not found or unreadable: " + ", ".join(missing))
    seen = set()
    dupes = [str(p) for p in paths if p.resolve() in seen or seen.add(p.resolve())]  # type: ignore[func-returns-value]
    if dupes:
        raise TransportError("Duplicate paths: " + ", ".join(dupes))
    if config.secret_guard:
        reasons = secrets.find_secrets(paths)
        if reasons:
            raise TransportError(
                "Refusing to send likely secrets to the worker model:\n  "
                + "\n  ".join(reasons)
                + "\nRead these files directly if you must, or set SHUNTKIT_SECRET_GUARD=off."
            )


def _file_blocks(paths: list[Path]) -> str:
    return "\n".join(f'<file path="{path}">\n{_read_text(path)}\n</file>\n' for path in paths)


def build_read_message(paths: list[Path], question: str) -> str:
    return _file_blocks(paths) + f"\nQuestion: {question}\n"


def build_write_message(spec: str, reference: Path, context: list[Path] | None = None) -> str:
    parts = [f"Spec: {spec}\n"]
    if context:
        parts.append(
            "Source files the output must be correct against (read these for actual "
            "names, signatures and values):\n" + _file_blocks(context)
        )
    parts.append(
        f"Reference file whose conventions the output must match ({reference.name}):\n"
        + _read_text(reference)
    )
    return "\n".join(parts).rstrip("\n") + "\n"


def _enforce_payload_cap(message: str, config: Config) -> None:
    size = len(message.encode("utf-8"))
    if size > config.max_payload_bytes:
        raise TransportError(
            f"Request is {size} bytes, over the {config.max_payload_bytes} byte cap. "
            "Send fewer or smaller files, or raise SHUNTKIT_MAX_PAYLOAD_BYTES."
        )


def bulk_read(transport: Transport, config: Config, paths: list[Path], question: str) -> DelegationResult:
    _check_files(paths, config)
    message = build_read_message(paths, question)
    _enforce_payload_cap(message, config)
    answer = transport.invoke(READER_SYSTEM_PROMPT, message)
    added = 0
    if config.citations:
        before = answer.text
        answer.text = citations.annotate(answer.text, paths)
        added = (
            answer.text.count("`) (") + answer.text.count("` (") - before.count("`) (") - before.count("` (")
        )
    budget.sanction(config, paths)
    return DelegationResult(
        answer=answer,
        corpus_bytes=len(message.encode("utf-8")),
        files=paths,
        citations_added=max(added, 0),
    )


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


def code_write(
    transport: Transport,
    config: Config,
    spec: str,
    reference: Path,
    context: list[Path] | None = None,
) -> DelegationResult:
    context = context or []
    _check_files([reference, *context], config)
    message = build_write_message(spec, reference, context)
    _enforce_payload_cap(message, config)
    answer = transport.invoke(WRITER_SYSTEM_PROMPT, message)
    answer.text = strip_fences(answer.text)
    warnings = []
    if not context:
        warnings.append(
            "No --context files given: the worker saw only the reference file's style, not the "
            "code the output is about. Values, names and signatures may be invented. Pass the "
            "source under test with --context."
        )
    return DelegationResult(
        answer=answer,
        corpus_bytes=len(message.encode("utf-8")),
        files=[reference, *context],
        warnings=warnings,
    )
