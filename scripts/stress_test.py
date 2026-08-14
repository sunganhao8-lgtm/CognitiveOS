"""Phase 6 — heavier stress tiers (5k / 10k synthetic memories).

    PYTHONPATH=src python scripts/stress_test.py [n]

Runs the full pipeline (reindex → retrieval percentiles → sleep → promote
→ conflict → correction) at the requested scale and prints the numbers.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))  # tests/ is importable for the generator

from cogos.conflict import detect_conflicts
from cogos.growth import run_sleep
from cogos.memory_service import MemoryService
from cogos.paths import Paths
from cogos.retrieve import RetrievalRequest, retrieve_ranked
from cogos.store import Store
from cogos.user import UserLayer
from tests.test_stress import _build_store, _pct  # reuse synthetic generator

TS0 = datetime.now(timezone.utc) - timedelta(days=30)


def main(n: int = 5000) -> int:
    tmp = ROOT / ".cogos" / "stress_ws"
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    paths, store, user = _build_store(tmp, n)

    t0 = time.perf_counter()
    report = store.reindex(paths)
    print(f"[stress-{n}] reindex: {round(time.perf_counter() - t0, 2)}s "
          f"(entities={report.entities}, fts={report.fts_rows})")

    latencies = []
    for i in range(50):
        q = f"处理第 {i} 次任务的销售数据"
        t0 = time.perf_counter()
        retrieve_ranked(store, None, RetrievalRequest(task_text=q, domain="sql"), mode="keyword")
        latencies.append((time.perf_counter() - t0) * 1000)
    print(f"[stress-{n}] retrieval p50={_pct(latencies, 0.5)}ms "
          f"p95={_pct(latencies, 0.95)}ms p99={_pct(latencies, 0.99)}ms")

    t0 = time.perf_counter()
    sr = run_sleep(user, store, now=TS0 + timedelta(days=31))
    print(f"[stress-{n}] sleep: {round(time.perf_counter() - t0, 2)}s "
          f"(patterns={sr.patterns_detected}, candidates={sr.candidates_created}, "
          f"promoted={sr.memories_promoted})")

    t0 = time.perf_counter()
    conflicts = detect_conflicts(store, "sql")
    print(f"[stress-{n}] conflict detection: {round(time.perf_counter() - t0, 3)}s "
          f"({len(conflicts)} conflicts)")

    svc = MemoryService(paths, store)
    try:
        rows = svc.list(limit=3)
        print(f"[stress-{n}] memory list ok ({len(rows)} shown)")
        cand = svc.list(status="candidate", limit=1)
        if cand:
            svc.reject(cand[0]["id"], reason="stress")
            print(f"[stress-{n}] correction ok (rejected {cand[0]['id']})")
    finally:
        svc.close()
        store.close()
    print(f"[stress-{n}] ALL PIPELINE STAGES OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5000))
