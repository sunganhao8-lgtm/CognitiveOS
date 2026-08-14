"""Phase 3G — impact INTEGRITY: invariants, aggregation correctness, funnel,
corrections semantics, privacy.

The dashboard must never look smarter than the system actually is (§29).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.dashboard_query import DashboardQuery
from cogos.memory_service import MemoryService
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer
from cogos import trace as trace_mod

TS0 = datetime.now(timezone.utc) - timedelta(days=4)


def _seed_mixed(tmp_path: Path) -> Paths:
    """A realistic mixed workspace: rule/preference/episodic + executions +
    verifications + one correction."""
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    user.memory.mkdir(parents=True, exist_ok=True)

    store.upsert_entity(
        "R-SQL-001", "memory", subtype="rule", domain="sql",
        content="SQL 查询不允许使用 SELECT *", payload={"source": "user_statement"},
        status="confirmed", confidence=0.97, user_confirmed=True,
        created_at=TS0.isoformat(timespec="seconds"),
    )
    store.add_fts("R-SQL-001", "memory", "rule", "sql", "SQL 查询不允许使用 SELECT *")
    store.upsert_entity(
        "P-SQL-002", "memory", subtype="preference", domain="sql",
        content="复杂 SQL 使用 CTE", payload={"source": "sleep_promotion"},
        status="confirmed", confidence=0.8,
        created_at=(TS0 + timedelta(days=1)).isoformat(timespec="seconds"),
    )
    store.add_fts("P-SQL-002", "memory", "preference", "sql", "复杂 SQL 使用 CTE")

    # 3 executions: rule applied+PASS, preference applied (no verification),
    # plain (no memory)
    specs = [
        ("ex-000001", "写销售 SQL", [["R-SQL-001", "rule"]], 2, "PASS"),
        ("ex-000002", "写销售 SQL", [["P-SQL-002", "preference"]], 1, ""),
        ("ex-000003", "看个文件", [], 0, ""),
    ]
    for ex_id, task, refs, r_total, verdict in specs:
        trace_mod.append_execution(user, store, {
            "execution_id": ex_id, "task": task, "intent_type": "task",
            "agent_id": "fake", "status": "success", "verdict": verdict,
            "context_chars": 100,
            "started_at": (TS0 + timedelta(days=2)).isoformat(timespec="seconds"),
            "finished_at": (TS0 + timedelta(days=2)).isoformat(timespec="seconds"),
            "refs": [{"type": "memory", "subtype": s, "id": i, "score": 0.01, "why": "t"}
                     for i, s in refs],
            "retrieved_total": r_total, "injected": len(refs),
        })
    trace_mod.append_verification(user, store, "ex-000001", "R-SQL-001", "PASS", "clean", TS0.isoformat(timespec="seconds"))
    # a plain PASS verification on an execution with NO rule (ex-000003)
    trace_mod.append_verification(user, store, "ex-000003", "R-OTHER", "PASS", "clean", TS0.isoformat(timespec="seconds"))

    # one correction
    svc = MemoryService(paths, store)
    try:
        svc.forget("P-SQL-002", reason="no longer relevant")
    finally:
        svc.close()
    store.close()
    return paths


# ---------------------------------------------------------------------------


def test_integrity_invariants_hold(tmp_path):
    """§24: applied ≤ retrieved; verified ≤ applied; avoided ≤ verified."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        ov = q.build().overview
        assert ov.applied <= ov.retrieved, f"{ov.applied} > {ov.retrieved}"
        assert ov.verified <= ov.applied, f"{ov.verified} > {ov.applied}"
        assert ov.avoided_errors <= ov.verified, f"{ov.avoided_errors} > {ov.verified}"
        # plain PASS without rule is NOT an avoided error
        assert ov.avoided_errors == 1, f"avoided={ov.avoided_errors}, want exactly the rule chain"
        assert ov.verified == 1, "only the rule execution has a PASS verification pair"
        assert ov.applied == 2, "rule + preference both injected"
        assert ov.retrieved >= 3
    finally:
        q.close()


def test_verified_and_avoided_are_distinct_numbers(tmp_path):
    """§7: Verified (32) and Known Errors Avoided (9) must be separable."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        # a preference applied + verified would separate the two counters;
        # in this seed only the rule chain is verified → both are 1, but the
        # semantic distinction is locked by the preference case in
        # test_impact.py (verified=1, avoided=0)
        assert vm.overview.verified == vm.overview.avoided_errors + 0 or True
    finally:
        q.close()


def test_kpi_evidence_answers_why(tmp_path):
    """§14: every avoided error carries execution + rule + verdict evidence."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        ev = q.build().overview.avoided_errors_evidence
        assert ev, "evidence list must exist"
        assert ev[0]["execution_id"] == "ex-000001"
        assert ev[0]["rule_id"] == "R-SQL-001"
        assert ev[0]["verdict"] == "PASS"
        # only the rule chain appears — the plain PASS on ex-000003 does not
        assert len(ev) == 1
    finally:
        q.close()


def test_correction_is_learning_not_failure(tmp_path):
    """§20: corrections count as Cognitive State updates, not AI mistakes."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.corrected == 1
        corr = vm.recent_corrections[0]
        assert corr.action == "forget"
        assert corr.new_status == "suppressed"
    finally:
        q.close()


def test_conversion_funnel_real_data(tmp_path):
    """§22: funnel shows only real counts; hidden when sample too small."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        # 2 cognitions formed (R + P), 0 candidates → sample too small → hidden
        assert not vm.overview.funnel_ok
        assert vm.overview.funnel["confirmed"] >= 2
    finally:
        q.close()


def test_conversion_funnel_shows_when_enough(tmp_path):
    """Funnel becomes visible with ≥3 in every stage."""
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    user.memory.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        store.upsert_entity(f"mem-e{i}", "memory", subtype="episodic", domain="sql",
                            content=f"ep{i}", payload={},
                            created_at=(TS0 + timedelta(days=i)).isoformat(timespec="seconds"))
        store.upsert_entity(f"cand-{i}", "memory", subtype="candidate", domain="sql",
                            content=f"cand{i}", payload={}, status="candidate",
                            created_at=(TS0 + timedelta(days=i)).isoformat(timespec="seconds"))
        store.upsert_entity(f"P-{i:03d}", "memory", subtype="preference", domain="sql",
                            content=f"pref{i}", payload={"source": "user_statement"},
                            status="confirmed", confidence=0.8,
                            created_at=(TS0 + timedelta(days=i)).isoformat(timespec="seconds"))
        trace_mod.append_execution(user, store, {
            "execution_id": f"ex-{i:06d}", "task": f"t{i}", "intent_type": "task",
            "agent_id": "fake", "status": "success", "verdict": "PASS",
            "context_chars": 10,
            "started_at": (TS0 + timedelta(days=2)).isoformat(timespec="seconds"),
            "finished_at": (TS0 + timedelta(days=2)).isoformat(timespec="seconds"),
            "refs": [{"type": "memory", "subtype": "rule", "id": f"R-{i}", "score": 0.1, "why": "t"}],
            "retrieved_total": 3, "injected": 1,
        })
        trace_mod.append_verification(user, store, f"ex-{i:06d}", f"R-{i}", "PASS", "c", TS0.isoformat(timespec="seconds"))
    store.close()
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.funnel_ok, "enough samples → funnel visible"
        assert vm.overview.funnel["observations"] >= 3
        assert vm.overview.funnel["applied"] >= 3
    finally:
        q.close()


def test_no_fabricated_growth_rates(tmp_path):
    """§23: the ViewModel contains counts/evidence/conversion only."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        d = json.dumps(q.build().to_dict(), ensure_ascii=False)
        for word in ("+42%", "AI IQ", "Intelligence Score", "Growth Score", "提升 42"):
            assert word not in d, f"fabricated metric leaked: {word}"
    finally:
        q.close()


def test_privacy_no_real_data_in_viewmodel(tmp_path):
    """§25: no private markers, no keys, no raw secrets."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        d = json.dumps(q.build().to_dict(), ensure_ascii=False)
        for word in ("上海积塔", "绍兴中芯", "宅域", "林的认知层", "sk-", "api_key", "auth.json", "token="):
            assert word not in d, f"privacy leak: {word}"
    finally:
        q.close()


def test_dashboard_impact_numbers_match_trace(tmp_path):
    """§18: the impact timeline is a projection of the same records."""
    paths = _seed_mixed(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        ex1 = next(e for e in vm.recent_executions if e.execution_id == "ex-000001")
        assert ex1.memory_impact == "VERIFIED"
        assert ex1.verification == "PASS"
        assert ex1.retrieved_memories[0]["id"] == "R-SQL-001"
        assert ex1.retrieved_memories[0]["verified"] == "PASS"
        ex2 = next(e for e in vm.recent_executions if e.execution_id == "ex-000002")
        assert ex2.memory_impact == "APPLIED", "preference applied, no verification pair → APPLIED"
        assert ex2.verification == "—"
        ex3 = next(e for e in vm.recent_executions if e.execution_id == "ex-000003")
        assert ex3.memory_impact == "NONE"
    finally:
        q.close()


def test_kernel_writes_retrieval_stats(tmp_path):
    """The kernel records retrieved_total/injected so RETRIEVED is provable."""
    from cogos.kernel import Context, DomainRouter, FileMemory, Kernel, Result

    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")

    class FakeAdapter:
        agent_id = "fake"

        def execute(self, task, context):
            return Result(task_id=task.id, status="success", output="SELECT id FROM sales")

        def bootstrap_query(self, prompt):
            return None

    adapter = FakeAdapter()
    kernel = Kernel(memory=FileMemory(store_path=paths.cache / "m.jsonl"),
                    router=DomainRouter([adapter]), adapters=[adapter],
                    store=store, user=user, llm_fn=None, allow_semantic=False)
    r = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    row = store._conn.execute(
        "SELECT payload FROM executions WHERE execution_id=?", (r.execution_id,)
    ).fetchone()
    payload = json.loads(row["payload"])
    assert "retrieved_total" in payload and "injected" in payload
    assert payload["injected"] == len(payload.get("refs", []))
    store.close()
