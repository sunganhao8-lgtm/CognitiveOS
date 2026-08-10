"""Cognitive Kernel — the orchestration loop.

This is the first concrete implementation of the loop described in
``core/kernel/DESIGN.md``. It is deliberately small and runs a single
task at a time; multi-process and concurrent routing are explicitly out
of scope for v0.1 (DEC-007).

The kernel does not do the work of an agent. It coordinates:

1. **Context assembly** — call the MemoryProvider to gather entries
   whose keys are listed in ``task.required_memory``.
2. **Routing** — call the Router to pick an AgentAdapter.
3. **Execution** — call the chosen adapter's ``execute``.
4. **Reflection** — emit a simple observation record.
5. **Memory write** — append an episodic entry.

Adapters are pluggable; today only the Hermes adapter implements
``execute`` and ``bootstrap_query`` — see ``cogos.adapters.hermes``.
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
# Default implementations (v0.1)
# ---------------------------------------------------------------------------


class FileMemory:
    """Trivial JSON-line memory store under ``.cogos/memory.jsonl``."""

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
    """Rule-based router for v0.1.

    Picks the first registered adapter whose ``handles`` includes the
    task's domain. If none matches, picks the first adapter (fail-open).
    """

    def __init__(self, adapters: list[AgentAdapter], *, domain_map: dict[str, str] | None = None) -> None:
        self.adapters = {a.agent_id: a for a in adapters}
        self.domain_map = domain_map or {}

    def decide(self, task: Task, context: Context) -> RouteDecision:
        if not self.adapters:
            return RouteDecision(agent_id="<none>", reason="no adapters", confidence=0.0)

        # Explicit domain map wins.
        target_id = self.domain_map.get(task.domain)
        if target_id and target_id in self.adapters:
            return RouteDecision(
                agent_id=target_id,
                reason=f"domain '{task.domain}' explicitly mapped to '{target_id}'",
                confidence=0.95,
            )

        # Otherwise, pick the first adapter (v0.1 rule: Hermes handles all).
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

    # --- public loop -----------------------------------------------------

    def run(self, task: Task) -> Result:
        # 1. Context assembly
        context = Context(task=task, memory_entries=self.memory.read(list(task.required_memory)))

        # 2. Routing
        decision = self.router.decide(task, context)
        adapter = self.adapters.get(decision.agent_id)
        if adapter is None:
            return Result(
                task_id=task.id,
                status="failed",
                output=f"router selected '{decision.agent_id}' but no adapter is registered",
            )

        # 3. Execution
        result = adapter.execute(task, context)
        result.routed_to = decision.agent_id
        result.routing_reason = decision.reason

        # 4. Reflection (single observation per run for v0.1)
        observation = {
            "task_id": task.id,
            "domain": task.domain,
            "agent": decision.agent_id,
            "status": result.status,
            "note": f"kernel selected {decision.agent_id} for domain '{task.domain}'",
        }
        result.observations.append(observation["note"])

        # 5. Memory write (episodic)
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
# Helpers for callers
# ---------------------------------------------------------------------------


def kernel_from_paths(paths: Paths, adapters: list[AgentAdapter], *, domain_map: dict[str, str] | None = None) -> Kernel:
    """Build a Kernel wired against the project's local paths."""
    memory = FileMemory(paths.cache / "memory.jsonl")
    router = DomainRouter(adapters, domain_map=domain_map)
    return Kernel(memory=memory, router=router, adapters=adapters)


def report_to_dict(result: Result) -> dict:
    return asdict(result)