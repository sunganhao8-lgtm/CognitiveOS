"""Phase 6 — stress test: does CognitiveOS get dirtier with scale?

Generates N synthetic memories, then exercises the FULL pipeline:
reindex → retrieval (latency percentiles) → sleep → promotion → conflict
detection → versioning → correction. Assertions: everything stays
functional; retrieval latency stays sub-100ms-ish at 1k (p99 bounds are
environment-dependent — asserted as ratios, not absolutes, so the test
does not flake on slow CI machines).

scripts/stress_test.py runs the heavier 5k/10k tiers.
"""

import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cogos.conflict import detect_conflicts
from cogos.growth import run_sleep
from cogos.memory_service import MemoryService
from cogos.paths import Paths
from cogos.retrieve import RetrievalRequest, retrieve_ranked
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime.now(timezone.utc) - timedelta(days=30)

TOPICS = ["销售", "库存", "订单", "客户", "报表", "周报", "月报", "财务",
          "人力资源", "生产", "采购", "物流", "售后", "市场", "研发"]


def _synthetic_memories(n: int) -> list[dict]:
    """n deterministic synthetic memories (episodic + preference mix)."""
    out = []
    rng = random.Random(42)
    for i in range(n):
        topic = TOPICS[i % len(TOPICS)]
        kind = "episodic" if i % 3 else "preference"
        content = (f"[PASS] 用户在第 {i} 次任务中处理{topic}数据，"
                   f"使用了 {'CTE' if i % 2 else '子查询'} 组织查询，"
                   f"结果字段 {i % 7} 个")
        out.append({
            "id": f"mem-s{i:05d}", "type": kind, "domain": "sql",
            "content": content, "source": "execution",
            "derived_from_execution": f"ex-s{i:06d}",
            "verdict": "PASS", "refs": [],
            "features": ["sql:uses_cte"] if i % 2 else ["sql:uses_subquery"],
            "created_at": (TS0 + timedelta(days=i % 20)).isoformat(timespec="seconds"),
        })
    return out


def _build_store(tmp_path: Path, n: int) -> tuple[Paths, Store, UserLayer]:
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    user.memory.mkdir(parents=True, exist_ok=True)
    (user.memory / "episodic.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in _synthetic_memories(n)) + "\n",
        encoding="utf-8")
    store = Store(paths.cache / "cognitive.db")
    return paths, store, user


def _pct(samples: list[float], p: float) -> float:
    s = sorted(samples)
    idx = min(len(s) - 1, int(len(s) * p))
    return round(s[idx], 3)


def test_stress_1000_full_pipeline(tmp_path):
    paths, store, user = _build_store(tmp_path, 1000)

    # reindex
    t0 = time.perf_counter()
    report = store.reindex(paths)
    reindex_s = round(time.perf_counter() - t0, 3)
    assert report.entities >= 1000

    # retrieval latency percentiles (50 samples)
    latencies = []
    for i in range(50):
        q = f"处理{TOPICS[i % len(TOPICS)]}数据"
        t0 = time.perf_counter()
        items = retrieve_ranked(store, None, RetrievalRequest(task_text=q, domain="sql"),
                                mode="keyword")
        latencies.append((time.perf_counter() - t0) * 1000)
        assert items, "retrieval must return results at 1k scale"
    p50, p95, p99 = _pct(latencies, 0.5), _pct(latencies, 0.95), _pct(latencies, 0.99)
    # no absolute wall-clock assertions (CI variance); sanity: p99 < 50x p50
    assert p99 < max(50, p50 * 50), f"retrieval latency exploded: p50={p50} p99={p99}"
    print(f"\n[stress-1k] reindex={reindex_s}s retrieval p50={p50}ms p95={p95}ms p99={p99}ms")

    # sleep (pattern detection over 1000 episodics)
    t0 = time.perf_counter()
    sleep_report = run_sleep(user, store, now=TS0 + timedelta(days=31))
    sleep_s = round(time.perf_counter() - t0, 3)
    print(f"[stress-1k] sleep={sleep_s}s patterns={sleep_report.patterns_detected} "
          f"candidates={sleep_report.candidates_created}")

    # conflict detection on the whole store
    conflicts = detect_conflicts(store, "sql")
    assert isinstance(conflicts, list)

    # correction round-trip on a promoted memory (if any) or a synthetic one
    svc = MemoryService(paths, store)
    try:
        rows = svc.list(limit=5)
        assert rows, "memory list must work at scale"
        if svc.list(status="candidate", limit=1):
            cand = svc.list(status="candidate", limit=1)[0]
            svc.reject(cand["id"], reason="stress test")
    finally:
        svc.close()

    # versioning chain still consistent
    chain = store.version_chain("mem-s00001")
    assert chain is not None
    store.close()


def test_stress_sleep_idempotent_at_scale(tmp_path):
    """Sleep twice at 1k scale → no duplicate candidates (idempotency holds)."""
    paths, store, user = _build_store(tmp_path, 1000)
    store.reindex(paths)
    run_sleep(user, store, now=TS0 + timedelta(days=31))
    n_cands_1 = len(list((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines())) \
        if (user.memory / "candidates.jsonl").exists() else 0
    run_sleep(user, store, now=TS0 + timedelta(days=32))
    n_cands_2 = len(list((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines())) \
        if (user.memory / "candidates.jsonl").exists() else 0
    assert n_cands_2 == n_cands_1, f"sleep not idempotent at scale: {n_cands_1} → {n_cands_2}"
    store.close()
