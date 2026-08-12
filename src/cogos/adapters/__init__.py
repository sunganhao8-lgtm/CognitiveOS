"""Agent Adapters.

一个 Adapter 是 该 only thing 在 CognitiveOS that knows 该 *internal*
layout 的 a 具体 Agent. It exposes three capabilities:

* :meth:`Adapter.describe` — short summary 被 ... 使用 该 dashboard.
* :meth:`Adapter.harvest` — copy Agent's raw data into
  ``knowledge/来源们/<agent_id>/``.
* :meth:`Adapter.bootstrap_query` — ask Agent 到 help interpret 该
  local environment during 第一个 CognitiveOS bootstrap.

Adapters 必须 从不 assume anything about *how* Agent 运行. 该
Hermes Adapter, 例如, 读取 文件们 直接 because Hermes keeps
everything 在 disk; a future Codex Adapter 可能 shell out 到 a CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..discovery import AgentHandle
from ..paths import Paths


@dataclass
class HarvestResult:
    """What 一个 Adapter produced while harvesting 一个 Agent."""

    agent_id: str
    copied_files: int
    notes: list[str]


class Adapter(Protocol):
    agent_id: str

    def describe(self) -> dict: ...

    def harvest(self, sources_root: Path) -> HarvestResult: ...

    def bootstrap_query(self, paths: Paths) -> str | None:
        """返回 a Markdown 注意 produced *通过* Agent, 或 None.

        用于 Agents that don't expose a query API (Hermes today), this 可以
        simply 返回 None 和 CognitiveOS 将 fall back 到 a heuristic
        bootstrap summary written 来自 该 harvested 文件们.
        """
        ...


def load_adapter(handle: AgentHandle) -> Adapter | None:
    """Pick 该 right Adapter implementation 用于 a given handle."""
    if handle.agent_id == "hermes":
        from .hermes.adapter import HermesAdapter

        return HermesAdapter(handle)
    if handle.agent_id == "claude_code":
        from .claude_code.adapter import ClaudeCodeAdapter

        return ClaudeCodeAdapter(handle)
    if handle.agent_id == "codex":
        from .codex.adapter import CodexAdapter

        return CodexAdapter(handle)
    return None