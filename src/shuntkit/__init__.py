"""shuntkit: route bulk file reads and boilerplate generation from Claude Code to a cheaper Claude model.

A vendor-free port of the ``shunt`` plugin from ``spotify/portal-ai-plugins``.
The hooks are the same idea; the transport talks to the Claude CLI or the
Anthropic API directly instead of Spotify's Portal backend.
"""

__version__ = "0.1.0"
