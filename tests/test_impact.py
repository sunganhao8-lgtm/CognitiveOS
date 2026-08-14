"""Phase 3G tests — impact definitions, benchmark cases, integrity invariants.

Every metric must be provable from real records:

    learned   = whitelist-subtype cognition formed in window (never episodic)
    retrieved = eligible hits (retrieved_total)
    applied   = pref/rule injected into context (refs)
    verified  = applied & verification PASS pairs
    avoided   = rule injected & verification PASS pairs (full chain)

Invariants (§24): applied ≤ retrieved; verified ≤ applied; avoided ≤ verified.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.dashboard_query import DashboardQuery
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer
from cogos import trace as trace_mod

TS0 = datetime.now(timezone.utc) - timedelta(days=5)
CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "impact_cases.json").read_text(encoding="utf-8")
)["cases"]


def _seed_case(tmp_path: Path, case: dict) -> Paths:
    """Seed one benchmark case: an execution + optional verifications."""
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    seed = case["seed"]
    refs = [{"type": "memory", "subtype": sub, "id": mid, "score": 0.01, "why": "test"}
            for mid, sub in seed.get("refs", [])]
    trace_mod.append_execution(user, store, {
        "execution_id": "ex-x", "task": "帮我写销售 SQL", "intent_type": "task",
        "agent_id": "fake", "status": "success",
        "verdict": "PASS" if any(v[2] == "PASS" for v in seed.get("verifications", [])) else "",
        "context_chars": 100, "started_at": TS0.isoformat(timespec="seconds"),
        "finished_at": TS0.isoformat(timespec="seconds"),
        "refs": refs,
        "retrieved_total": seed.get("retrieved_total", 0),
        "injected": len(refs),
    })
    for ex_id, rule_id, verdict in seed.get("verifications", []):
        trace_mod.append_verification(user, store, ex_id, rule_id, verdict, "t", TS0.isoformat(timespec="seconds"))
    store.close()
    return paths


def _build(tmp_path):
    q = DashboardQuery(paths := _seed_case(tmp_path, {})) if False else None
    return q


def _impact_for(tmp_path: Path):
    paths = Paths(root=tmp_path)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        ex = vm.recent_executions[0]
        ov = vm.overview
        return ex, ov
    finally:
        q.close()


# ---------------------------------------------------------------------------
# benchmark cases (fixtures/impact_cases.json)
# ---------------------------------------------------------------------------


def test_impact_cases_all_pass(tmp_path):
    """Every case in the frozen benchmark behaves exactly as defined."""
    for case in CASES:
        tmp2 = tmp_path / case["id"]
        paths = _seed_case(tmp2, case)
        q = DashboardQuery(paths)
        try:
            vm = q.build()
            ex = vm.recent_executions[0]
        finally:
            q.close()
        exp = case["expect"]
        assert ex.memory_impact == exp["impact"], f"{case['id']}: impact {ex.memory_impact} != {exp['impact']}"
        assert ex.applied == exp["applied"], f"{case['id']}: applied {ex.applied}"
        assert ex.verified == exp["verified"], f"{case['id']}: verified {ex.verified}"
        if "verification" in exp:
            assert ex.verification == exp["verification"], f"{case['id']}: verification {ex.verification}"


def test_no_memory_verify_pass_is_not_avoided(tmp_path):
    """§5: Verify PASS with no rule involvement must NOT count as avoided."""
    case = next(c for c in CASES if c["id"] == "case-verify-pass-no-rule")
    paths = _seed_case(tmp_path / "x", case)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.avoided_errors == 0
        assert vm.overview.verified == 0  # nothing applied → nothing verified
    finally:
        q.close()


def test_retrieved_not_applied_is_not_applied(tmp_path):
    """§16: retrieved but not injected → RETRIEVED, never APPLIED."""
    case = next(c for c in CASES if c["id"] == "case-retrieved-not-applied")
    paths = _seed_case(tmp_path / "x", case)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        ex = vm.recent_executions[0]
        assert ex.memory_impact == "RETRIEVED"
        assert ex.applied == 0
        assert vm.overview.applied == 0
    finally:
        q.close()


def test_preference_pass_is_verified_but_not_avoided(tmp_path):
    """§19: preference applied + PASS → verified, NOT an avoided error."""
    case = next(c for c in CASES if c["id"] == "case-applied-preference-pass")
    paths = _seed_case(tmp_path / "x", case)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.verified == 1
        assert vm.overview.avoided_errors == 0
    finally:
        q.close()


def test_rule_applied_pass_is_avoided(tmp_path):
    """§6: full chain (rule + injected + PASS) → avoided_error."""
    case = next(c for c in CASES if c["id"] == "case-applied-rule-pass")
    paths = _seed_case(tmp_path / "x", case)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.avoided_errors == 1
        assert vm.overview.verified == 1
        # evidence list answers "why this number" (§14)
        assert vm.overview.avoided_errors_evidence[0]["rule_id"] == "R-SQL-001"
        assert vm.overview.avoided_errors_evidence[0]["execution_id"] == "ex-x"
    finally:
        q.close()


def test_rule_applied_fail_is_not_avoided(tmp_path):
    """§6: applied + FAIL → no avoided error."""
    case = next(c for c in CASES if c["id"] == "case-applied-rule-fail")
    paths = _seed_case(tmp_path / "x", case)
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        ex = vm.recent_executions[0]
        assert ex.memory_impact == "APPLIED"
        assert ex.verification == "FAIL"
        assert vm.overview.avoided_errors == 0
    finally:
        q.close()


def test_learned_never_counts_episodic(tmp_path):
    """§3: episodic writes are NOT learning."""
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    # an episodic memory created in the window
    store.upsert_entity(
        "mem-e1", "memory", subtype="episodic", domain="sql",
        content="[PASS] task 1", payload={"source": "execution"},
        status="", created_at=TS0.isoformat(timespec="seconds"),
    )
    # a real preference formed in the window
    store.upsert_entity(
        "P-SQL-001", "memory", subtype="preference", domain="sql",
        content="SQL 偏好 CTE", payload={"source": "user_statement"},
        status="confirmed", confidence=0.9, created_at=TS0.isoformat(timespec="seconds"),
    )
    store.close()
    q = DashboardQuery(paths)
    try:
        vm = q.build()
        assert vm.overview.learned == 1, "episodic must not count as learned"
    finally:
        q.close()
