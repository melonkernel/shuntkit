#!/usr/bin/env python3
"""Render skills/*/SKILL.md and agents/*.md from the templates in shuntkit.skills.

Run after editing src/shuntkit/skills.py. A test fails when they drift.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from shuntkit.skills import AGENTS, PLUGIN_COMMAND, SKILLS  # noqa: E402

for name, render in SKILLS.items():
    target = REPO / "skills" / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(PLUGIN_COMMAND), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)}")

for name, render_agent in AGENTS.items():
    target = REPO / "agents" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_agent(), encoding="utf-8")
    print(f"wrote {target.relative_to(REPO)}")
