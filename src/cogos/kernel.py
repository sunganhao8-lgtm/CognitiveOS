"""Cognitive Kernel —— 编排主循环。

这是 ``core/kernel/DESIGN.md`` 中所描述循环的第一个具体实现。
刻意保持小而单任务，多进程 / 并发路由明确不在 v0.1 范围内（DEC-007）。

Kernel 不亲自做 Agent 的活。它只负责协调：

1. **上下文装配** —— 调 MemoryProvider，捞 ``任务.required_memory``
   列出的 keys。
2. **路由** —— 调 Router 选一个 AgentAdapter。
3. **执行** —— 调选中 Adapter 的 ``执行``。
4. **反思** —— 写一条简单观察记录。
5. **写记忆** —— 追加一条 episodic 记录。

Adapter 是可插拔的；目前只有 Hermes Adapter 实现了
``执行`` 和 ``bootstrap_query``，见 ``cogos.Adapters.hermes``。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .paths import Paths


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    id: str
    intent: str
    domain: str
    required_memory: tuple[str, ...] = ()


@dataclass(frozen=True)
class Context:
    task: Task
    memory_entries: list = field(default_factory=list)


@dataclass(frozen=True)
class RouteDecision:
    agent_id: str
    reason: str
    confidence: float


@dataclass
class Result:
    task_id: str
    status: str  # "success" | "failed"
    output: str
    artifacts: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    routed_to: str | None = None
    routing_reason: str | None = None


# ---------------------------------------------------------------------------
# Subsystem contracts
# ---------------------------------------------------------------------------


class MemoryProvider(Protocol):
    def read(self, query: list[str]) -> list: ...
    def write(self, entry: dict) -> None: ...


class Router(Protocol):
    def decide(self, task: Task, context: Context) -> RouteDecision: ...


class AgentAdapter(Protocol):
    agent_id: str

    def execute(self, task: Task, context: Context) -> Result: ...
    def bootstrap_query(self, prompt: str) -> str | None: ...


# ---------------------------------------------------------------------------
# 默认 implementations (v0.1)
# ---------------------------------------------------------------------------


class FileMemory:
    """v0.1 用的极简 JSON-line 记忆存储，位于 ``.cogos/记忆.jsonl``。"""

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self, query: list[str]) -> list:
        if not self.store_path.exists():
            return []
        entries = []
        for line in self.store_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if any(q in rec.get("keys", []) for q in query) or not query:
                entries.append(rec)
        return entries

    def write(self, entry: dict) -> None:
        if "created_at" not in entry:
            entry = {**entry, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with self.store_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class DomainRouter:
    """v0.1 的基于规则的路由器。

    选第一个 ``handles`` 含本任务 domain 的 Adapter。
    都不匹配则回退到第一个（fail-open）。
    """

    def __init__(self, adapters: list[AgentAdapter], *, domain_map: dict[str, str] | None = None) -> None:
        self.adapters = {a.agent_id: a for a in adapters}
        self.domain_map = domain_map or {}

    def decide(self, task: Task, context: Context) -> RouteDecision:
        if not self.adapters:
            return RouteDecision(agent_id="<none>", reason="no adapters", confidence=0.0)

        # 显式 domain map 优先。
        target_id = self.domain_map.get(task.domain)
        if target_id and target_id in self.adapters:
            return RouteDecision(
                agent_id=target_id,
                reason=f"domain '{task.domain}' explicitly mapped to '{target_id}'",
                confidence=0.95,
            )

        # 否则选第一个 Adapter（v0.1 规则：Hermes 兜底全部）。
        first_id = next(iter(self.adapters))
        return RouteDecision(
            agent_id=first_id,
            reason=f"domain '{task.domain}' fell back to first available adapter",
            confidence=0.6,
        )


# ---------------------------------------------------------------------------
# Kernel
# ---------------------------------------------------------------------------


class Kernel:
    def __init__(
        self,
        *,
        memory: MemoryProvider,
        router: Router,
        adapters: list[AgentAdapter],
    ) -> None:
        self.memory = memory
        self.router = router
        self.adapters = {a.agent_id: a for a in adapters}

    # --- 对外主循环 -----------------------------------------------------

    def run(self, task: Task) -> Result:
        # 1. 上下文装配
        context = Context(task=task, memory_entries=self.memory.read(list(task.required_memory)))

        # 2. 路由
        decision = self.router.decide(task, context)
        adapter = self.adapters.get(decision.agent_id)
        if adapter is None:
            return Result(
                task_id=task.id,
                status="failed",
                output=f"路由器选了 '{decision.agent_id}'，但没有对应的 adapter",
            )

        # 3. 执行
        result = adapter.execute(task, context)
        result.routed_to = decision.agent_id
        result.routing_reason = decision.reason

        # 4. 反思（v0.1 每轮只记一条）
        observation = {
            "task_id": task.id,
            "domain": task.domain,
            "agent": decision.agent_id,
            "status": result.status,
            "note": f"kernel 为 domain '{task.domain}' 选了 {decision.agent_id}",
        }
        result.observations.append(observation["note"])

        # 5. 写记忆（episodic）
        self.memory.write(
            {
                "task_id": task.id,
                "domain": task.domain,
                "agent": decision.agent_id,
                "intent": task.intent,
                "status": result.status,
                "keys": list(task.required_memory),
                "kind": "episodic",
            }
        )

        return result


# ---------------------------------------------------------------------------
# Helpers 用于 callers
# ---------------------------------------------------------------------------


def kernel_from_paths(paths: Paths, adapters: list[AgentAdapter], *, domain_map: dict[str, str] | None = None) -> Kernel:
    """Build a Kernel wired against 该 project's local 路径们."""
    memory = FileMemory(paths.cache / "memory.jsonl")
    router = DomainRouter(adapters, domain_map=domain_map)
    return Kernel(memory=memory, router=router, adapters=adapters)


def report_to_dict(result: Result) -> dict:
    return asdict(result)