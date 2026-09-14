"""Append-only usage log and a small summary.

Every delegation appends one JSON line to ``<state_dir>/usage.jsonl``. The
summary reports what was measured: bytes kept out of the parent context and
what the worker actually cost. It does not invent a "dollars saved" figure,
because the parent model's price depends on the user's plan.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from shuntkit.config import Config
from shuntkit.delegate import DelegationResult


def record(config: Config, kind: str, result: DelegationResult) -> None:
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "kind": kind,
            "files": [str(p) for p in result.files],
            "corpus_bytes": result.corpus_bytes,
            "approx_corpus_tokens": result.approx_corpus_tokens,
            "worker_model": result.answer.usage.model,
            "worker_input_tokens": result.answer.usage.input_tokens
            + result.answer.usage.cache_read_input_tokens
            + result.answer.usage.cache_creation_input_tokens,
            "worker_output_tokens": result.answer.usage.output_tokens,
            "worker_cost_usd": result.answer.usage.cost_usd,
            "duration_ms": result.answer.usage.duration_ms,
        }
        with (config.state_dir / "usage.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        # Stats are best-effort; never fail a delegation over them.
        pass


def summarize(path: Path) -> str:
    if not path.is_file():
        return f"No usage recorded yet ({path})."
    n = 0
    corpus_tokens = 0
    worker_in = 0
    worker_out = 0
    cost = 0.0
    cost_known = True
    by_kind: dict[str, int] = {}
    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            n += 1
            by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
            corpus_tokens += int(e.get("approx_corpus_tokens") or 0)
            worker_in += int(e.get("worker_input_tokens") or 0)
            worker_out += int(e.get("worker_output_tokens") or 0)
            c = e.get("worker_cost_usd")
            if c is None:
                cost_known = False
            else:
                cost += float(c)
    if n == 0:
        return f"No usage recorded yet ({path})."
    kinds = ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items()))
    lines = [
        f"shuntkit usage ({path})",
        f"  delegations:                 {n}  ({kinds})",
        f"  kept out of parent context:  ~{corpus_tokens:,} tokens",
        f"  worker input tokens:         {worker_in:,}",
        f"  worker output tokens:        {worker_out:,}",
    ]
    if cost_known:
        lines.append(f"  worker cost:                 ${cost:.4f}")
    else:
        lines.append("  worker cost:                 (not reported by transport)")
    return "\n".join(lines)
