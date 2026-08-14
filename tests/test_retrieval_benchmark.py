"""Phase 5 tests — full retrieval benchmark: metrics correctness, safety
rates (FCR / candidate / conflict exclusion), dataset integrity."""

import json
from pathlib import Path

from cogos.retrieval_benchmark import (
    aggregate,
    evaluate_query,
    load_queries,
    run_benchmark,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "retrieval_benchmark"


def test_dataset_has_50_plus_queries():
    queries = load_queries()
    assert len(queries) >= 50, f"dataset must have 50+ queries, got {len(queries)}"
    categories = {q["category"] for q in queries}
    for cat in ("sql", "report", "general", "synonym", "short", "long",
                "project", "temporary", "conflict", "negative", "unrelated",
                "versioning"):
        assert cat in categories, f"missing category: {cat}"


def test_metric_math():
    # perfect: expected first
    r = evaluate_query({"id": "t", "expected": ["A"], "forbidden": ["B"]}, ["A", "B"])
    assert r["recall@1"] == 1.0 and r["mrr"] == 1.0 and r["ndcg@5"] == 1.0
    assert r["false_injection_rate"] == 0.5  # B injected
    assert r["ok"] is False  # forbidden leak → not ok

    # clean miss
    r2 = evaluate_query({"id": "t2", "expected": ["A"], "forbidden": []}, ["B", "C"])
    assert r2["recall@1"] == 0.0 and r2["mrr"] == 0.0
    assert r2["false_injection_rate"] == 0.0  # nothing forbidden injected

    # empty expected (unrelated query): no false claim of success
    r3 = evaluate_query({"id": "t3", "expected": [], "forbidden": ["A"]}, ["B"])
    assert r3["recall@1"] == 1.0 and r3["ok"] is True


def test_aggregate_math():
    agg = aggregate([
        {"recall@1": 1.0, "recall@3": 1.0, "recall@5": 1.0, "precision@3": 0.5,
         "precision@5": 0.5, "mrr": 1.0, "ndcg@5": 1.0, "false_injection_rate": 0.0,
         "candidate_exclusion": 0.0, "conflict_exclusion": 0.0, "ok": True},
        {"recall@1": 0.0, "recall@3": 0.5, "recall@5": 0.5, "precision@3": 0.25,
         "precision@5": 0.25, "mrr": 0.0, "ndcg@5": 0.4, "false_injection_rate": 1.0,
         "candidate_exclusion": 0.0, "conflict_exclusion": 0.0, "ok": False},
    ])
    assert agg["recall@1"] == 0.5
    assert agg["ok_rate"] == 0.5
    assert agg["false_injection_rate"] == 0.5


def test_engine_safety_rates(tmp_path):
    """Candidate/conflict/temporary/superseded must NEVER be injected."""
    results = run_benchmark(None, mode="keyword", workspace=tmp_path)
    for r in results:
        assert r["candidate_exclusion"] == 0.0, f"{r['query_id']}: candidate injected"
        assert r["conflict_exclusion"] == 0.0, f"{r['query_id']}: conflicted injected"
        inj = r["injected"]
        assert "tmp-bench-002" not in inj, f"{r['query_id']}: temporary injected"
        assert "P-SQL-CTE-OLD" not in inj, f"{r['query_id']}: superseded injected"
    agg = aggregate(results)
    # hard safety: candidate/conflict/temporary/superseded NEVER inject (0)
    # soft bound: FCR < 0.02 — keyword mode has one known true-positive trap
    # (sql-007: "数据" hits the backup-rule "数据库"), which is exactly what
    # semantic reranking must fix; the safety classes above are already 0
    assert agg["false_injection_rate"] < 0.02, (
        f"keyword engine false-injection rate too high: {agg}"
    )


def test_benchmark_runs_all_modes(tmp_path):
    from cogos.retrieval_benchmark import run_benchmark

    for mode in ("keyword", "semantic", "hybrid"):
        results = run_benchmark(None, mode=mode, workspace=tmp_path)
        # semantic/hybrid without provider degrade to keyword results
        assert len(results) == len(load_queries())
        agg = aggregate(results)
        assert agg["n"] == len(load_queries())


def test_unrelated_queries_stay_empty(tmp_path):
    results = run_benchmark(None, mode="keyword", workspace=tmp_path)
    qm = {q["id"]: q for q in load_queries()}
    for r in results:
        if r["query_id"].startswith("unrel-"):
            # forbidden list is the whole memory set for these — nothing may inject
            assert not set(r["injected"]) & set(qm[r["query_id"]]["forbidden"]), r["query_id"]
