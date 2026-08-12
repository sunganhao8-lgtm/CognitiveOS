"""Tests for cogos.kernel — Task / Context / Kernel.run loop."""

import json
from pathlib import Path

from cogos.kernel import Task, Context, Kernel, FileMemory, DomainRouter, Result


class _StubAdapter:
    agent_id = "stub"

    def __init__(self, output: str = "stub answer"):
        self.output = output
        self.calls: list = []

    def execute(self, task, context):
        self.calls.append(task)
        return Result(task_id=task.id, status="success", output=self.output)

    def bootstrap_query(self, prompt):
        return None


def test_kernel_routes_to_first_adapter_when_no_domain_map(tmp_path):
    ad = _StubAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=tmp_path / "m.jsonl"),
        router=DomainRouter([ad]),
        adapters=[ad],
    )
    task = Task(id="t1", intent="test", domain="oracle", required_memory=())
    result = kernel.run(task)
    assert result.status == "success"
    assert result.routed_to == "stub"
    assert ad.calls and ad.calls[0].id == "t1"


def test_kernel_writes_episodic_memory_after_run(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    ad = _StubAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=memory_path),
        router=DomainRouter([ad]),
        adapters=[ad],
    )
    task = Task(id="t1", intent="t", domain="oracle", required_memory=("k1",))
    kernel.run(task)
    assert memory_path.exists()
    lines = memory_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["task_id"] == "t1"
    assert rec["domain"] == "oracle"
    assert "k1" in rec["keys"]
    assert rec["kind"] == "episodic"


def test_kernel_routes_to_first_adapter_when_no_domain_map(tmp_path):
    memory_path = tmp_path / "memory.jsonl"
    ad = _StubAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=memory_path),
        router=DomainRouter([ad]),
        adapters=[ad],
    )
    task = Task(id="t1", intent="t", domain="oracle", required_memory=("k1",))
    kernel.run(task)
    assert memory_path.exists()
    lines = memory_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["task_id"] == "t1"
    assert rec["domain"] == "oracle"
    assert "k1" in rec["keys"]
    assert rec["kind"] == "episodic"


def test_kernel_returns_failed_when_router_target_missing(tmp_path):
    class _NoRouter:
        def decide(self, task, context):
            from cogos.kernel import RouteDecision
            return RouteDecision(agent_id="missing", reason="x", confidence=0.0)

    ad = _StubAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=tmp_path / "m.jsonl"),
        router=_NoRouter(),
        adapters=[ad],
    )
    task = Task(id="t2", intent="x", domain="oracle")
    result = kernel.run(task)
    assert result.status == "failed"
    assert "missing" in result.output


def test_kernel_records_routing_reason_in_result(tmp_path):
    """Result must carry both the chosen agent and the *reason* — for auditability."""
    ad = _StubAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=tmp_path / "m.jsonl"),
        router=DomainRouter([ad], domain_map={"oracle": "stub"}),
        adapters=[ad],
    )
    task = Task(id="t3", intent="x", domain="oracle")
    result = kernel.run(task)
    assert result.routed_to == "stub"
    assert "oracle" in (result.routing_reason or "")
    assert "mapped" in (result.routing_reason or "")