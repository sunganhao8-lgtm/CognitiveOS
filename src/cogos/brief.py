"""Butler briefing.

When you install a new AI agent (a "butler") or move to a new machine,
the butler needs to be told who you are, what you care about, and what
is forbidden territory.

``brief`` reads the protocol-neutral ``user/manifest.md`` and renders it
into a form the *current* agent can ingest directly:

* ``--agent hermes``    -> a single shell command you paste into the
  terminal (sets up a session and pipes the manifest in)
* ``--agent codex``     -> a project doc Codex can `cat`
* ``--agent claude``    -> a Claude Code system prompt prefix
* ``--agent raw``       -> the bare manifest text, in case you want to
  hand-paste it somewhere

The agent-specific wrappers are deliberately trivial. The intelligence
lives in the manifest; the wrappers are just plumbing.
"""

from __future__ import annotations

from pathlib import Path

from .user import UserLayer


HEADER = (
    "[Briefing: you are being installed as the user's AI butler. "
    "Read everything below as your induction. The user will NOT repeat it.]"
)


def render_brief(user: UserLayer, agent: str) -> str:
    manifest = (user.root / "manifest.md").read_text(encoding="utf-8")
    preferences = (user.preferences).read_text(encoding="utf-8") if user.preferences.exists() else ""
    style = (user.style).read_text(encoding="utf-8") if user.style.exists() else ""

    body = "\n\n---\n\n## PREFERENCES\n\n" + preferences + "\n\n---\n\n## STYLE\n\n" + style + "\n\n---\n\n## MASTER MANIFEST\n\n" + manifest

    agent = agent.lower()
    if agent == "raw":
        return HEADER + "\n\n" + body + "\n"

    if agent == "hermes":
        # Hermes accepts a prompt via `hermes chat -q "..."`. We keep the
        # brief on one line with escaped newlines so the user can paste
        # the whole command into any terminal unchanged.
        one_line = body.replace("\n", " \\n ").replace('"', '\\"')
        return (
            "# Paste this single command into your terminal to give Hermes the induction:\n"
            "\n"
            f'hermes chat -q "{HEADER} {one_line}"\n'
        )

    if agent == "codex":
        target = user.root.parent / "AGENTS.md"
        return (
            f"# Codex reads project docs from {target}.\n"
            f"# Append the brief to that file:\n\n"
            f"cat >> {target} <<'COGOS_BRIEF_EOF'\n"
            f"{HEADER}\n\n{body}\nCOGOS_BRIEF_EOF\n"
        )

    if agent == "claude":
        target = user.root.parent / "CLAUDE.md"
        return (
            f"# Claude Code reads {target}.\n"
            f"# Append the brief:\n\n"
            f"cat >> {target} <<'COGOS_BRIEF_EOF'\n"
            f"{HEADER}\n\n{body}\nCOGOS_BRIEF_EOF\n"
        )

    raise ValueError(f"unknown agent: {agent!r}; choose one of: raw, hermes, codex, claude")