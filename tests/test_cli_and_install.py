from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from shuntkit.cli import main
from shuntkit.install import install, uninstall
from shuntkit.skills import AGENTS, PLUGIN_COMMAND, SKILLS

REPO = Path(__file__).resolve().parent.parent


def run_hook(kind: str, payload: dict, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = {**os.environ, "PYTHONPATH": str(REPO / "src"), **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "shuntkit", "hook", kind],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_hook_read_blocks_via_stdout_json(files):
    proc = run_hook("read", {"tool_input": {"file_path": str(files["large"])}})
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "1200 lines" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_read_allows_silently(files):
    proc = run_hook("read", {"tool_input": {"file_path": str(files["small"])}})
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_hook_hint_uses_plugin_root_when_set(files):
    proc = run_hook(
        "read",
        {"tool_input": {"file_path": str(files["large"])}},
        env={"CLAUDE_PLUGIN_ROOT": "/plugins/shuntkit"},
    )
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'PYTHONPATH="/plugins/shuntkit/src" python3 -m shuntkit read' in reason


def test_hook_subagent_mode_hint(files):
    proc = run_hook(
        "read",
        {"tool_input": {"file_path": str(files["large"])}},
        env={"SHUNTKIT_DELEGATE": "subagent", "CLAUDE_PLUGIN_ROOT": "/plugins/shuntkit"},
    )
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert 'subagent_type "shuntkit:bulk-reader"' in reason


def test_hook_bash_blocks(files):
    proc = run_hook("bash", {"tool_input": {"command": f"cat {files['large']}"}})
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_malformed_input_allows():
    proc = run_hook("read", {})
    assert proc.returncode == 0
    proc2 = subprocess.run(
        [sys.executable, "-m", "shuntkit", "hook", "read"],
        input="not json",
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc2.returncode == 0
    assert proc2.stdout == ""


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "shuntkit" in capsys.readouterr().out


def test_install_and_uninstall_roundtrip(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    settings = claude_dir / "settings.json"
    claude_dir.mkdir()
    settings.write_text(
        json.dumps({"theme": "dark", "hooks": {"PreToolUse": [{"matcher": "Edit", "hooks": []}]}})
    )

    written = install(claude_dir, command="/opt/bin/shuntkit")
    data = json.loads(settings.read_text())
    assert data["theme"] == "dark"
    matchers = [e["matcher"] for e in data["hooks"]["PreToolUse"]]
    assert matchers == ["Edit", "Read", "Bash"]
    assert data["hooks"]["PreToolUse"][1]["hooks"][0]["command"] == "/opt/bin/shuntkit hook read"
    assert (claude_dir / "skills" / "bulk-reader" / "SKILL.md").is_file()
    assert (claude_dir / "skills" / "code-writer" / "SKILL.md").is_file()
    assert (claude_dir / "agents" / "bulk-reader.md").is_file()
    assert "/opt/bin/shuntkit read" in (claude_dir / "skills" / "bulk-reader" / "SKILL.md").read_text()
    assert len(written) == 4

    # Idempotent: a second install does not duplicate entries.
    install(claude_dir, command="/opt/bin/shuntkit")
    assert [e["matcher"] for e in json.loads(settings.read_text())["hooks"]["PreToolUse"]] == [
        "Edit",
        "Read",
        "Bash",
    ]

    removed = uninstall(claude_dir)
    data = json.loads(settings.read_text())
    assert [e["matcher"] for e in data["hooks"]["PreToolUse"]] == ["Edit"]
    assert not (claude_dir / "skills" / "bulk-reader").exists()
    assert not (claude_dir / "agents" / "bulk-reader.md").exists()
    assert len(removed) == 4


def test_install_quotes_paths_with_spaces(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    install(claude_dir, command="/Users/me/my tools/shuntkit")
    data = json.loads((claude_dir / "settings.json").read_text())
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == '"/Users/me/my tools/shuntkit" hook read'
    uninstall(claude_dir)
    assert json.loads((claude_dir / "settings.json").read_text()) == {}


def test_install_into_empty_dir(tmp_path: Path):
    claude_dir = tmp_path / ".claude"
    install(claude_dir, command="shuntkit")
    data = json.loads((claude_dir / "settings.json").read_text())
    assert [e["matcher"] for e in data["hooks"]["PreToolUse"]] == ["Read", "Bash"]
    uninstall(claude_dir)
    assert json.loads((claude_dir / "settings.json").read_text()) == {}


def test_resolve_target_scopes(tmp_path: Path, monkeypatch):
    from shuntkit.install import PROJECT_SCOPE, USER_SCOPE, resolve_target

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    project_dir, project_cmd = resolve_target(PROJECT_SCOPE)
    assert project_dir == tmp_path / ".claude"
    assert project_cmd == "shuntkit", "project installs are committed, so the command must be portable"

    user_dir, user_cmd = resolve_target(USER_SCOPE)
    assert user_dir == Path.home() / ".claude"
    assert Path(user_cmd).is_absolute() or user_cmd == "shuntkit"

    explicit_dir, _ = resolve_target(PROJECT_SCOPE, str(tmp_path / "elsewhere"))
    assert explicit_dir == tmp_path / "elsewhere"

    with pytest.raises(ValueError):
        resolve_target("global")


def test_cli_install_defaults_to_project_scope(tmp_path: Path, monkeypatch, capsys):
    from shuntkit.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert main(["install"]) == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "shuntkit hook read"
    assert (tmp_path / ".claude" / "skills" / "bulk-reader" / "SKILL.md").is_file()
    assert not (tmp_path / "home" / ".claude").exists()
    out = capsys.readouterr().out
    assert "project scope" in out
    assert "must be on PATH" in out

    assert main(["uninstall"]) == 0
    assert json.loads((tmp_path / ".claude" / "settings.json").read_text()) == {}


def test_cli_install_user_scope(tmp_path: Path, monkeypatch, capsys):
    from shuntkit.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    assert main(["install", "--user", "--command", "/opt/bin/shuntkit"]) == 0
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_text())
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/opt/bin/shuntkit hook read"
    assert not (tmp_path / ".claude").exists()
    assert "user scope" in capsys.readouterr().out

    # Default-scope uninstall does not touch the user install, and says where to look.
    assert main(["uninstall"]) == 0
    assert "shuntkit uninstall --host claude --user" in capsys.readouterr().out
    assert (tmp_path / "home" / ".claude" / "agents" / "bulk-reader.md").is_file()

    assert main(["uninstall", "--user"]) == 0
    assert not (tmp_path / "home" / ".claude" / "agents" / "bulk-reader.md").exists()


def test_cli_install_codex_host(tmp_path: Path, monkeypatch, capsys):
    from shuntkit.cli import main
    from shuntkit.install import hooks_registered

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    hooks_path = tmp_path / ".codex" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "apply_patch", "hooks": []}]}}))

    assert main(["install", "--host", "codex"]) == 0
    data = json.loads(hooks_path.read_text())
    matchers = [e["matcher"] for e in data["hooks"]["PreToolUse"]]
    assert matchers == ["apply_patch", "Bash"], "only the Bash hook applies: Codex has no Read tool"
    assert data["hooks"]["PreToolUse"][1]["hooks"][0]["command"] == "shuntkit hook bash --host codex"
    assert not (tmp_path / ".codex" / "skills").exists()
    assert not (tmp_path / ".claude").exists()
    assert hooks_registered(tmp_path / ".codex")
    out = capsys.readouterr().out
    assert "/hooks" in out, "the user must trust the hook inside Codex; the install cannot"

    # Idempotent.
    assert main(["install", "--host", "codex"]) == 0
    assert [e["matcher"] for e in json.loads(hooks_path.read_text())["hooks"]["PreToolUse"]] == [
        "apply_patch",
        "Bash",
    ]

    assert main(["uninstall", "--host", "codex"]) == 0
    assert [e["matcher"] for e in json.loads(hooks_path.read_text())["hooks"]["PreToolUse"]] == [
        "apply_patch"
    ]
    assert not hooks_registered(tmp_path / ".codex")


def test_cli_uninstall_codex_removes_empty_hooks_file(tmp_path: Path, monkeypatch):
    from shuntkit.cli import main

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert main(["install", "--host", "codex", "--user"]) == 0
    hooks_path = tmp_path / "home" / ".codex" / "hooks.json"
    assert hooks_path.is_file()
    assert main(["uninstall", "--host", "codex", "--user"]) == 0
    assert not hooks_path.exists()


def test_hook_host_flag_changes_wording(files, capsys):
    from shuntkit.cli import main

    payload = {"tool_name": "Bash", "session_id": "s", "tool_input": {"command": f"cat {files['large']}"}}
    import io
    import sys as _sys

    _sys.stdin = io.StringIO(json.dumps(payload))
    assert main(["hook", "bash", "--host", "codex"]) == 0
    out = json.loads(capsys.readouterr().out)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "sed -n" in reason
    assert "skill" not in reason and "Agent tool" not in reason
    assert 'shuntkit read --question "<q>" --paths <files>' in reason


def test_cli_rejects_conflicting_scope_flags(tmp_path: Path, monkeypatch):
    from shuntkit.cli import main

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["install", "--user", "--claude-dir", str(tmp_path)])


def test_repo_skills_are_rendered_from_templates():
    """The checked-in plugin skills must match the templates in skills.py."""
    for name, render in SKILLS.items():
        on_disk = (REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert on_disk == render(PLUGIN_COMMAND), (
            f"skills/{name}/SKILL.md is stale; run scripts/render-skills.py"
        )


def test_repo_agents_are_rendered_from_templates():
    for name, render in AGENTS.items():
        on_disk = (REPO / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert on_disk == render(), f"agents/{name}.md is stale; run scripts/render-skills.py"


def test_agent_frontmatter_is_haiku_and_read_only():
    text = (REPO / "agents" / "bulk-reader.md").read_text()
    assert "\nmodel: haiku\n" in text
    assert "\ntools: Read, Glob, Grep\n" in text
    assert "disallowedTools: Agent" in text


def test_plugin_hooks_json_points_at_module():
    data = json.loads((REPO / "hooks" / "hooks.json").read_text())
    entries = data["hooks"]["PreToolUse"]
    assert [e["matcher"] for e in entries] == ["Read", "Bash"]
    for e, kind in zip(entries, ["read", "bash"]):
        cmd = e["hooks"][0]["command"]
        assert cmd == f"{PLUGIN_COMMAND} hook {kind}"


def test_plugin_manifest_matches_version():
    from shuntkit import __version__

    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text())
    marketplace = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    assert plugin["version"] == __version__
    assert marketplace["plugins"][0]["version"] == __version__
    assert plugin["name"] == "shuntkit"
    # agents/ at the plugin root is auto-discovered; an explicit key fails validation.
    assert "agents" not in plugin
    assert (REPO / "agents" / "bulk-reader.md").is_file()
