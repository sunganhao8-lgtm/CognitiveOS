"""Unit tests for the Cognitive Store: indexing, search, rebuildability."""

import json

from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer


def _make_workspace(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    return paths, user


def _write_rule(user, rid="R-SQL-001", rule_zh="SQL 不允许使用 SELECT *"):
    (user.root / "rules").mkdir(parents=True, exist_ok=True)
    rec = {
        "id": rid,
        "domain": "sql",
        "rule_zh": rule_zh,
        "rule_en": "no SELECT * in SQL",
        "forbidden": ["SELECT *"],
        "required": [],
    }
    (user.root / "rules" / f"{rid}.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8"
    )
    return rec


def test_reindex_indexes_rules_and_search_finds_them(tmp_path):
    paths, user = _make_workspace(tmp_path)
    _write_rule(user)
    store = Store(paths.cache / "cognitive.db")
    try:
        report = store.reindex(paths)
        assert report.entities >= 2  # user + rule
        hits = store.search("写 SQL 查询", types=("memory",))
        ids = [h.ent_id for h in hits]
        assert "R-SQL-001" in ids
        hit = next(h for h in hits if h.ent_id == "R-SQL-001")
        assert hit.subtype == "rule"
        assert hit.domain == "sql"
    finally:
        store.close()


def test_store_survives_delete_and_reindex(tmp_path):
    paths, user = _make_workspace(tmp_path)
    _write_rule(user)
    db = paths.cache / "cognitive.db"
    store = Store(db)
    store.reindex(paths)
    store.close()

    db.unlink()  # simulate losing the index
    assert not db.exists()

    store = Store(db)
    try:
        store.reindex(paths)
        hits = store.search("SELECT", types=("memory",))
        assert any(h.ent_id == "R-SQL-001" for h in hits)
    finally:
        store.close()


def test_reindex_indexes_skills(tmp_path):
    paths, user = _make_workspace(tmp_path)
    skill_dir = paths.sources / "hermes" / "skills" / "oracle_optimizer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: oracle_optimizer\ndescription: Oracle SQL performance tuning\n---\n",
        encoding="utf-8",
    )
    store = Store(paths.cache / "cognitive.db")
    try:
        report = store.reindex(paths)
        assert report.skills == 1
        hits = store.search("oracle tuning", types=("skill",))
        assert any(h.ent_id == "skill-hermes:oracle_optimizer" for h in hits)
    finally:
        store.close()


def test_memories_for_regions_maps_subtypes(tmp_path):
    paths, user = _make_workspace(tmp_path)
    _write_rule(user)
    (user.memory).mkdir(parents=True, exist_ok=True)
    (user.memory / "episodic.jsonl").write_text(
        json.dumps(
            {
                "id": "mem-e1",
                "type": "episodic",
                "domain": "sql",
                "content": "wrote a query",
                "created_at": "2026-08-13T00:00:00+00:00",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    store = Store(paths.cache / "cognitive.db")
    try:
        store.reindex(paths)
        regions = store.memories_for_regions()
        assert any(m["id"] == "R-SQL-001" for m in regions.get("hippocampus", []))
        assert any(m["id"] == "mem-e1" for m in regions.get("reflection", []))
    finally:
        store.close()


def test_recent_executions_and_events(tmp_path):
    paths, user = _make_workspace(tmp_path)
    store = Store(paths.cache / "cognitive.db")
    try:
        store.record_execution(
            {
                "execution_id": "ex-20260813-000001",
                "task": "demo",
                "intent_type": "task",
                "agent_id": "stub",
                "status": "success",
                "verdict": "PASS",
                "context_chars": 100,
                "started_at": "2026-08-13T01:00:00+00:00",
                "finished_at": "2026-08-13T01:00:05+00:00",
                "payload": "{}",
            }
        )
        store.record_event("ex-20260813-000001", "memory_retrieved", "rules=1", [], "2026-08-13T01:00:00+00:00")
        runs = store.recent_executions(limit=5)
        assert len(runs) == 1
        assert runs[0]["events"][0]["step"] == "memory_retrieved"
    finally:
        store.close()
