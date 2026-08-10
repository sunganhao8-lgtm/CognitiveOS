"""Discovery probes.

Each probe looks for one specific AI agent on the local machine. Probes
are intentionally tiny: if a probe would need more than ~30 lines to
locate an agent, the rest belongs in an Adapter.
"""

from __future__ import annotations

import os
from pathlib import Path

from cogos.discovery import AgentHandle, Probe
from cogos.paths import Paths


def _hermes_home() -> Path | None:
    """Locate the Hermes installation directory.

    Hermes follows the convention documented in its own README:
    ``%LOCALAPPDATA%\\hermes`` on Windows, ``~/.local/share/hermes``
    elsewhere, or whatever ``HERMES_HOME`` points to.
    """

    env = os.environ.get("HERMES_HOME")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None

    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidate = Path(local_app) / "hermes"
        if candidate.exists():
            return candidate

    home = Path.home()
    for candidate in (
        home / ".local" / "share" / "hermes",
        home / ".hermes",
    ):
        if candidate.exists():
            return candidate
    return None


def probe_hermes(paths: Paths) -> list[AgentHandle]:
    home = _hermes_home()
    if home is None:
        return []

    profiles_dir = home / "profiles"
    profiles = (
        sorted(p.name for p in profiles_dir.iterdir() if p.is_dir())
        if profiles_dir.exists()
        else []
    )

    return [
        AgentHandle(
            agent_id="hermes",
            display_name="Hermes Agent",
            version=None,
            paths={
                "home": home,
                "skills": home / "skills",
                "profiles": profiles_dir,
                "config": home / "config.yaml",
            },
            notes=[f"profiles: {', '.join(profiles) or '(none)'}"] if profiles else [],
        )
    ]


PROBES: list[Probe] = [probe_hermes]


def all_probes() -> list[Probe]:
    return list(PROBES)