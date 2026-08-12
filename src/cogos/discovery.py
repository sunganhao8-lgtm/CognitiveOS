"""Agent 发现。

``discovery`` 扫描本机已安装的 AI Agent，返回一个
:class:`AgentHandle` 列表。每个 handle 告诉你*发现了什么*和*在
哪里*；具体的数据读取由 Adapter 完成。

发现层永远不能为某个特定 Agent 写死行为。新加一个 Agent 意味着
在 ``cogos.discovery.probes`` 下写一个小的 probe 函数，然后在
``PROBES`` 里注册。CognitiveOS 别的地方都不用改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .paths import Paths


@dataclass(frozen=True)
class AgentHandle:
    """发现到的 AI Agent 安装。

    ``agent_id`` 是被 adapter 和 wiki 使用的稳定名称；
    ``paths`` 是与该 Agent 相关的磁盘位置。
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


# probe 接收共享 Paths，返回零或多个 AgentHandle。
Probe = Callable[[Paths], Iterable[AgentHandle]]


def discover(paths: Paths) -> list[AgentHandle]:
    """跑所有已注册的 probe，返回 handle 的并集。"""
    from . import probes  # local import: avoid cycles when probes import this module

    found: list[AgentHandle] = []
    for probe in probes.all_probes():
        try:
            for h in probe(paths):
                found.append(h)
        except Exception as exc:  # 一个坏的 probe 不能让发现整体挂掉
            found.append(
                AgentHandle(
                    agent_id="<probe_error>",
                    display_name="probe error",
                    version=None,
                    notes=[f"{probe.__name__}: {exc!r}"],
                )
            )
    return found