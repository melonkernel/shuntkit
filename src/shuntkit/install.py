"""Register shuntkit hooks, skills and the bulk-reader agent for a pip install.

``shuntkit install`` adds two PreToolUse entries to a ``settings.json``, writes
the SKILL.md files to ``skills/`` and the agent to ``agents/`` under one Claude
settings directory. ``shuntkit uninstall`` removes exactly what it added. Both
are idempotent.

Two hosts:

- ``claude`` (default): Claude Code. Hooks go into ``settings.json``, skills
  into ``skills/`` and the agent into ``agents/``.
- ``codex``: Codex CLI. Only the Bash hook applies (Codex has no Read tool)
  and it goes into ``hooks.json``. Codex runs hooks only after the user has
  trusted them with ``/hooks``; project hooks also need a trusted project.
  Codex plugins cannot ship hooks, so there is no plugin form for Codex.

Two scopes:

- ``project`` (default): ``./.claude`` in the current directory. Only that
  repository gets the hooks. The files are meant to be committed, so the hook
  command is the bare ``shuntkit`` name, which must be on ``PATH`` when Claude
  Code starts.
- ``user``: ``~/.claude``. Every project on the machine gets the hooks. The
  hook command is the absolute path of the executable, because hooks run in a
  non-login shell where ``~/.local/bin`` (uv, pipx) is often not on ``PATH``.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
from pathlib import Path

from shuntkit.config import DEFAULT_HOST, HOSTS
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


PROJECT_SCOPE = "project"
USER_SCOPE = "user"


def resolve_target(scope: str, claude_dir: str | None = None, host: str = DEFAULT_HOST) -> tuple[Path, str]:
    """The settings directory and default hook command for a scope and host.

    An explicit ``claude_dir`` wins over the scope and behaves like a user
    install (absolute command path).
    """
    if host not in HOSTS:
        raise ValueError(f"unknown host: {host!r}")
    dirname = ".claude" if host == "claude" else ".codex"
    if claude_dir:
        return Path(claude_dir).expanduser(), resolve_command()
    if scope == USER_SCOPE:
        return Path.home() / dirname, resolve_command()
    if scope == PROJECT_SCOPE:
        return Path.cwd() / dirname, INSTALLED_COMMAND
    raise ValueError(f"unknown install scope: {scope!r}")


def hooks_registered(claude_dir: Path) -> bool:
    """True if ``settings.json`` (Claude Code) or ``hooks.json`` (Codex) in the
    directory carries shuntkit's PreToolUse hooks."""
    for name in ("settings.json", "hooks.json"):
        path = claude_dir / name
        if path.is_file():
            settings = _load_settings(path)
            if any(_is_ours(e) for e in settings.get("hooks", {}).get("PreToolUse", [])):
                return True
    return False


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


def codex_hook_entries(command: str) -> list[dict]:
    cmd = command if " " not in command else f'"{command}"'
    return [
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": f"{cmd} hook bash --host codex", "timeout": 10}],
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


def install(claude_dir: Path, command: str | None = None, host: str = DEFAULT_HOST) -> list[str]:
    command = command or resolve_command()
    if host == "codex":
        return _install_codex(claude_dir, command)
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


def _install_codex(codex_dir: Path, command: str) -> list[str]:
    hooks_path = codex_dir / "hooks.json"
    data = _load_settings(hooks_path)
    hooks = data.setdefault("hooks", {})
    pre = [e for e in hooks.get("PreToolUse", []) if not _is_ours(e)]
    pre.extend(codex_hook_entries(command))
    hooks["PreToolUse"] = pre
    _save_settings(hooks_path, data)
    return [str(hooks_path)]


def _uninstall_codex(codex_dir: Path) -> list[str]:
    hooks_path = codex_dir / "hooks.json"
    if not hooks_path.is_file():
        return []
    data = _load_settings(hooks_path)
    hooks = data.get("hooks", {})
    before = hooks.get("PreToolUse", [])
    after = [e for e in before if not _is_ours(e)]
    if len(after) == len(before):
        return []
    if after:
        hooks["PreToolUse"] = after
    else:
        hooks.pop("PreToolUse", None)
    if not hooks:
        data.pop("hooks", None)
    if data:
        _save_settings(hooks_path, data)
    else:
        hooks_path.unlink()  # an empty hooks.json has no reason to exist
    return [f"{hooks_path} (hooks)"]


def uninstall(claude_dir: Path, host: str = DEFAULT_HOST) -> list[str]:
    if host == "codex":
        return _uninstall_codex(claude_dir)
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
