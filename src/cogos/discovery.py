"""Agent discovery.

``discovery`` scans the local machine for installed AI agents and returns
a list of :class:`AgentHandle`. Each handle says *what* was found and
*where*; the actual reading of data is delegated to an Adapter.

The discovery layer must never hard-code behaviour for a specific agent.
Adding a new agent means writing a small probe function under
``cogos.discovery.probes`` and registering it in ``PROBES``. Nothing else
in CognitiveOS needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .paths import Paths


@dataclass(frozen=True)
class AgentHandle:
    """A discovered AI agent installation.

    ``agent_id`` is the stable name used by adapters and the wiki.
    ``paths`` are the on-disk locations relevant to this agent.
    """

    agent_id: str
    display_name: str
    version: str | None
    paths: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "version": self.version,
            "paths": {k: str(v) for k, v in self.paths.items()},
            "notes": list(self.notes),
        }


# A probe takes the shared Paths and returns zero or more AgentHandles.
Probe = Callable[[Paths], Iterable[AgentHandle]]


def discover(paths: Paths) -> list[AgentHandle]:
    """Run every registered probe and return the union of handles."""
    from . import probes  # local import: avoid cycles when probes import this module

    found: list[AgentHandle] = []
    for probe in probes.all_probes():
        try:
            for h in probe(paths):
                found.append(h)
        except Exception as exc:  # a broken probe must not kill discovery
            found.append(
                AgentHandle(
                    agent_id="<probe_error>",
                    display_name="probe error",
                    version=None,
                    notes=[f"{probe.__name__}: {exc!r}"],
                )
            )
    return found