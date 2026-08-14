"""Phase 3F tests — Cognitive Dashboard 2.0: ViewModel truth, snapshot
fixture, no hardcoded cognition, no direct store mutation from the dashboard.

Fixture workspace (synthetic, no real user data): 3 confirmed cognitions,
2 candidates, 1 conflict, 2 corrections, 5 executions, ≥10 trace events.
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

TS0 = datetime.now(timezone.utc) - timedelta(days=10)


def _ts(days: int) -> str:
    return (TS0 + timedelta(days=days)).isoformat(timespec="seconds")


def _build_fixture(tmp_path: Path) -> Paths:
    """3 confirmed + 2 candidates + 1 conflict + 2 corrections + 5 execs."""
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    user.memory.mkdir(parents=True, exist_ok=True)

    def mem(ent_id, subtype, content, *, status="confirmed", domain="sql",
            confidence=0.9, evidence=3, vpass=2, version=1, scope="global",
            created=_ts(6), source="user_statement", user_confirmed=False,
            fts=True):
        store.upsert_entity(
            ent_id, "memory", subtype=subtype, domain=domain, content=content,
            payload={"source": source, "source_executions": ["ex-1", "ex-2", "ex-3"]},
            status=status, confidence=confidence, evidence_count=evidence,
            verify_pass_count=vpass, version=version, scope=scope,
            user_confirmed=user_confirmed, created_at=created,
        )
        if fts:
            store.add_fts(ent_id, "memory", subtype, domain, content)

    # 3 confirmed cognitions
    mem("R-SQL-001", "rule", "SQL 查询不允许使用 SELECT *", created=_ts(0))
    mem("P-SQL-002", "preference", "复杂 SQL 使用 CTE", created=_ts(1), confidence=0.93)
    mem("P-REPORT-001", "preference", "报表偏好横向宽表", domain="reporting",
        created=_ts(2), confidence=0.81)
    # 2 candidates
    mem("cand-sql-x", "candidate", "用户似乎喜欢给表起简短别名",
        status="candidate", confidence=0.64, evidence=4, fts=False)
    mem("cand-rpt-y", "candidate", "用户似乎偏好列顺序固定", domain="reporting",
        status="candidate", confidence=0.55, evidence=2, fts=False)
    # 1 conflict (deterministic pair)
    mem("R-CONF-A", "rule", "SQL 必须使用 CTE", status="conflicted", fts=False)
    mem("R-CONF-B", "rule", "SQL 禁止使用 CTE", status="conflicted", fts=False)

    # 5 executions with refs (some applied + PASS, some plain)
    for i, (task, refs, verdict, status) in enumerate([
        ("帮我写销售 SQL", [{"type": "memory", "subtype": "rule", "id": "R-SQL-001", "score": 0.01, "why": "关键词命中"}], "PASS", "success"),
        ("帮我写销售 SQL", [{"type": "memory", "subtype": "preference", "id": "P-SQL-002", "score": 0.02, "why": "语义相似"}], "PASS", "success"),
        ("写一份周报", [{"type": "memory", "subtype": "preference", "id": "P-REPORT-001", "score": 0.03, "why": "关键词命中"}], "PASS", "success"),
        ("查一下文件", [], "", "success"),
        ("写销售 SQL", [{"type": "memory", "subtype": "episodic", "id": "mem-e1", "score": 0.04, "why": "相关记忆"}], "FAIL", "failed"),
    ]):
        ex_id = f"ex-20260802-{i + 1:06d}"
        trace_mod.append_execution(user, store, {
            "execution_id": ex_id, "task": task, "intent_type": "task",
            "agent_id": "fake", "status": status, "verdict": verdict,
            "context_chars": 100, "started_at": _ts(4 + i),
            "finished_at": _ts(4 + i), "refs": refs,
        })

    # verifications (avoided errors = rule applied + verify PASS; verified
    # = applied & PASS pairs — each execution's ref gets its own record)
    trace_mod.append_verification(user, store, "ex-20260802-000001", "R-SQL-001", "PASS", "code_blocks clean", _ts(5))
    trace_mod.append_verification(user, store, "ex-20260802-000002", "P-SQL-002", "PASS", "code_blocks clean", _ts(5))
    trace_mod.append_verification(user, store, "ex-20260802-000003", "P-REPORT-001", "PASS", "code_blocks clean", _ts(5))

    # 2 corrections via MemoryService (real user_corrected traces)
    svc = MemoryService(paths, store)
    try:
        svc.forget("P-REPORT-001", reason="no longer relevant")
        svc.modify("P-SQL-002", "复杂 SQL 使用 CTE，简单 SQL 优先子查询")
    finally:
        svc.close()
    store.close()
    return paths


# ---------------------------------------------------------------------------


def test_viewmodel_overview_real_numbers(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        ov = vm.overview
        # learned: real cognition formation (preference/rule/semantic), NOT
        # episodic writes (Phase 3G integrity)
        assert ov.learned >= 3
        # applied: injected pref/rule refs (no PASS condition — 3G)
        assert ov.applied >= 2
        assert ov.verified >= 3, "applied & PASS pairs must aggregate"
        # only the RULE chain counts as avoided error — the two preference
        # PASS pairs are verified but NOT avoided errors (§19)
        assert ov.avoided_errors == 1, "rule + injected + PASS full chain (preferences excluded)"
        assert ov.corrected >= 2, "two user corrections must appear"
        assert ov.retrieved >= 4, "retrieved_total aggregation"
        assert ov.conflicts_pending >= 1
        assert ov.candidates_pending >= 2
        # integrity invariants (§24)
        assert ov.applied <= ov.retrieved
        assert ov.verified <= ov.applied
        assert ov.avoided_errors <= ov.verified
    finally:
        q.close()


def test_candidates_separated_from_confirmed(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        cand_ids = {c.id for c in vm.candidates}
        assert "cand-sql-x" in cand_ids and "cand-rpt-y" in cand_ids
        learning_ids = {c.id for c in vm.recent_learning}
        assert not (cand_ids & learning_ids), "candidates must never mix with confirmed"
        # candidates carry the pending note
        assert vm.candidates[0].content
    finally:
        q.close()


def test_conflicts_present(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.conflicts, "conflicted entities must surface"
        assert all(c.a_id.startswith("R-CONF") for c in vm.conflicts)
    finally:
        q.close()


def test_corrections_present(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        actions = {c.action for c in vm.recent_corrections}
        assert "forget" in actions and "modify" in actions
        modify = next(c for c in vm.recent_corrections if c.action == "modify")
        assert modify.old_version == 1 and modify.new_version == 2
    finally:
        q.close()


def test_execution_memory_impact(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        by_id = {e.execution_id: e for e in vm.recent_executions}
        high = by_id["ex-20260802-000001"]
        assert high.retrieved == 1 and high.applied == 1 and high.verdict == "PASS"
        assert high.verified == 1
        assert high.memory_impact == "VERIFIED", "applied + verification PASS → VERIFIED (Phase 3G)"
        low = by_id["ex-20260802-000004"]
        assert low.retrieved == 0 and low.memory_impact == "NONE"
        med = by_id["ex-20260802-000005"]
        # episodic-only refs: applied=0 but retrieved≥1 → RETRIEVED (not APPLIED)
        assert med.applied == 0 and med.retrieved >= 1 and med.memory_impact == "RETRIEVED"
    finally:
        q.close()


def test_retrieval_explanation_present(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        any_why = any(
            m.get("why") for e in vm.recent_executions for m in e.retrieved_memories
        )
        assert any_why, "retrieved memories must carry why_retrieved"
    finally:
        q.close()


def test_health_real(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        h = vm.cognitive_health
        assert h.memory_count >= 3
        assert h.conflicts_unresolved >= 1
        assert h.schema_version >= 4
    finally:
        q.close()


def test_no_hardcoded_privacy(tmp_path):
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        blob = json.dumps(vm.to_dict(), ensure_ascii=False)
        for word in ("上海积塔", "绍兴中芯", "宅域", "林的认知层"):
            assert word not in blob, f"privacy word leaked into ViewModel: {word}"
    finally:
        q.close()


def test_dashboard_never_mutates_store(tmp_path):
    """§2: the dashboard (query layer) must be read-only."""
    paths = _build_fixture(tmp_path)
    store = Store(paths.cache / "cognitive.db")
    before = store._conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
    store.close()
    q = DashboardQuery(paths)
    q.build()
    q.close()
    store2 = Store(paths.cache / "cognitive.db")
    after = store2._conn.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0]
    store2.close()
    assert before == after, "dashboard query must not write anything"


def test_viewmodel_independent_generation(tmp_path):
    """§20/§22-12: one build pass produces the complete VM."""
    paths = _build_fixture(tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        d = vm.to_dict()
        for key in ("overview", "recent_learning", "candidates", "active_cognitions",
                    "conflicts", "recent_corrections", "timeline", "recent_executions",
                    "cognitive_health", "brain_regions"):
            assert key in d
    finally:
        q.close()


def test_render_dashboard_uses_viewmodel(tmp_path):
    """bootstrap renders the cockpit sections with real numbers."""
    from cogos.dashboard import render_dashboard

    paths = _build_fixture(tmp_path)
    render_dashboard(paths)
    html = (paths.root / "index.html").read_text(encoding="utf-8")
    assert "你的 CognitiveOS 最近发生了什么" in html
    assert "R-SQL-001" in html
    assert "正在形成的认知" in html and "cand-sql-x" in html
    assert "VERIFIED" in html or "Memory Impact" in html
