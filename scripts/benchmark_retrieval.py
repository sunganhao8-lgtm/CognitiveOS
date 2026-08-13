"""Retrieval benchmark runner — three-mode comparison on the frozen case set.

    PYTHONPATH=src python scripts/benchmark_retrieval.py

Builds the deterministic synthetic dataset, runs keyword / semantic / hybrid
retrieval over every case query, and prints per-case detail + the summary
table. The real local embedding model (bge-small-zh via fastembed) is used
when available; otherwise semantic/hybrid honestly report 'unavailable'.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.benchmark import build_benchmark_dataset, evaluate_case, load_cases, summarize
from cogos.embedding import get_provider
from cogos.paths import Paths
from cogos.retrieve import RetrievalRequest, retrieve_ranked
from cogos.store import Store
from cogos.user import UserLayer


def main() -> int:
    tmp = ROOT / ".cogos" / "bench_ws"
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    paths = Paths(root=tmp)
    paths.ensure()
    user = UserLayer(root=tmp / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    build_benchmark_dataset(store)

    provider = get_provider()
    print(f"embedding provider: {provider.name if provider else '(none — keyword-only)'}")
    if provider:
        print(f"  model={provider.name} dimension={provider.dimension}")

    modes = ["keyword"]
    if provider:
        modes += ["semantic", "hybrid"]
    else:
        modes += ["semantic (unavailable)", "hybrid (unavailable)"]

    summaries: dict[str, dict] = {}
    for mode in modes:
        real_mode = mode.split()[0]
        if "unavailable" in mode:
            summaries[mode] = {"recall_at5": float("nan"), "precision_at5": float("nan"),
                               "mrr": float("nan"), "n": 0}
            continue
        results = []
        for case in load_cases():
            for query in case["queries"]:
                req = RetrievalRequest(
                    task_text=query,
                    domain=case.get("domain", "sql"),
                    scope=case.get("scope", "global"),
                    scope_id=case.get("scope_id", ""),
                    execution_id="ex-bench",
                )
                items = retrieve_ranked(store, provider, req, mode=real_mode)
                results.append(evaluate_case(case, query, [i.memory_id for i in items]))
        summaries[mode] = summarize(results)
        print(f"\n=== mode: {mode} ===")
        for r in results:
            mark = "OK " if r.ok else "MISS"
            print(f"  [{mark}] {r.case_id:<28} {r.query[:24]:<26} expected={r.expected} "
                  f"actual={r.actual} ranks={r.ranks or '-'}")
        print(f"  summary: {summaries[mode]}")

    print("\n=== COMPARISON TABLE ===")
    print(f"{'mode':<22} {'Recall@5':>9} {'Precision@5':>12} {'MRR':>8}")
    for mode, s in summaries.items():
        print(f"{mode:<22} {s['recall_at5']:>9} {s['precision_at5']:>12} {s['mrr']:>8}")

    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
