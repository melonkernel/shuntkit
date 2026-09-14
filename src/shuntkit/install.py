"""Register shuntkit hooks and skills for a pip install (no plugin marketplace).

``shuntkit install`` adds two PreToolUse entries to ``~/.claude/settings.json``
and writes the two SKILL.md files to ``~/.claude/skills``. ``shuntkit
uninstall`` removes exactly what it added. Both are idempotent.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from shuntkit.skills import INSTALLED_COMMAND, SKILLS

MARKER = "shuntkit hook"


def hook_entries(command: str = INSTALLED_COMMAND) -> list[dict]:
    return [
        {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": f"{command} hook read", "timeout": 10}],
        },
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": f"{command} hook bash", "timeout": 10}],
        },
    ]


def _is_ours(entry: dict) -> bool:
    for hook in entry.get("hooks", []):
        cmd = hook.get("command", "")
        if cmd.startswith(f"{INSTALLED_COMMAND} hook ") or "-m shuntkit hook" in cmd:
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


def install(claude_dir: Path, command: str = INSTALLED_COMMAND) -> list[str]:
    settings_path = claude_dir / "settings.json"
    settings = _load_settings(settings_path)
    hooks = settings.setdefault("hooks", {})
    pre = [e for e in hooks.get("PreToolUse", []) if not _is_ours(e)]
    pre.extend(hook_entries(command))
    hooks["PreToolUse"] = pre
    _save_settings(settings_path, settings)

    written = [str(settings_path)]
    for name, render in SKILLS.items():
        skill_dir = claude_dir / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        target = skill_dir / "SKILL.md"
        target.write_text(render(command), encoding="utf-8")
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
    return removed
