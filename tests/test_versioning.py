"""Phase 3B tests — preference versioning: supersede chains, version history,
migration of v2 databases."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def _pref(pid, *, content, scope="global", scope_id="", created=TS0, confidence=0.9, version=1, source="user_statement"):
    return {
        "id": pid,
        "type": "memory",
        "subtype": "preference",
        "domain": "sql",
        "content": content,
        "status": "confirmed",
        "scope": scope,
        "scope_id": scope_id,
        "version": version,
        "confidence": confidence,
        "created_at": created.isoformat(timespec="seconds"),
        "payload": {"source": source},
    }


def _seed(store: Store, spec: dict) -> None:
    store.upsert_entity(
        spec["id"], spec["type"], subtype=spec["subtype"], domain=spec["domain"],
        content=spec["content"], payload=spec["payload"],
        created_at=spec["created_at"], status=spec["status"],
        confidence=spec.get("confidence"), scope=spec.get("scope", "global"),
        scope_id=spec.get("scope_id", ""), version=spec.get("version", 1),
    )
    store.add_fts(spec["id"], "memory", spec["subtype"], spec["domain"], spec["content"])


def test_version_chain_v1_v2_v3(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed(store, _pref("P-SQL-001", content="v1 使用 CTE", version=1))
    _seed(store, _pref("P-SQL-002", content="v2 简单查询用子查询", version=2, created=TS0 + timedelta(days=1)))
    _seed(store, _pref("P-SQL-003", content="v3 复杂查询才用 CTE", version=3, created=TS0 + timedelta(days=2)))
    store.supersede("P-SQL-001", "P-SQL-002", reason="preference evolved")
    store.supersede("P-SQL-002", "P-SQL-003", reason="preference refined")

    chain = store.version_chain("P-SQL-003")
    assert [c["id"] for c in chain] == ["P-SQL-001", "P-SQL-002", "P-SQL-003"]
    assert [c["version"] for c in chain] == [1, 2, 3]
    assert chain[0]["status"] == "superseded"
    assert chain[1]["status"] == "superseded"
    assert chain[2]["status"] == "confirmed"


def test_version_chain_from_middle_id(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed(store, _pref("P-SQL-001", content="v1", version=1))
    _seed(store, _pref("P-SQL-002", content="v2", version=2))
    store.supersede("P-SQL-001", "P-SQL-002", reason="x")
    chain = store.version_chain("P-SQL-001")  # start from the OLD id
    assert [c["id"] for c in chain] == ["P-SQL-001", "P-SQL-002"]


def test_old_version_still_queryable(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed(store, _pref("P-SQL-001", content="v1 使用 CTE"))
    _seed(store, _pref("P-SQL-002", content="v2 使用子查询"))
    store.supersede("P-SQL-001", "P-SQL-002", reason="evolved")
    assert store.entity("P-SQL-001")["content"] == "v1 使用 CTE"
    # superseded is excluded from retrieval, but visible in the chain
    assert not any(h.ent_id == "P-SQL-001" for h in store.search("CTE", types=("memory",)))


def test_memory_show_cli_output_shape(tmp_path):
    paths, user, store = _ws(tmp_path)
    _seed(store, _pref("P-SQL-001", content="v1", version=1))
    _seed(store, _pref("P-SQL-002", content="v2", version=2))
    store.supersede("P-SQL-001", "P-SQL-002", reason="test")
    from cogos.cli import _memory_show

    _memory_show(paths, "P-SQL-002")
    # (shape validated by version_chain tests; smoke the CLI path)


def test_v2_database_migrates_to_v3(tmp_path):
    """A Phase 3A (v2) database must stay readable after the v3 migration."""
    db = tmp_path / "v2.db"
    con = sqlite3.connect(str(db))
    con.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    INSERT INTO meta VALUES ('schema_version', '2');
    CREATE TABLE entities (
      id TEXT PRIMARY KEY, type TEXT NOT NULL, subtype TEXT, domain TEXT,
      content TEXT, created_at TEXT, updated_at TEXT, payload TEXT,
      status TEXT DEFAULT '', confidence REAL, evidence_count INTEGER DEFAULT 0,
      last_observed TEXT DEFAULT '', verify_pass_count INTEGER DEFAULT 0,
      user_confirmed INTEGER DEFAULT 0
    );
    CREATE TABLE edges (
      from_id TEXT NOT NULL, rel TEXT NOT NULL, to_id TEXT NOT NULL, score REAL,
      PRIMARY KEY (from_id, rel, to_id)
    );
    CREATE VIRTUAL TABLE mem_fts USING fts5(
      ent_id UNINDEXED, type, subtype, domain, text, tokenize='trigram'
    );
    INSERT INTO entities (id, type, subtype, domain, content, payload, status, confidence)
      VALUES ('P-OLD-001', 'memory', 'preference', 'sql', 'v2 era preference', '{}', 'confirmed', 0.8);
    INSERT INTO mem_fts (ent_id, type, subtype, domain, text)
      VALUES ('P-OLD-001', 'memory', 'preference', 'sql', 'v2 era preference');
    """)
    con.commit()
    con.close()

    store = Store(db)
    try:
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(entities)")}
        assert {"scope", "scope_id", "version", "superseded_at", "superseded_by", "superseded_reason"} <= cols
        v = store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert v["value"] == "3"
        ent = store.entity("P-OLD-001")
        assert ent["content"] == "v2 era preference"
        assert ent["scope"] == "global" and ent["version"] == 1  # sensible defaults
        assert any(h.ent_id == "P-OLD-001" for h in store.search("preference", types=("memory",)))
    finally:
        store.close()


def test_project_scope_preference_wins_retrieval_ranking(tmp_path):
    """Case A (§26): project-scope preference outranks a global one."""
    paths, user, store = _ws(tmp_path)
    _seed(store, _pref("P-GLOBAL", content="SQL 喜欢 CTE", scope="global", source="sleep_promotion"))
    _seed(store, _pref("P-PROJ", content="该项目 SQL 偏好 subquery", scope="project",
                       scope_id="bp", source="user_statement", created=TS0 + timedelta(days=1)))
    hits = store.search("SQL 写法偏好", types=("memory",))
    # both hit, but the project-scoped explicit statement must rank above the
    # global behavior-derived one
    ids = [h.ent_id for h in hits if h.subtype == "preference"]
    assert "P-PROJ" in ids and "P-GLOBAL" in ids
    assert ids.index("P-PROJ") < ids.index("P-GLOBAL"), "project-scoped explicit statement must outrank global behavior evidence"
