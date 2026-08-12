"""运行 a single 任务 through CognitiveOS Kernel v0.1 (real execution).

This script proves 该 kernel loop end-到-end:

1. Discover Hermes 在 本机.
2. Build a Kernel 使用 one HermesAdapter.
3. Construct 一个任务 在 该 ``oracle`` domain (oracle_issues 记忆 key).
4. Kernel assembles context, routes, 执行 (via Hermes), reflects,
   和 写入 an episodic 记忆 entry.
5. Everything 是 dumped 到 ``.cogos/router_demo.json`` so 用户 可以
   inspect 该 actual decision trail.

运行:

    PYTHONPATH=src python scripts/run_router_demo.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make 该 在-tree cogos package importable 当 运行 来自 该 repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.adapters import load_adapter
from cogos.discovery import discover
from cogos.kernel import Task, kernel_from_paths, report_to_dict
from cogos.paths import Paths


def main() -> int:
    paths = Paths(root=ROOT)
    paths.ensure()

    print("=" * 70)
    print("CognitiveOS Router Demo — Kernel v0.1")
    print("=" * 70)

    # 1. Discovery
    print("\n[1/5] Discovery: scanning for installed agents ...")
    handles = discover(paths)
    for h in handles:
        print(f"      found: {h.agent_id}  ({h.display_name})  notes={h.notes}")

    if not handles:
        print("      NO AGENT FOUND. Aborting.")
        return 1

    # 2. Build Kernel + HermesAdapter
    print("\n[2/5] Building Kernel with Hermes adapter ...")
    adapters = []
    for h in handles:
        a = load_adapter(h)
        if a:
            adapters.append(a)
            print(f"      loaded adapter: {a.agent_id}")

    if not adapters:
        print("      NO ADAPTER AVAILABLE. Aborting.")
        return 2

    kernel = kernel_from_paths(paths, adapters, domain_map={"oracle": "hermes", "coding": "hermes"})

    # 3. Construct 任务 (real one 来自 用户's domain)
    print("\n[3/5] Constructing Task: oracle schema issue ...")
    task = Task(
        id="demo-001",
        intent=(
            "Given an Oracle 19c schema with tables A, B, C where A->B is a "
            "many-to-many bridge, design a SQL query that returns the latest "
            "status of B for each A row from the last 30 days, without "
            "triggering ORA-00918."
        ),
        domain="oracle",
        required_memory=("oracle_issues", "sql_experience"),
    )
    print(f"      task.id        = {task.id}")
    print(f"      task.domain    = {task.domain}")
    print(f"      task.intent    = {task.intent[:80]}...")
    print(f"      task.req_memory= {task.required_memory}")

    # 4. 运行
    print("\n[4/5] Kernel.run(task) ...")
    t0 = time.time()
    result = kernel.run(task)
    elapsed = time.time() - t0
    print(f"      status         = {result.status}")
    print(f"      routed_to      = {result.routed_to}")
    print(f"      routing_reason = {result.routing_reason}")
    print(f"      elapsed        = {elapsed:.2f}s")

    # 5. Persist + 显示
    print("\n[5/5] Writing demo report ...")
    report_path = paths.cache / "router_demo.json"
    report = {
        "task": {
            "id": task.id,
            "intent": task.intent,
            "domain": task.domain,
            "required_memory": list(task.required_memory),
        },
        "routing_decision": {
            "agent": result.routed_to,
            "reason": result.routing_reason,
        },
        "execution_result": {
            "status": result.status,
            "output_preview": (result.output or "")[:500],
            "full_output_path": str(report_path.with_name("router_demo_output.txt")),
        },
        "observations": result.observations,
        "elapsed_seconds": round(elapsed, 2),
        "memory_written_to": str(paths.cache / "memory.jsonl"),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.with_name("router_demo_output.txt").write_text(result.output or "", encoding="utf-8")

    print(f"      report         -> {report_path}")
    print(f"      full output    -> {report_path.with_name('router_demo_output.txt')}")

    print("\n" + "=" * 70)
    print("AGENT ANSWER (first 600 chars):")
    print("-" * 70)
    print((result.output or "(empty)")[:600])
    print("-" * 70)

    print("\nEPISODIC MEMORY ENTRY:")
    mem_path = paths.cache / "memory.jsonl"
    if mem_path.exists():
        for line in mem_path.read_text(encoding="utf-8").splitlines()[-1:]:
            print("      " + line)
    print("=" * 70)

    return 0 if result.status == "success" else 3


if __name__ == "__main__":
    sys.exit(main())