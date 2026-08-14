"""Phase 3E integration tests — the FULL correction loop:

    user action (CLI/Service) → canonical → SQLite → trace →
    next retrieval → agent behavior change

and the rejected-pattern lifecycle (§20 no immediate resurrection,
§21 new explicit evidence may revive).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.growth import run_sleep
from cogos.kernel import Context, DomainRouter, FileMemory, Kernel, Result
from cogos.memory_service import MemoryService
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


class FakeAdapter:
    agent_id = "fake"

    def __init__(self, output="SELECT id FROM sales"):
        self.output = output
        self.last_block = ""

    def execute(self, task, context):
        self.last_block = context.context_block
        return Result(task_id=task.id, status="success", output=self.output)

    def bootstrap_query(self, prompt):
        return None


def _kernel(tmp_path: Path, output="SELECT id FROM sales"):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    adapter = FakeAdapter(output)
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "m.jsonl"),
        router=DomainRouter([adapter]),
        adapters=[adapter],
        store=store, user=user, llm_fn=None, allow_semantic=False,
    )
    return paths, user, store, adapter, kernel


def _episodic(i, *, features=None, verdict="PASS", created=TS0):
    return {
        "id": f"mem-e{i:03d}", "type": "episodic", "domain": "sql",
        "content": f"[{verdict}] task {i}", "source": "execution",
        "derived_from_execution": f"ex-20260801-{i:06d}",
        "verdict": verdict, "refs": [], "features": features or [],
        "created_at": created.isoformat(timespec="seconds"),
    }


def _seed_episodics(user: UserLayer, rows: list[dict]) -> None:
    user.memory.mkdir(parents=True, exist_ok=True)
    (user.memory / "episodic.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


# ---------------------------------------------------------------------------
# Case C (end-to-end): forget → next run → cognition gone from context
# ---------------------------------------------------------------------------


def test_forget_changes_agent_behavior_end_to_end(tmp_path):
    """§14: forget must change what the AGENT receives, not just the db."""
    paths, user, store, adapter, kernel = _kernel(tmp_path)
    # a confirmed preference about SQL aliases
    store.upsert_entity(
        "P-ALIAS-001", "memory", subtype="preference", domain="sql",
        content="写 SQL 时给表起简短别名（s、o、p）",
        payload={"source": "user_statement"}, status="confirmed",
        confidence=0.9, user_confirmed=True, version=1,
        created_at=TS0.isoformat(timespec="seconds"),
    )
    store.add_fts("P-ALIAS-001", "memory", "preference", "sql", "写 SQL 时给表起简短别名（s、o、p）")

    r1 = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert "P-ALIAS-001" in adapter.last_block, "before: preference injected"

    svc = MemoryService(paths)
    try:
        svc.forget("P-ALIAS-001")
    finally:
        svc.close()
    kernel.store = Store(paths.cache / "cognitive.db")  # fresh handle, same data

    r2 = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert "P-ALIAS-001" not in adapter.last_block, "after: preference gone from agent context"
    assert r2.status == "success"


# ---------------------------------------------------------------------------
# §20 / §21 — rejected pattern lifecycle
# ---------------------------------------------------------------------------


def test_rejected_pattern_does_not_resurface_after_sleep(tmp_path):
    """§20: sleep must not immediately recreate a rejected candidate."""
    paths, user, store = _ws = _kernel(tmp_path)[:3]
    _seed_episodics(user, [_episodic(1, features=["sql:uses_cte"])])
    store.reindex(paths)
    run_sleep(user, store, now=TS0 + timedelta(days=2))
    cand_id = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])["id"]

    svc = MemoryService(paths)
    try:
        svc.reject(cand_id, reason="wrong inference")
    finally:
        svc.close()

    # MORE evidence for the same pattern arrives
    _seed_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=3)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=4)),
    ])
    store2 = Store(paths.cache / "cognitive.db")
    try:
        store2.reindex(paths)
        report = run_sleep(user, store2, now=TS0 + timedelta(days=5))
        # the same pattern must NOT come back as a fresh candidate
        rows = [json.loads(l) for l in (user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        assert all(r["id"] != cand_id or r["status"] == "rejected" for r in rows), \
            "rejected candidate must not be resurrected"
        assert not report.memories_promoted, "suppressed pattern must not promote"
    finally:
        store2.close()


def test_new_explicit_statement_can_revive_rejected_concept(tmp_path):
    """§21: explicit new user evidence revives a previously rejected pattern."""
    paths, user, store = _kernel(tmp_path)[:3]
    _seed_episodics(user, [_episodic(1, features=["sql:uses_cte"])])
    store.reindex(paths)
    run_sleep(user, store, now=TS0 + timedelta(days=2))
    cand_id = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])["id"]

    svc = MemoryService(paths)
    try:
        svc.reject(cand_id, reason="wrong inference")
    finally:
        svc.close()

    # the user EXPLICITLY declares CTE preference AFTER the rejection
    # (real path: kernel._learn_rule writes BOTH canonical and store)
    from datetime import datetime as _dt, timezone as _tz

    now_real = _dt.now(_tz.utc)
    store2 = Store(paths.cache / "cognitive.db")
    try:
        store2.upsert_entity(
            "R-EXPLICIT-001", "memory", subtype="rule", domain="sql",
            content="以后我的 SQL 可以使用 CTE", payload={"source": "user_statement"},
            status="confirmed", user_confirmed=True, confidence=0.95,
            created_at=now_real.isoformat(),  # microseconds: later than the rejection
        )
        store2.add_fts("R-EXPLICIT-001", "memory", "rule", "sql", "以后我的 SQL 可以使用 CTE")
        # canonical mirror (what a real explicit statement leaves behind)
        rules_dir = user.root / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "R-EXPLICIT-001.json").write_text(json.dumps({
            "id": "R-EXPLICIT-001", "domain": "sql", "rule_zh": "以后我的 SQL 可以使用 CTE",
            "source": "user_statement", "status": "confirmed", "user_confirmed": True,
            "created_at": now_real.isoformat(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        store2.close()
    store3 = Store(paths.cache / "cognitive.db")
    try:
        store3.reindex(paths)
        from cogos.growth import _is_rejected_pattern
        assert _is_rejected_pattern(user, "sql", "sql:uses_cte", store=store3,
                                    now=now_real + timedelta(seconds=2)) is False, \
            "new explicit statement must revive the concept"
    finally:
        store3.close()


# ---------------------------------------------------------------------------
# Case D end-to-end: modify → retrieval sees only v2
# ---------------------------------------------------------------------------


def test_modify_changes_retrieval_immediately(tmp_path):
    paths, user, store, adapter, kernel = _kernel(tmp_path)
    store.upsert_entity(
        "P-SQL-001", "memory", subtype="preference", domain="sql",
        content="SQL 偏好使用 CTE", payload={"source": "user_statement"},
        status="confirmed", confidence=0.91, evidence_count=3, version=1,
        created_at=TS0.isoformat(timespec="seconds"),
    )
    store.add_fts("P-SQL-001", "memory", "preference", "sql", "SQL 偏好使用 CTE")

    svc = MemoryService(paths)
    try:
        new_id = svc.modify("P-SQL-001", "复杂 SQL 使用 CTE，简单 SQL 优先子查询")["new"]
    finally:
        svc.close()

    kernel.store = Store(paths.cache / "cognitive.db")
    r = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert new_id in adapter.last_block, "new version must be injected"
    assert "P-SQL-001" not in adapter.last_block, "superseded version must not be injected"
    assert r.status == "success"
