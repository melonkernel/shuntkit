"""Register shuntkit hooks, skills and the bulk-reader agent for a pip install.

``shuntkit install`` adds two PreToolUse entries to ``~/.claude/settings.json``,
writes the SKILL.md files to ``~/.claude/skills`` and the agent to
``~/.claude/agents``. ``shuntkit uninstall`` removes exactly what it added.
Both are idempotent.

The hook command is written with the absolute path of the ``shuntkit``
executable. Hooks run in a non-login shell, where ``~/.local/bin`` (uv, pipx)
is often not on ``PATH``.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
from pathlib import Path

from shuntkit.skills import AGENTS, INSTALLED_COMMAND, SKILLS


def resolve_command() -> str:
    """Absolute path to the ``shuntkit`` console script, or the bare name."""
    candidates = [
        Path(sys.argv[0]) if sys.argv and sys.argv[0] else None,
        Path(sys.executable).with_name(INSTALLED_COMMAND) if sys.executable else None,
    ]
    for c in candidates:
        if c and c.name == INSTALLED_COMMAND and c.is_file():
            return str(c.resolve())
    found = shutil.which(INSTALLED_COMMAND)
    return str(Path(found).resolve()) if found else INSTALLED_COMMAND


def hook_entries(command: str) -> list[dict]:
    cmd = command if " " not in command else f'"{command}"'
    return [
        {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": f"{cmd} hook read", "timeout": 10}],
        },
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": f"{cmd} hook bash", "timeout": 10}],
        },
    ]


def _is_ours(entry: dict) -> bool:
    for hook in entry.get("hooks", []):
        cmd = str(hook.get("command", ""))
        if "shuntkit hook " in cmd or 'shuntkit" hook ' in cmd or "-m shuntkit hook" in cmd:
            return True
    return False


def _load_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON; fix it before installing: {exc}") from exc


def _save_settings(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install(claude_dir: Path, command: str | None = None) -> list[str]:
    command = command or resolve_command()
    settings_path = claude_dir / "settings.json"
    settings = _load_settings(settings_path)
    hooks = settings.setdefault("hooks", {})
    pre = [e for e in hooks.get("PreToolUse", []) if not _is_ours(e)]
    pre.extend(hook_entries(command))
    hooks["PreToolUse"] = pre
    _save_settings(settings_path, settings)

    skill_command = command if " " not in command else f'"{command}"'
    written = [str(settings_path)]
    for name, render in SKILLS.items():
        target = claude_dir / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(skill_command), encoding="utf-8")
        written.append(str(target))
    for name, render_agent in AGENTS.items():
        target = claude_dir / "agents" / f"{name}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_agent(), encoding="utf-8")
        written.append(str(target))
    return written


def uninstall(claude_dir: Path) -> list[str]:
    removed: list[str] = []
    settings_path = claude_dir / "settings.json"
    if settings_path.is_file():
        settings = _load_settings(settings_path)
        hooks = settings.get("hooks", {})
        before = hooks.get("PreToolUse", [])
        after = [e for e in before if not _is_ours(e)]
        if len(after) != len(before):
            if after:
                hooks["PreToolUse"] = after
            else:
                hooks.pop("PreToolUse", None)
            if not hooks:
                settings.pop("hooks", None)
            _save_settings(settings_path, settings)
            removed.append(f"{settings_path} (hooks)")
    for name in SKILLS:
        target = claude_dir / "skills" / name / "SKILL.md"
        if target.is_file():
            target.unlink()
            removed.append(str(target))
            with contextlib.suppress(OSError):
                target.parent.rmdir()
    for name in AGENTS:
        target = claude_dir / "agents" / f"{name}.md"
        if target.is_file():
            target.unlink()
            removed.append(str(target))
    return removed
