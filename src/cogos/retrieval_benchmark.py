"""Phase 5 — full retrieval benchmark engine.

Dataset: tests/fixtures/retrieval_benchmark/queries.json (50+ queries).
Metrics: Recall@1/3/5, Precision@3/5, MRR, NDCG@5, plus the safety trio:
  - False Cognitive Injection Rate (FCR): injected ∩ forbidden / injected
  - Candidate exclusion rate (must be 0)
  - Conflict exclusion rate (must be 0)

Every number comes from the real retrieval engine (retrieve_ranked);
the dataset defines expected / forbidden per query.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .benchmark import build_benchmark_dataset
from .paths import Paths
from .retrieve import RetrievalRequest, retrieve_ranked
from .store import Store
from .user import UserLayer

FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "retrieval_benchmark"


def load_queries() -> list[dict]:
    return json.loads((FIXTURES / "queries.json").read_text(encoding="utf-8"))["queries"]


# ---------------------------------------------------------------------------
# per-query metrics
# ---------------------------------------------------------------------------


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def evaluate_query(q: dict, injected_ids: list[str], *, k5: int = 5) -> dict:
    """Full metric set for one query (injected_ids = engine's final list)."""
    expected = set(q.get("expected", []))
    forbidden = set(q.get("forbidden", []))
    top1, top3, top5 = injected_ids[:1], injected_ids[:3], injected_ids[:5]

    def recall(k_list):
        return len(expected & set(k_list)) / len(expected) if expected else 1.0

    def precision(k_list):
        return len(expected & set(k_list)) / len(k_list) if k_list else 0.0

    # NDCG@5 (binary relevance: expected=1)
    rels = [1.0 if m in expected else 0.0 for m in injected_ids[:5]]
    dcg = _dcg(rels)
    ideal = _dcg([1.0] * min(len(expected), 5))
    ndcg = dcg / ideal if ideal > 0 else 0.0

    ranks = [i + 1 for i, m in enumerate(injected_ids) if m in expected]
    mrr = 1.0 / ranks[0] if ranks else 0.0

    inj = set(injected_ids)
    false_injections = inj & forbidden
    fcr = len(false_injections) / len(inj) if inj else 0.0
    cand_rate = len([m for m in inj if m.startswith("cand-")]) / len(inj) if inj else 0.0
    # conflicted ids are stored with R-CONF prefix in the dataset
    conf_rate = len([m for m in inj if m in ("R-CONF-A", "R-CONF-B", "R-CONF-X", "R-CONF-Y")]) / len(inj) if inj else 0.0

    return {
        "query_id": q["id"],
        "recall@1": round(recall(top1), 3),
        "recall@3": round(recall(top3), 3),
        "recall@5": round(recall(top5), 3),
        "precision@3": round(precision(top3), 3),
        "precision@5": round(precision(top5), 3),
        "mrr": round(mrr, 3),
        "ndcg@5": round(ndcg, 3),
        "false_injection_rate": round(fcr, 3),
        "candidate_exclusion": round(cand_rate, 3),
        "conflict_exclusion": round(conf_rate, 3),
        "injected": injected_ids,
        # ok = expected hit (or nothing expected) AND no forbidden leak
        "ok": (bool(expected & set(injected_ids)) or not expected) and not false_injections,
    }


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    keys = ["recall@1", "recall@3", "recall@5", "precision@3", "precision@5",
            "mrr", "ndcg@5", "false_injection_rate", "candidate_exclusion",
            "conflict_exclusion"]
    out = {"n": n}
    for k in keys:
        out[k] = round(sum(r[k] for r in results) / n, 3)
    out["ok_queries"] = sum(1 for r in results if r["ok"])
    out["ok_rate"] = round(out["ok_queries"] / n, 3)
    return out


# ---------------------------------------------------------------------------
# full run
# ---------------------------------------------------------------------------


def run_benchmark(provider, *, mode: str = "auto", workspace=None) -> list[dict]:
    """Run all 50+ queries against the engine; returns per-query results."""
    import tempfile

    tmp = Path(workspace) if workspace else Path(tempfile.mkdtemp())
    paths = Paths(root=tmp)
    paths.ensure()
    user = UserLayer(root=tmp / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    build_benchmark_dataset(store)
    results = []
    for q in load_queries():
        req = RetrievalRequest(
            task_text=q["text"],
            domain=q.get("domain", "sql"),
            scope=q.get("scope", "global"),
            scope_id=q.get("scope_id", ""),
            execution_id="ex-bench",
        )
        items = retrieve_ranked(store, provider, req, mode=mode)
        results.append(evaluate_query(q, [i.memory_id for i in items]))
    store.close()
    return results
