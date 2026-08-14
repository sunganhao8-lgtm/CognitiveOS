"""Retrieval benchmark — dataset construction, metric computation.

The 8 case classes from the frozen contract (§9). Dataset construction is
DETERMINISTIC (synthetic memories seeded into a fresh workspace) so the
benchmark can run anywhere without real user data, and its numbers are
comparable across retrieval strategy changes.

Metrics: Recall@k, Precision@k, MRR (mean reciprocal rank).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def build_benchmark_dataset(store) -> list[str]:
    """Seed the deterministic synthetic memory set; returns memory ids.

    Domains: sql / reporting / writing / pet — plus project-scoped sql.
    """

    def mem(ent_id, subtype, domain, content, *, scope="global", scope_id="",
            status="confirmed", confidence=0.85, user_confirmed=False,
            payload=None, version=1, fts=True):
        store.upsert_entity(
            ent_id, "memory", subtype=subtype, domain=domain, content=content,
            payload=payload or {"source": "benchmark"},
            status=status, scope=scope, scope_id=scope_id,
            confidence=confidence, user_confirmed=user_confirmed, version=version,
        )
        if fts:
            store.add_fts(ent_id, "memory", subtype, domain, content)
        return ent_id

    ids: list[str] = []
    # SQL rules / preferences (global)
    ids.append(mem("R-SQL-001", "rule", "sql",
                   "SQL 查询不允许使用 SELECT *，必须显式列出字段",
                   payload={"source": "user_statement", "forbidden": ["SELECT *"], "required": []},
                   user_confirmed=True, confidence=0.99))
    ids.append(mem("P-SQL-CTE", "preference", "sql",
                   "写 SQL 查询时偏好使用 CTE（WITH）结构组织复杂逻辑",
                   confidence=0.9))
    # report preference
    ids.append(mem("P-REPORT-001", "preference", "reporting",
                   "生成报表时偏好横向宽表布局，表头带汇总行",
                   confidence=0.85))
    # formatting preference
    ids.append(mem("P-FORMAT-001", "preference", "writing",
                   "写文案偏好短句分段，每段不超过三行，少用形容词",
                   confidence=0.8))
    # project-scoped sql preference
    ids.append(mem("P-PROJ-BP", "preference", "sql",
                   "该项目（BP）的 SQL 查询偏好使用子查询而不是 CTE",
                   scope="project", scope_id="bp",
                   payload={"source": "user_statement"}, user_confirmed=True,
                   confidence=0.88))
    # unrelated pet-domain memory (negative sample)
    ids.append(mem("P-PET-001", "preference", "pet",
                   "用户喜欢给猫制定采购计划，偏好按月囤粮",
                   confidence=0.8))
    # repeated-behavior derived preference
    ids.append(mem("P-SQL-INDEX", "preference", "sql",
                   "写 SQL 时习惯给表起简短别名（如 s、o、p）",
                   payload={"source": "sleep_promotion"}, confidence=0.72,
                   user_confirmed=False))
    # interference memory (same domain, wrong topic — must NOT be injected
    # for sales queries)
    ids.append(mem("P-SQL-BACKUP", "preference", "sql",
                   "数据库备份策略：每天凌晨全量备份到本地磁盘",
                   confidence=0.99, user_confirmed=True))
    # unrelated topic inside a related domain (trap for keyword overlap)
    ids.append(mem("P-SQL-SECURITY", "rule", "sql",
                   "生产数据库禁止直接执行 DELETE 语句，必须先备份",
                   payload={"source": "user_statement", "forbidden": ["DELETE FROM"], "required": []},
                   user_confirmed=True, confidence=0.9))
    # superseded version (must never be injected)
    ids.append(mem("P-SQL-CTE-OLD", "preference", "sql",
                   "旧版：所有 SQL 一律使用 CTE",
                   payload={"source": "user_statement"}, status="superseded",
                   confidence=0.8))
    # conflicted pair (must never inject as ordinary cognition)
    ids.append(mem("R-CONF-X", "rule", "sql",
                   "SQL 必须使用 CTE 结构",
                   payload={"source": "manual", "required": ["CTE"]},
                   status="conflicted", confidence=0.9))
    ids.append(mem("R-CONF-Y", "rule", "sql",
                   "SQL 禁止使用 CTE 结构",
                   payload={"source": "manual", "forbidden": ["CTE"]},
                   status="conflicted", confidence=0.9))
    # candidate (must never inject)
    ids.append(mem("cand-sql-join", "candidate", "sql", "用户似乎偏好 JOIN 写法",
                   status="candidate", confidence=0.6, fts=False))
    # long-query-friendly general preference
    ids.append(mem("P-GEN-001", "preference", "general",
                   "给用户的汇报必须先给结论再给细节，不要一上来就铺细节",
                   confidence=0.85))
    # temporary (retrieval layer must exclude it)
    ids.append(mem("tmp-bench-002", "temporary", "sql",
                   "本次允许使用 SELECT *", status="temporary", scope="temporary",
                   payload={"allowed": ["SELECT *"]}, fts=False))
    return ids


def load_cases() -> list[dict]:
    """The frozen 8-class case set (contract §9)."""
    return [
        {
            "id": "case-sql-preference",
            "queries": [
                "写一个销售 SQL",
                "帮我生成销售查询",
                "做一个销售数据查询",
                "查询销售明细",
                "帮我查销售数据",
            ],
            "expected_memory": ["R-SQL-001"],
            "forbidden_memory": ["P-PET-001"],
            "expected_context_contains": ["R-SQL-001"],
        },
        {
            "id": "case-report-preference",
            "queries": ["帮我做一份销售报表", "生成周报"],
            "expected_memory": ["P-REPORT-001"],
            "forbidden_memory": ["P-PET-001"],
            "expected_context_contains": ["P-REPORT-001"],
        },
        {
            "id": "case-formatting-preference",
            "queries": ["帮我写一段产品文案", "写一个发布文案"],
            "expected_memory": ["P-FORMAT-001"],
            "forbidden_memory": ["P-PET-001"],
            "expected_context_contains": ["P-FORMAT-001"],
        },
        {
            "id": "case-temporary-exception",
            "queries": ["帮我写一个销售 SQL"],
            # temporary exceptions are injected by the KERNEL layer for the
            # bound task — the retrieval layer must NOT return them (§2/§6)
            "expected_memory": [],
            "forbidden_memory": ["tmp-bench-001"],
            "expected_context_contains": [],
            "setup": "temporary",
        },
        {
            "id": "case-conflicting-preference",
            "queries": ["帮我写一个 SQL"],
            # conflicted cognitions must NOT be injected as ordinary entries —
            # the correct behavior is retrieving NEITHER of them (§6/§26)
            "expected_memory": [],
            "forbidden_memory": ["R-CONF-A", "R-CONF-B"],
            "expected_context_contains": [],
            "setup": "conflict",
        },
        {
            "id": "case-repeated-behavior",
            "queries": ["写一个销售查询 SQL"],
            "expected_memory": ["P-SQL-INDEX"],
            "forbidden_memory": [],
            "expected_context_contains": ["P-SQL-INDEX"],
        },
        {
            "id": "case-unrelated-memory",
            "queries": ["帮我制定猫粮采购计划"],
            "expected_memory": ["P-PET-001"],
            "forbidden_memory": ["R-SQL-001", "P-REPORT-001"],
            "expected_context_contains": ["P-PET-001"],
        },
        {
            "id": "case-project-specific-memory",
            "queries": ["帮我写一个销售查询 SQL"],
            "expected_memory": ["P-PROJ-BP"],
            "forbidden_memory": [],
            "expected_context_contains": ["P-PROJ-BP"],
            "scope": "project",
            "scope_id": "bp",
            "assert_priority_above": "P-SQL-CTE",
        },
    ]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class CaseResult:
    case_id: str
    query: str
    expected: list[str]
    forbidden: list[str]
    actual: list[str]
    ranks: dict[str, int] = field(default_factory=dict)  # memory_id → rank (1-based)
    recall_at5: float = 0.0
    precision_at5: float = 0.0
    reciprocal_rank: float = 0.0
    ok: bool = True


def evaluate_case(case: dict, query: str, retrieved_ids: list[str]) -> CaseResult:
    """Recall@5 / Precision@5 / RR for one query against one case."""
    expected = case["expected_memory"]
    forbidden = case["forbidden_memory"]
    top5 = retrieved_ids[:5]
    ranks = {mid: i + 1 for i, mid in enumerate(retrieved_ids) if mid in expected}

    hits = [m for m in expected if m in top5]
    recall = len(hits) / len(expected) if expected else 1.0
    # precision: expected hits minus forbidden leaks, over top-5 size
    forbidden_leaks = [m for m in forbidden if m in top5]
    relevant = len(hits)
    precision = (relevant - len(forbidden_leaks)) / len(top5) if top5 else 0.0
    rr = 0.0
    if expected:
        first_rank = min(ranks.values()) if ranks else None
        if first_rank is not None:
            rr = 1.0 / first_rank
    return CaseResult(
        case_id=case["id"],
        query=query,
        expected=expected,
        forbidden=forbidden,
        actual=top5,
        ranks=ranks,
        recall_at5=round(recall, 3),
        precision_at5=round(max(0.0, precision), 3),
        reciprocal_rank=round(rr, 3),
        ok=bool(hits) and not forbidden_leaks,
    )


def summarize(results: list[CaseResult]) -> dict:
    """Aggregate: mean Recall@5, mean Precision@5, MRR."""
    if not results:
        return {"recall_at5": 0.0, "precision_at5": 0.0, "mrr": 0.0, "n": 0}
    n = len(results)
    return {
        "recall_at5": round(sum(r.recall_at5 for r in results) / n, 3),
        "precision_at5": round(sum(r.precision_at5 for r in results) / n, 3),
        "mrr": round(sum(r.reciprocal_rank for r in results) / n, 3),
        "n": n,
    }
