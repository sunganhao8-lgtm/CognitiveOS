"""Phase 3B tests — conflict detection & resolution, scope precedence,
temporary override lifecycle.

Deterministic fixtures only; the LLM judge (when involved) is stubbed.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.conflict import (
    Conflict,
    detect_conflicts,
    resolve_conflict,
    rule_rule_conflict,
)
from cogos.kernel import Context, DomainRouter, FileMemory, Kernel, Result
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime(2026, 8, 10, 10, 0, 0, tzinfo=timezone.utc)


def _ws(tmp_path: Path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    return paths, user, store


def _rule(rid, *, forbidden=(), required=(), scope="global", scope_id="", source="user_statement",
          user_confirmed=True, created=TS0, confidence=0.95):
    return {
        "id": rid,
        "type": "memory",
        "subtype": "rule",
        "domain": "sql",
        "content": f"rule {rid}",
        "status": "confirmed",
        "scope": scope,
        "scope_id": scope_id,
        "version": 1,
        "user_confirmed": int(user_confirmed),
        "confidence": confidence,
        "created_at": created.isoformat(timespec="seconds"),
        "payload": {"id": rid, "forbidden": list(forbidden), "required": list(required),
                    "source": source, "rule_zh": f"rule {rid}"},
    }


def _seed_entity(store: Store, spec: dict) -> None:
    store.upsert_entity(
        spec["id"], spec["type"], subtype=spec["subtype"], domain=spec["domain"],
        content=spec["content"], payload=spec["payload"],
        created_at=spec["created_at"], status=spec["status"],
        confidence=spec.get("confidence"), user_confirmed=bool(spec.get("user_confirmed")),
        scope=spec.get("scope", "global"), scope_id=spec.get("scope_id", ""),
        version=spec.get("version", 1),
    )
    store.add_fts(spec["id"], "memory", spec["subtype"], spec["domain"], spec["content"])


# ---------------------------------------------------------------------------
# Conflict detection (deterministic)
# ---------------------------------------------------------------------------


def test_rule_rule_conflict_detected():
    a = _rule("R-A", forbidden=["SELECT *"])
    b = _rule("R-B", required=["SELECT *"])
    assert rule_rule_conflict(a, b)


def test_rule_rule_no_conflict_when_compatible():
    a = _rule("R-A", forbidden=["SELECT *"])
    b = _rule("R-B", forbidden=["SELECT *"])
    assert not rule_rule_conflict(a, b)


def test_detect_conflicts_finds_rule_pair(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-A", forbidden=["CTE"]))
    _seed_entity(store, _rule("R-B", required=["CTE"]))
    conflicts = detect_conflicts(store, "sql")
    assert any(c.kind == "rule_rule" and {c.a_id, c.b_id} == {"R-A", "R-B"} for c in conflicts)


def test_unresolved_conflict_stays_conflicted(tmp_path):
    """No scope/source/confirmation difference → NO winner is picked (§19)."""
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-A", forbidden=["CTE"], source="manual", user_confirmed=True))
    _seed_entity(store, _rule("R-B", required=["CTE"], source="manual", user_confirmed=True))
    conflicts = detect_conflicts(store, "sql")
    assert conflicts
    c = resolve_conflict(store, conflicts[0])
    assert not c.resolved
    assert c.winner == ""


def test_scope_outranks_time(tmp_path):
    """A project-scoped rule wins over a NEWER global rule (§5: time never
    outranks scope)."""
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-GLOBAL", forbidden=["SELECT *"], scope="global",
                              created=TS0 + timedelta(days=3)))
    _seed_entity(store, _rule("R-PROJ", required=["SELECT *"], scope="project",
                              scope_id="bp", created=TS0))
    conflicts = detect_conflicts(store, "sql")
    assert conflicts
    c = resolve_conflict(store, conflicts[0])
    assert c.resolved and c.winner == "R-PROJ"


def test_explicit_user_statement_beats_behavior_evidence(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-STATEMENT", forbidden=["SELECT *"], source="user_statement"))
    _seed_entity(store, _rule("R-BEHAVIOR", required=["SELECT *"], source="sleep_promotion",
                              user_confirmed=False))
    conflicts = detect_conflicts(store, "sql")
    assert conflicts
    c = resolve_conflict(store, conflicts[0])
    assert c.resolved and c.winner == "R-STATEMENT"
    assert "explicit user statement" in c.reason


def test_newer_confirmed_wins_in_same_scope(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-OLD", forbidden=["SELECT *"], created=TS0))
    _seed_entity(store, _rule("R-NEW", required=["SELECT *"], created=TS0 + timedelta(days=1)))
    conflicts = detect_conflicts(store, "sql")
    c = resolve_conflict(store, conflicts[0])
    assert c.resolved and c.winner == "R-NEW"


# ---------------------------------------------------------------------------
# Temporary override lifecycle (kernel-level, deterministic fake)
# ---------------------------------------------------------------------------


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
    paths, user, store = _ws(tmp_path)
    adapter = FakeAdapter(output)
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "m.jsonl"),
        router=DomainRouter([adapter]),
        adapters=[adapter],
        store=store, user=user, llm_fn=None, allow_semantic=False,
    )
    return paths, user, store, adapter, kernel


def test_temporary_overrides_global_rule(tmp_path):
    paths, user, store, adapter, kernel = _kernel(tmp_path)
    # global rule: no SELECT *
    kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    # temporary: this time SELECT * is fine
    r_tmp = kernel.run_input("这次我的 SQL 可以用 SELECT *。")
    assert r_tmp.status == "learned"
    assert r_tmp.memory_written[0].startswith("tmp-")
    # next task consumes the temporary: agent "uses" SELECT *
    r_task = kernel.run_input("帮我写一个查询销售数据的 SQL。", )
    # rule R-SQL-001 was overridden → verification skipped → no FAIL
    assert r_task.status in ("success", "failed")
    assert r_task.verdict != "FAIL"
    assert "任务级临时例外" in adapter.last_block
    # temporary expired after consumption
    temps = store.active_temporaries()
    assert temps == [], "temporary must expire after its consuming task"


def test_global_rule_restored_after_temporary(tmp_path):
    paths, user, store, adapter, kernel = _kernel(tmp_path, output="SELECT * FROM sales")
    kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    kernel.run_input("这次我的 SQL 可以用 SELECT *。")
    r_task = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    # overridden during the temporary → not FAIL
    assert r_task.verdict != "FAIL"
    # NEXT task: temporary gone → rule enforced again → FAIL (SELECT * present)
    r_task2 = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert r_task2.verdict == "FAIL", "global rule must be restored after temporary expires"


def test_superseded_memory_not_retrieved(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-OLD", forbidden=["SELECT *"]))
    store.supersede("R-OLD", "R-NEW", reason="test")
    hits = store.search("SELECT", types=("memory",))
    assert not any(h.ent_id == "R-OLD" for h in hits)


def test_old_confidence_preserved_after_supersede(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-OLD", forbidden=["SELECT *"], confidence=0.91))
    store.supersede("R-OLD", "R-NEW", reason="test")
    old = store.entity("R-OLD")
    assert old["status"] == "superseded"
    assert old["confidence"] == 0.91, "historical confidence must not be touched"


def test_candidate_never_in_context_even_during_conflicts(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed_entity(store, _rule("R-A", forbidden=["CTE"], source="manual"))
    _seed_entity(store, _rule("R-B", required=["CTE"], source="manual"))
    # seed a candidate about CTE — it must never be retrieved
    store.upsert_entity(
        "cand-x", "memory", subtype="candidate", domain="sql",
        content="用户似乎喜欢 CTE", payload={}, status="candidate",
    )
    store.add_fts("cand-x", "memory", "candidate", "sql", "用户似乎喜欢 CTE")
    hits = store.search("CTE", types=("memory",))
    assert not any(h.ent_id == "cand-x" for h in hits)
    conflicts = detect_conflicts(store, "sql")
    assert conflicts  # the real conflict is still detected


def test_explicit_statement_supersedes_old_rule_via_kernel(tmp_path):
    paths, user, store, adapter, kernel = _kernel(tmp_path)
    kernel.run_input("以后我的 SQL 必须使用 CTE。")   # required CTE
    r2 = kernel.run_input("以后我的 SQL 不允许使用 CTE。")  # forbidden CTE → supersedes
    assert r2.status == "learned"
    old = store.entity("R-SQL-001")
    assert old["status"] == "superseded"
    assert old["superseded_by"].startswith("R-SQL-")
    assert "explicit user statement" in old["superseded_reason"]
    assert old["confidence"] == 0.95  # history intact
