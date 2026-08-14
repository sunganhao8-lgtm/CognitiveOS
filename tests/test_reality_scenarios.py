"""Phase 4 reality test — three-domain scenario chain (SQL / Report / General).

Proves the cognition chain works OUTSIDE the SQL domain: a preference
declared in any domain → remembered → retrieved → injected into context.
(The agent execution step itself is already proven by the Golden Path with
real Hermes; here the full cognitive chain runs on the real CLI/kernel
pipeline with a deterministic executor.)

Invariant: if all three domains apply, CognitiveOS is NOT SQL-specific
memory (task book §9).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.kernel import Context, DomainRouter, FileMemory, Kernel, Result
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime.now(timezone.utc) - timedelta(days=1)

SCENARIOS = [
    {
        "id": "sql",
        "declaration": "以后我的 SQL 查询不允许使用 SELECT *。",
        "task": "帮我写一个查询销售数据的 SQL。",
    },
    {
        "id": "reporting",
        "declaration": "以后我做的报表必须用横向宽表布局，表头带汇总行，不要竖排窄表。",
        "task": "帮我生成一份销售报表。",
    },
    {
        "id": "general",
        "declaration": "以后给我的汇报必须先给结论再给细节，不要一上来就铺细节。",
        "task": "帮我写一份项目进展汇报。",
    },
]


class RecordingAdapter:
    agent_id = "fake"

    def __init__(self):
        self.last_block = ""

    def execute(self, task, context):
        self.last_block = context.context_block
        return Result(task_id=task.id, status="success", output="(deterministic executor)")

    def bootstrap_query(self, prompt):
        return None


def _kernel(tmp_path: Path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    adapter = RecordingAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "m.jsonl"),
        router=DomainRouter([adapter]),
        adapters=[adapter],
        store=store, user=user, llm_fn=None, allow_semantic=False,
    )
    return paths, user, store, adapter, kernel


def test_three_domain_chain(tmp_path):
    """Declare → remember → retrieve → inject, in all three domains."""
    results = []
    for sc in SCENARIOS:
        ws = tmp_path / sc["id"]
        ws.mkdir(parents=True, exist_ok=True)
        paths, user, store, adapter, kernel = _kernel(ws)

        # 1. remember
        r1 = kernel.run_input(sc["declaration"])
        rule_id = r1.memory_written[0]
        assert r1.status == "learned", f"{sc['id']}: declaration must be learned"

        # 2. apply without repeating the declaration
        r2 = kernel.run_input(sc["task"])
        from cogos.classify import DOMAIN_SHORT

        expect_prefix = f"R-{DOMAIN_SHORT.get(sc['id'], sc['id'].upper())}"
        assert rule_id.startswith(expect_prefix), f"{sc['id']}: got {rule_id}, want {expect_prefix}*"
        assert rule_id in adapter.last_block, (
            f"{sc['id']}: rule {rule_id} must be injected into context"
        )
        # 3. the rule is usable by verification (has forbidden/required payload)
        ent = store.entity(rule_id)
        payload = ent.get("payload") or {}
        assert payload.get("forbidden") or payload.get("required"), (
            f"{sc['id']}: rule must carry executable patterns"
        )
        results.append({"domain": sc["id"], "rule_id": rule_id, "injected": True})
        store.close()

    # all three domains work → NOT SQL-specific
    assert len(results) == 3
    domains = {r["domain"] for r in results}
    assert {"sql", "reporting", "general"} <= domains


def test_report_and_general_do_not_require_sql(tmp_path):
    """The non-SQL rules must retrieve on their own domain tasks."""
    ws = tmp_path / "report"
    ws.mkdir(parents=True, exist_ok=True)
    paths, user, store, adapter, kernel = _kernel(ws)
    kernel.run_input("以后我做的报表要横向宽表布局，表头带汇总行。")
    kernel.run_input("帮我生成一份销售报表。")
    assert "横向宽表" in adapter.last_block, "report preference must surface"
    store.close()
