"""Command-line entry point.

Subcommands:

* ``hook read`` / ``hook bash``: PreToolUse hooks (JSON on stdin).
* ``read``: delegate a question over files to the worker model.
* ``write``: delegate boilerplate generation to the worker model.
* ``install`` / ``uninstall``: register hooks and skills in ``~/.claude``.
* ``doctor``: check the environment.
* ``stats``: summarize recorded usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from shuntkit import __version__
from shuntkit.config import Config
from shuntkit.transports import TransportError


def _command_hint() -> str:
    """How the skills should invoke us, for use inside hook block messages."""
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        return f'PYTHONPATH="{root}/src" python3 -m shuntkit read --question "<q>" --paths <files>'
    return 'shuntkit read --question "<q>" --paths <files>'


def cmd_hook(args: argparse.Namespace) -> int:
    from shuntkit.hooks import decide_bash, decide_read, to_hook_output

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0  # Never block on malformed input.
    if not isinstance(payload, dict):
        return 0
    config = Config.from_env()
    hint = _command_hint()
    decision = (
        decide_read(payload, config, hint) if args.kind == "read" else decide_bash(payload, config, hint)
    )
    output = to_hook_output(decision)
    if output is not None:
        print(json.dumps(output))
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    from shuntkit import stats
    from shuntkit.delegate import bulk_read
    from shuntkit.transports import get_transport

    config = Config.from_env()
    if args.model:
        config = Config(**{**config.__dict__, "model": args.model})
    transport = get_transport(config)
    paths = [Path(p).expanduser() for p in args.paths]
    result = bulk_read(transport, config, paths, args.question)
    sys.stdout.write(result.answer.text.rstrip("\n") + "\n")
    stats.record(config, "read", result)
    _report(result, config)
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    from shuntkit import stats
    from shuntkit.delegate import code_write
    from shuntkit.transports import get_transport

    config = Config.from_env()
    if args.model:
        config = Config(**{**config.__dict__, "model": args.model})
    transport = get_transport(config)
    result = code_write(transport, config, args.spec, Path(args.reference).expanduser())
    if args.target:
        target = Path(args.target).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.answer.text, encoding="utf-8")
        line_count = result.answer.text.count("\n")
        print(f"Wrote {line_count} lines to {target}", file=sys.stderr)
    else:
        sys.stdout.write(result.answer.text)
    stats.record(config, "write", result)
    _report(result, config)
    return 0


def _report(result, config: Config) -> None:
    u = result.answer.usage
    cost = f" | worker cost ${u.cost_usd:.4f}" if u.cost_usd is not None else ""
    worker_in = u.input_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens
    print(
        f"[shuntkit: ~{result.approx_corpus_tokens:,} tokens kept out of context | "
        f"worker {u.model or config.model} used {worker_in:,} in / {u.output_tokens:,} out{cost}]",
        file=sys.stderr,
    )


def cmd_install(args: argparse.Namespace) -> int:
    from shuntkit.install import install

    written = install(Path(args.claude_dir).expanduser())
    print("shuntkit installed. Updated:")
    for w in written:
        print(f"  {w}")
    print("Restart Claude Code (or start a new session) for the hooks to load.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    from shuntkit.install import uninstall

    removed = uninstall(Path(args.claude_dir).expanduser())
    if removed:
        print("shuntkit removed:")
        for r in removed:
            print(f"  {r}")
    else:
        print("Nothing to remove.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from shuntkit.install import _is_ours  # noqa: PLC2701
    from shuntkit.transports import get_transport

    config = Config.from_env()
    problems: list[str] = []
    print(f"shuntkit {__version__}")
    print(f"  python:     {sys.version.split()[0]}")
    print(f"  transport:  {config.transport}")
    print(f"  model:      {config.model}")
    print(f"  min_lines:  {config.min_lines}")
    print(f"  disabled:   {config.disabled}")
    try:
        transport = get_transport(config)
        problems.extend(transport.check())
    except TransportError as exc:
        problems.append(str(exc))

    settings = Path(args.claude_dir).expanduser() / "settings.json"
    registered = False
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8") or "{}")
            registered = any(_is_ours(e) for e in data.get("hooks", {}).get("PreToolUse", []))
        except json.JSONDecodeError:
            problems.append(f"{settings} is not valid JSON.")
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if registered:
        print(f"  hooks:      registered in {settings}")
    elif plugin_root:
        print(f"  hooks:      running as plugin from {plugin_root}")
    else:
        print("  hooks:      not registered (run 'shuntkit install' or install the plugin)")

    if args.probe and not problems:
        from shuntkit.config import READER_SYSTEM_PROMPT

        print("  probe:      calling worker model...", end="", flush=True)
        try:
            answer = transport.invoke(READER_SYSTEM_PROMPT, "Reply with the single word: ready")
            u = answer.usage
            cost = f", ${u.cost_usd:.4f}" if u.cost_usd is not None else ""
            worker_in = u.input_tokens + u.cache_creation_input_tokens
            print(f" ok ({u.model or config.model}, {worker_in} in / {u.output_tokens} out{cost})")
        except TransportError as exc:
            print(" failed")
            problems.append(str(exc))

    if problems:
        print("Problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("All checks passed.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from shuntkit.stats import summarize

    config = Config.from_env()
    print(summarize(config.state_dir / "usage.jsonl"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shuntkit",
        description=(
            "Route bulk file reads and boilerplate generation from Claude Code to a cheaper Claude model."
        ),
    )
    parser.add_argument("--version", action="version", version=f"shuntkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("hook", help="PreToolUse hook (reads JSON from stdin)")
    p.add_argument("kind", choices=["read", "bash"])
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("read", help="Delegate a question over one or more files to the worker model")
    p.add_argument("--question", required=True)
    p.add_argument("--paths", nargs="+", required=True, metavar="FILE")
    p.add_argument("--model", help="Override SHUNTKIT_MODEL for this call")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("write", help="Delegate boilerplate generation to the worker model")
    p.add_argument("--spec", required=True)
    p.add_argument("--reference", required=True, metavar="FILE")
    p.add_argument("--target", metavar="FILE", help="Write output here instead of stdout")
    p.add_argument("--model", help="Override SHUNTKIT_MODEL for this call")
    p.set_defaults(func=cmd_write)

    for name, func, help_text in (
        ("install", cmd_install, "Register hooks and skills in ~/.claude"),
        ("uninstall", cmd_uninstall, "Remove what 'install' added"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--claude-dir", default="~/.claude")
        p.set_defaults(func=func)

    p = sub.add_parser("doctor", help="Check the environment")
    p.add_argument("--claude-dir", default="~/.claude")
    p.add_argument("--probe", action="store_true", help="Also make one tiny worker call")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("stats", help="Summarize recorded usage")
    p.set_defaults(func=cmd_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except TransportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
