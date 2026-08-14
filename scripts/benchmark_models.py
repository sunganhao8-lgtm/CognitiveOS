"""Phase 5 — model comparison runner.

    PYTHONPATH=src python scripts/benchmark_models.py

Benchmarks every available embedding provider (plus keyword-only) on the
50+ query dataset and prints the comparison table. The final default model
choice is DATA-DRIVEN (highest recall/precision/MRR, lowest FCR), not by
model name.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.embedding import get_provider, load_local_provider, load_remote_provider
from cogos.retrieval_benchmark import aggregate, load_queries, run_benchmark

MODELS = [
    ("keyword-only", None),
    ("bge-small-zh-v1.5", None),  # resolved lazily below
]


def main() -> int:
    # resolve real providers
    small = load_local_provider()
    providers = [("keyword-only", None, "keyword")]
    if small is not None:
        providers.append((small.name, small, "hybrid"))
    # attempt a stronger zh/multilingual model (downloads on first use;
    # skipped honestly when unavailable). bge-m3 is NOT supported by
    # fastembed 0.8.0 — jina-embeddings-v2-base-zh (zh, 768d) is the next
    # best candidate.
    for mname, mlabel in (
        ("jinaai/jina-embeddings-v2-base-zh", "jina-embeddings-v2-base-zh"),
        ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "multilingual-MiniLM"),
    ):
        try:
            from fastembed import TextEmbedding

            model = TextEmbedding(mname, threads=2)
            probe = list(model.embed(["你好"]))

            class _Alt:
                name = mlabel
                dimension = len(probe[0])

                def embed(self, texts):
                    return [v.tolist() for v in model.embed(texts)]

            providers.append((_Alt.name, _Alt(), "hybrid"))
        except Exception as exc:
            print(f"({mname} unavailable: {exc})", file=sys.stderr)

    print(f"dataset: {len(load_queries())} queries\n")
    rows = []
    for label, provider, mode in providers:
        results = run_benchmark(provider, mode=mode)
        agg = aggregate(results)
        rows.append((label, agg))
        print(f"--- {label} (mode={mode}) ---")
        for r in results:
            if not r["ok"]:
                print(f"  [MISS] {r['query_id']}: injected={r['injected']} "
                      f"expected={r['injected'] and '?'}")
        print(f"  aggregate: {agg}\n")

    print("=== COMPARISON TABLE ===")
    hdr = f"{'model':<22} {'R@1':>6} {'R@3':>6} {'R@5':>6} {'P@3':>6} {'P@5':>6} {'MRR':>6} {'NDCG':>6} {'FCR':>7} {'ok%':>6}"
    print(hdr)
    for label, agg in rows:
        print(f"{label:<22} {agg['recall@1']:>6} {agg['recall@3']:>6} {agg['recall@5']:>6} "
              f"{agg['precision@3']:>6} {agg['precision@5']:>6} {agg['mrr']:>6} {agg['ndcg@5']:>6} "
              f"{agg['false_injection_rate']:>7} {agg['ok_rate']:>6}")

    # data-driven default choice
    best = max(rows, key=lambda r: (r[1]["recall@5"], r[1]["mrr"], -r[1]["false_injection_rate"]))
    print(f"\n>>> data-driven best model: {best[0]} "
          f"(R@5={best[1]['recall_at_5'] if 'recall_at_5' in best[1] else best[1]['recall@5']}, "
          f"MRR={best[1]['mrr']}, FCR={best[1]['false_injection_rate']})")
    print(">>> decision rule: pick the best ONLY if it materially beats "
          "bge-small-zh-v1.5; otherwise keep bge-small-zh-v1.5 (no upgrade for upgrade's sake)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
