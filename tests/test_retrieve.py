"""Unit tests for retrieval and the bounded context builder."""

from cogos.paths import Paths
from cogos.retrieve import build_context, retrieve, RetrievedSet
from cogos.store import SearchHit, Store
from cogos.user import UserLayer
import json


def _hit(ent_id, type_="memory", subtype="rule", content="no SELECT *"):
    return SearchHit(ent_id=ent_id, type=type_, subtype=subtype, domain="sql", score=2.0, content=content)


def test_build_context_contains_sections_and_task():
    rset = RetrievedSet(hits=[_hit("R-SQL-001")])
    block = build_context(rset, "帮我写一个 SQL")
    assert "## 相关规则" in block.text
    assert "R-SQL-001" in block.text
    assert "## 当前任务" in block.text
    assert "帮我写一个 SQL" in block.text
    assert block.sections.get("rules") == 1


def test_build_context_respects_hard_budget():
    big = [_hit(f"R-{i:03d}", content="x" * 900) for i in range(20)]
    block = build_context(RetrievedSet(hits=big), "task", budget=4000)
    assert block.chars <= 4000
    assert block.truncated


def test_retrieve_caps_per_type():
    hits = []
    for i in range(10):
        hits.append(SearchHit(ent_id=f"rule-{i}", type="memory", subtype="rule", domain="sql", score=1.0, content="rule"))
        hits.append(SearchHit(ent_id=f"skill-{i}", type="skill", subtype="", domain="sql", score=1.0, content="skill"))

    class _Store:
        def search(self, query, *, types=(), limit=12):
            return hits[:limit]

    rset = retrieve(_Store(), "sql query")
    rules = [h for h in rset.hits if h.subtype == "rule"]
    skills = [h for h in rset.hits if h.type == "skill"]
    assert len(rules) <= 2  # PER_TYPE_LIMITS["rule"]
    assert len(skills) <= 2  # PER_TYPE_LIMITS["skill"]


def test_refs_and_summary_shape():
    rset = RetrievedSet(hits=[_hit("R-SQL-001"), _hit("mem-e1", subtype="episodic", content="past run")])
    refs = rset.refs()
    assert {"type": "memory", "subtype": "rule", "id": "R-SQL-001", "score": 2.0} in refs
    assert "rules=1" in rset.summary()
    assert "memories=1" in rset.summary()


def test_empty_retrieval_builds_task_only_context():
    block = build_context(RetrievedSet(hits=[]), "just a task")
    assert "## 当前任务" in block.text
    assert "相关" not in block.text.replace("当前任务", "")
    assert block.sections == {}
