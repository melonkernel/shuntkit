"""Per-session slice budget and per-file sanctions.

Without this, a blocked whole-file read can be reassembled from many small
``offset``/``limit`` reads, defeating the point. The hook charges every
targeted read against a per-(session, file) budget. Once the budget is spent,
further slices of that file are blocked until the file has been delegated once
("sanctioned"). A sanction lasts ``sanction_ttl_seconds`` so that the normal
flow, delegate first and then take targeted reads for editing, is never
interrupted.

State lives under ``<state_dir>/slices/<session_id>.json`` and ``<state_dir>/sanctions.json``.
All I/O is best-effort: any failure means "allow".
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from shuntkit.config import Config

_SESSION_RE = re.compile(r"[^A-Za-z0-9_.-]")
_MAX_SESSION_FILES = 200
_SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class SliceState:
    total: int
    budget: int
    sanctioned: bool

    @property
    def exceeded(self) -> bool:
        return self.budget > 0 and self.total > self.budget and not self.sanctioned


def _read_json(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _session_file(config: Config, session_id: str | None) -> Path:
    safe = _SESSION_RE.sub("_", session_id or "unknown")[:120] or "unknown"
    return config.state_dir / "slices" / f"{safe}.json"


def _sanctions_file(config: Config) -> Path:
    return config.state_dir / "sanctions.json"


def _key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _prune_sessions(directory: Path) -> None:
    try:
        files = list(directory.glob("*.json"))
    except OSError:
        return
    if len(files) <= _MAX_SESSION_FILES:
        return
    cutoff = time.time() - _SESSION_MAX_AGE_SECONDS
    for f in files:
        with contextlib.suppress(OSError):
            if f.stat().st_mtime < cutoff:
                f.unlink()


def is_sanctioned(config: Config, path: Path) -> bool:
    entry = _read_json(_sanctions_file(config)).get(_key(path))
    if not isinstance(entry, (int, float)):
        return False
    return time.time() - float(entry) <= config.sanction_ttl_seconds


def sanction(config: Config, paths: list[Path]) -> None:
    """Record that these files were delegated. Best-effort."""
    try:
        target = _sanctions_file(config)
        data = _read_json(target)
        now = time.time()
        # Drop expired entries while we are here.
        data = {
            k: v
            for k, v in data.items()
            if isinstance(v, (int, float)) and now - v <= config.sanction_ttl_seconds
        }
        for p in paths:
            data[_key(p)] = now
        _write_json(target, data)
    except OSError:
        pass


def charge_slice(config: Config, session_id: str | None, path: Path, lines: int) -> SliceState:
    """Add ``lines`` to the session's tally for ``path`` and report the state.

    The charge is recorded even when the result is "exceeded", so repeated
    attempts keep the tally honest.
    """
    budget = config.slice_budget_lines
    if budget <= 0:
        return SliceState(total=0, budget=0, sanctioned=True)
    sanctioned = is_sanctioned(config, path)
    try:
        target = _session_file(config, session_id)
        data = _read_json(target)
        key = _key(path)
        total = int(data.get(key) or 0) + max(int(lines), 0)
        data[key] = total
        _write_json(target, data)
        _prune_sessions(target.parent)
    except (OSError, ValueError):
        return SliceState(total=0, budget=budget, sanctioned=True)
    return SliceState(total=total, budget=budget, sanctioned=sanctioned)
