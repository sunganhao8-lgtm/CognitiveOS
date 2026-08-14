"""Agent Registry — Phase 7.

Unified view of every agent CognitiveOS can drive:

    agent_id | name | provider | capabilities | workspace | status

Sources:
- adapters/ (the runtime adapters actually wired into the Kernel)
- knowledge/sources/<agent>/ (harvested skill/knowledge registrations)

Agent Run Contract (every execution must carry):
    execution_id, agent_id, task, cognitive_context, result, verification, trace
— enforced by the Kernel (trace is mandatory for any agent run).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .paths import Paths


@dataclass
class AgentInfo:
    agent_id: str
    name: str
    provider: str = "local"
    capabilities: list[str] = field(default_factory=list)
    workspace: str = ""
    status: str = "unknown"  # registered | available | offline

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "workspace": self.workspace,
            "status": self.status,
        }


class AgentRegistry:
    """Registry of agents: runtime adapters + harvested sources."""

    def __init__(self, paths: Paths, adapters: list | None = None) -> None:
        self.paths = paths
        self._adapters = {a.agent_id: a for a in (adapters or [])}

    # ------------------------------------------------------------ discovery

    def _harvested_agents(self) -> list[dict]:
        """Agents discovered from knowledge/sources/<agent> registries."""
        out: list[dict] = []
        sources = self.paths.sources
        if not sources.exists():
            return out
        for agent_dir in sorted(p for p in sources.iterdir() if p.is_dir()):
            aid = agent_dir.name
            caps: list[str] = []
            skills = agent_dir / "skills"
            if skills.exists():
                caps = sorted(
                    d.name for d in skills.iterdir()
                    if d.is_dir() and (d / "SKILL.md").exists()
                )[:20]
            out.append({
                "agent_id": aid,
                "name": aid,
                "provider": "local",
                "capabilities": caps,
                "workspace": str(agent_dir),
                "status": "registered",
            })
        return out

    def list(self) -> list[AgentInfo]:
        agents: dict[str, AgentInfo] = {}
        # runtime adapters first (they can actually execute)
        for aid, adapter in self._adapters.items():
            agents[aid] = AgentInfo(
                agent_id=aid,
                name=adapter.agent_id,
                provider=getattr(adapter, "provider", "local"),
                capabilities=[],
                workspace=getattr(adapter, "workspace", ""),
                status="available",
            )
        for h in self._harvested_agents():
            if h["agent_id"] not in agents:
                agents[h["agent_id"]] = AgentInfo(**h)
        return list(agents.values())

    def show(self, agent_id: str) -> AgentInfo | None:
        for a in self.list():
            if a.agent_id == agent_id:
                return a
        return None

    # ------------------------------------------------------------ skills

    def skills_for(self, agent_id: str) -> list[dict]:
        """Skills registered under an agent (knowledge/sources/<agent>/skills)."""
        skills_dir = self.paths.sources / agent_id / "skills"
        out: list[dict] = []
        if not skills_dir.exists():
            return out
        for skill_dir in sorted(skills_dir.iterdir()):
            sk = skill_dir / "SKILL.md"
            if not sk.exists():
                continue
            out.append({
                "name": skill_dir.name,
                "path": str(sk),
                "size": sk.stat().st_size,
            })
        return out
