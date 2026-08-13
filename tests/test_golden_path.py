"""Golden Path integration test — the FULL cognitive loop, no LLM, no real
user data.

Scenario (docs/cognitive-architecture.md §6):

1. `cogos run "以后我的 SQL 不允许使用 SELECT *。"` → rule remembered
2. `cogos run "帮我写一个查询销售数据的 SQL。"` → rule retrieved, injected
   into the agent context, output verified against it, trace + episodic
   memory written.
3. Delete the SQLite index → `reindex` → the rule is still retrievable.

The agent here is a deterministic fake adapter — integration tests must not
depend on a real Hermes CLI. The REAL Hermes execution is proven separately
via the actual ``cogos run`` CLI (see docs for the acceptance evidence).
"""

import json
from pathlib import Path

from cogos.kernel import Context, Kernel, DomainRouter, FileMemory, Result
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer


class FakeAdapter:
    """Deterministic agent: echoes what it was given, output configurable.

    Records the assembled context block so tests can PROVE the retrieved
    rule was actually injected (Test 3 / 4 of the acceptance criteria)."""

    agent_id = "fake"

    def __init__(self, output: str = "SELECT id FROM sales"):
        self.output = output
        self.last_context_block = ""

    def execute(self, task, context: Context) -> Result:
        self.last_context_block = context.context_block
        return Result(task_id=task.id, status="success", output=self.output)

    def bootstrap_query(self, prompt):
        return None


def _build_kernel(tmp_path: Path, output: str = "SELECT id FROM sales"):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    adapter = FakeAdapter(output=output)
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "memory.jsonl"),
        router=DomainRouter([adapter]),
        adapters=[adapter],
        store=store,
        user=user,
        llm_fn=None,  # deterministic keyword/pattern path
        allow_semantic=False,
    )
    return paths, user, store, adapter, kernel


def _rule_file(user: UserLayer) -> Path:
    return next((user.root / "rules").glob("R-*.json"))


# ---------------------------------------------------------------------------
# The Golden Path
# ---------------------------------------------------------------------------


def test_golden_path_full_loop(tmp_path):
    paths, user, store, adapter, kernel = _build_kernel(tmp_path)

    # ---- Test 1: rule statement is recognized and remembered -------------
    r1 = kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    assert r1.status == "learned"
    assert r1.intent_type == "rule"
    assert len(r1.memory_written) == 1
    rule_id = r1.memory_written[0]
    assert rule_id.startswith("R-SQL-")

    rule_path = _rule_file(user)
    assert rule_path.exists()
    rule = json.loads(rule_path.read_text(encoding="utf-8"))
    assert "SELECT *" in rule["forbidden"]

    # ---- Test 2 + 3: retrieval finds the rule AND injects it -------------
    r2 = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert r2.intent_type == "task"
    assert rule_id in adapter.last_context_block, "retrieved rule must be injected into agent context"
    assert "## 相关规则" in adapter.last_context_block
    assert r2.retrieved_summary and "rules=1" in r2.retrieved_summary

    # ---- Test 4 + 5: trace exists, verdict PASS --------------------------
    assert r2.verdict == "PASS"
    assert r2.status == "success"
    trace_files = list((user.traces).glob("*.jsonl"))
    assert trace_files, "trace file must exist"
    trace_text = "\n".join(p.read_text(encoding="utf-8") for p in trace_files)
    assert "memory_retrieved" in trace_text
    assert rule_id in trace_text
    assert "verification_completed" in trace_text

    # ---- Test 6: episodic learning written -------------------------------
    episodic = user.memory / "episodic.jsonl"
    assert episodic.exists()
    mem_line = json.loads(episodic.read_text(encoding="utf-8").splitlines()[-1])
    assert mem_line["type"] == "episodic"
    assert mem_line["derived_from_execution"] == r2.execution_id

    # ---- Test 7 / G: db deleted → reindex → still remembers --------------
    store.close()
    db_path = paths.cache / "cognitive.db"
    db_path.unlink()
    store2 = Store(db_path)
    try:
        store2.reindex(paths)
        hits = store2.search("写一个 SQL 查询", types=("memory",))
        assert any(h.ent_id == rule_id for h in hits), "rule must survive reindex"
    finally:
        store2.close()


def test_golden_path_verification_fails_when_agent_violates(tmp_path):
    paths, user, store, adapter, kernel = _build_kernel(tmp_path, output="SELECT * FROM sales")
    kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    r2 = kernel.run_input("帮我写一个 SQL。")
    assert r2.verdict == "FAIL", "agent output contains SELECT * — verification must catch it"
    assert r2.status == "failed"


def test_golden_path_rule_only_run_produces_trace(tmp_path):
    paths, user, store, adapter, kernel = _build_kernel(tmp_path)
    r = kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    assert r.execution_id.startswith("ex-")
    trace_files = list((user.traces).glob("*.jsonl"))
    assert trace_files
    text = "\n".join(p.read_text(encoding="utf-8") for p in trace_files)
    assert "task_classified" in text
    assert "memory_written" in text
    assert "execution_completed" in text


def test_execution_ids_are_unique_and_sequential(tmp_path):
    paths, user, store, adapter, kernel = _build_kernel(tmp_path)
    r1 = kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    r2 = kernel.run_input("帮我写一个 SQL。")
    assert r1.execution_id != r2.execution_id
    assert r2.execution_id.endswith("000002") or int(r2.execution_id.split("-")[-1]) == 2


def test_dashboard_snapshot_reflects_real_runs(tmp_path):
    paths, user, store, adapter, kernel = _build_kernel(tmp_path)
    kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    kernel.run_input("帮我写一个 SQL。")
    from cogos.dashboard import _load_store_snapshot

    snap = _load_store_snapshot(paths)
    assert len(snap["executions"]) == 2
    assert any(m["id"].startswith("R-SQL-") for m in snap["region_memories"].get("hippocampus", []))
