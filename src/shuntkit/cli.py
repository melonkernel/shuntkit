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
import dataclasses
import json
import os
import sys
from pathlib import Path

from shuntkit import __version__
from shuntkit.config import HOSTS, Config
from shuntkit.transports import TransportError


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
    if args.host:
        config = dataclasses.replace(config, host=args.host)
    try:
        decision = decide_read(payload, config) if args.kind == "read" else decide_bash(payload, config)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
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
    context = [Path(p).expanduser() for p in (args.context or [])]
    result = code_write(transport, config, args.spec, Path(args.reference).expanduser(), context)
    for warning in result.warnings:
        print(f"[shuntkit warning] {warning}", file=sys.stderr)
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
    cites = f" | {result.citations_added} verified citations" if result.citations_added else ""
    print(
        f"[shuntkit: ~{result.approx_corpus_tokens:,} tokens kept out of context | "
        f"worker {u.model or config.model} used {worker_in:,} in / {u.output_tokens:,} out{cost}{cites}]",
        file=sys.stderr,
    )


def _scope_label(args: argparse.Namespace) -> str:
    where = "custom dir" if args.claude_dir else f"{args.scope} scope"
    return f"{args.host}, {where}"


def cmd_install(args: argparse.Namespace) -> int:
    from shuntkit.install import PROJECT_SCOPE, install, resolve_target

    claude_dir, default_command = resolve_target(args.scope, args.claude_dir, args.host)
    command = args.command or default_command
    written = install(claude_dir, command, args.host)
    print(f"shuntkit installed ({_scope_label(args)}). Updated:")
    for w in written:
        print(f"  {w}")
    app = "Claude Code" if args.host == "claude" else "Codex"
    if args.scope == PROJECT_SCOPE and not args.claude_dir and not args.command:
        print(
            f"Hooks call `shuntkit` by name, so it must be on PATH when {app} starts.\n"
            f"If {app} is launched from an app rather than a terminal, use:\n"
            f'  shuntkit install --host {args.host} --command "$(command -v shuntkit)"'
        )
    if args.host == "codex":
        print(
            "Codex runs hooks only after you have trusted them: open Codex here and run /hooks.\n"
            "Project hooks also need the project itself to be trusted (Codex asks on first open)."
        )
    print(f"Restart {app} (or start a new session) for the hooks to load.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    from shuntkit.install import PROJECT_SCOPE, resolve_target, uninstall

    claude_dir, _ = resolve_target(args.scope, args.claude_dir, args.host)
    removed = uninstall(claude_dir, args.host)
    if removed:
        print(f"shuntkit removed ({_scope_label(args)}):")
        for r in removed:
            print(f"  {r}")
    else:
        print(f"Nothing to remove in {claude_dir}.")
        if args.scope == PROJECT_SCOPE and not args.claude_dir:
            print(f"For a user-wide install, run: shuntkit uninstall --host {args.host} --user")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from shuntkit.install import PROJECT_SCOPE, USER_SCOPE, hooks_registered, resolve_target
    from shuntkit.transports import get_transport

    config = Config.from_env()
    problems: list[str] = []
    print(f"shuntkit {__version__}")
    print(f"  python:     {sys.version.split()[0]}")
    print(f"  transport:  {config.transport}")
    print(f"  model:      {config.model}")
    print(f"  min_lines:  {config.min_lines}")
    print(f"  budget:     {config.slice_budget_lines} lines/file/session (0 = off)")
    print(f"  delegate:   {config.delegate}")
    secrets_state = "on" if config.secret_guard else "off"
    citations_state = "on" if config.citations else "off"
    print(f"  guards:     secrets={secrets_state} citations={citations_state}")
    print(f"  state_dir:  {config.state_dir}")
    print(f"  disabled:   {config.disabled}")
    if config.delegate not in {"cli", "subagent"}:
        problems.append(f"SHUNTKIT_DELEGATE must be 'cli' or 'subagent', not '{config.delegate}'.")
    try:
        transport = get_transport(config)
        problems.extend(transport.check())
    except TransportError as exc:
        problems.append(str(exc))

    if args.claude_dir:
        candidates = [resolve_target(PROJECT_SCOPE, args.claude_dir)[0]]
    else:
        candidates = [
            resolve_target(scope, host=host)[0]
            for host in ("claude", "codex")
            for scope in (PROJECT_SCOPE, USER_SCOPE)
        ]
    registered: list[Path] = []
    for claude_dir in candidates:
        try:
            if hooks_registered(claude_dir):
                registered.append(claude_dir / "settings.json")
        except SystemExit as exc:
            problems.append(str(exc))
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if registered:
        print("  hooks:      registered in " + ", ".join(str(r) for r in registered))
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


def _add_scope_args(p: argparse.ArgumentParser) -> None:
    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--project",
        dest="scope",
        action="store_const",
        const="project",
        help="./.claude in the current directory; only this repository (default)",
    )
    scope.add_argument(
        "--user",
        dest="scope",
        action="store_const",
        const="user",
        help="~/.claude; every project on this machine",
    )
    scope.add_argument("--claude-dir", help="An explicit settings directory (.claude or .codex)")
    p.add_argument("--host", choices=list(HOSTS), default="claude", help="Coding agent (default: claude)")
    p.set_defaults(scope="project", claude_dir=None)


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
    p.add_argument("--host", choices=list(HOSTS), help="Override SHUNTKIT_HOST for this call")
    p.set_defaults(func=cmd_hook)

    p = sub.add_parser("read", help="Delegate a question over one or more files to the worker model")
    p.add_argument("--question", required=True)
    p.add_argument("--paths", nargs="+", required=True, metavar="FILE")
    p.add_argument("--model", help="Override SHUNTKIT_MODEL for this call")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("write", help="Delegate boilerplate generation to the worker model")
    p.add_argument("--spec", required=True)
    p.add_argument("--reference", required=True, metavar="FILE", help="File whose conventions to match")
    p.add_argument(
        "--context", nargs="+", metavar="FILE", help="Source files the output must be correct against"
    )
    p.add_argument("--target", metavar="FILE", help="Write output here instead of stdout")
    p.add_argument("--model", help="Override SHUNTKIT_MODEL for this call")
    p.set_defaults(func=cmd_write)

    p = sub.add_parser(
        "install",
        help="Register hooks, skills and the bulk-reader agent (./.claude by default; ~/.claude with --user)",
    )
    _add_scope_args(p)
    p.add_argument("--command", help="Override the shuntkit command written into hooks and skills")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("uninstall", help="Remove what 'install' added")
    _add_scope_args(p)
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("doctor", help="Check the environment")
    p.add_argument("--claude-dir", help="Only check this Claude settings directory for hooks")
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
