"""Agent adapters.

An Adapter is the only thing in CognitiveOS that knows the *internal*
layout of a specific agent. It exposes three capabilities:

* :meth:`Adapter.describe` — short summary used by the dashboard.
* :meth:`Adapter.harvest` — copy the agent's raw data into
  ``knowledge/sources/<agent_id>/``.
* :meth:`Adapter.bootstrap_query` — ask the agent to help interpret the
  local environment during the first CognitiveOS bootstrap.

Adapters must never assume anything about *how* the agent runs. The
Hermes adapter, for example, reads files directly because Hermes keeps
everything on disk; a future Codex adapter might shell out to a CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..discovery import AgentHandle
from ..paths import Paths


@dataclass
class HarvestResult:
    """What an Adapter produced while harvesting an agent."""

    agent_id: str
    copied_files: int
    notes: list[str]


class Adapter(Protocol):
    agent_id: str

    def describe(self) -> dict: ...

    def harvest(self, sources_root: Path) -> HarvestResult: ...

    def bootstrap_query(self, paths: Paths) -> str | None:
        """Return a Markdown note produced *by* the agent, or None.

        For agents that don't expose a query API (Hermes today), this can
        simply return None and CognitiveOS will fall back to a heuristic
        bootstrap summary written from the harvested files.
        """
        ...


def load_adapter(handle: AgentHandle) -> Adapter | None:
    """Pick the right adapter implementation for a given handle."""
    if handle.agent_id == "hermes":
        from .hermes.adapter import HermesAdapter

        return HermesAdapter(handle)
    return None