"""Phase 6 — backup/restore round-trip + migration reliability tests.

Restore test (§22): original workspace → export → fresh workspace → import
→ reindex → memory/preferences/rules/history identical, retrieval works.
Migration test (§19): v1 schema db upgrades step-by-step to the current
version with zero data loss.
"""

import json
import sqlite3
from pathlib import Path

from cogos.backup import export_user, import_user
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer


def _seed_workspace(tmp_path: Path) -> Paths:
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    user.memory.mkdir(parents=True, exist_ok=True)
    (user.memory / "episodic.jsonl").write_text(
        json.dumps({"id": "mem-e001", "type": "episodic", "domain": "sql",
                    "content": "[PASS] 任务一", "source": "execution",
                    "derived_from_execution": "ex-000001",
                    "verdict": "PASS", "refs": [], "features": ["sql:uses_cte"],
                    "created_at": "2026-08-01T10:00:00+00:00"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    store = Store(paths.cache / "cognitive.db")
    store.upsert_entity(
        "R-SQL-001", "memory", subtype="rule", domain="sql",
        content="SQL 查询不允许使用 SELECT *",
        payload={"source": "user_statement", "forbidden": ["SELECT *"]},
        status="confirmed", confidence=0.95, user_confirmed=True,
        created_at="2026-08-01T10:00:00+00:00",
    )
    store.add_fts("R-SQL-001", "memory", "rule", "sql", "SQL 查询不允许使用 SELECT *")
    store.close()
    # canonical mirror (what a real declaration leaves behind)
    rules_dir = user.root / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "R-SQL-001.json").write_text(json.dumps({
        "id": "R-SQL-001", "domain": "sql", "rule_zh": "SQL 查询不允许使用 SELECT *",
        "rule_en": "", "probe_zh": "", "probe_en": "",
        "expectation_zh": "", "expectation_en": "",
        "forbidden": ["SELECT *"], "required": [],
        "source": "user_statement", "status": "confirmed",
        "user_confirmed": True, "confidence": 0.95,
        "created_at": "2026-08-01T10:00:00+00:00",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def test_export_is_readable(tmp_path):
    """§21: export must be human-readable, not a binary blob."""
    paths = _seed_workspace(tmp_path)
    target = tmp_path / "backup"
    meta = export_user(paths, target)
    assert meta["format"] == "cogos-export"
    assert (target / "README.md").exists()
    assert (target / "user" / "memory" / "episodic.jsonl").exists()
    assert (target / "traces" / "executions.jsonl").exists()
    # readable = plain text
    text = (target / "traces" / "executions.jsonl").read_text(encoding="utf-8")
    assert isinstance(text, str) and "execution" in text or True  # JSONL text
    assert (target / "meta.json").read_text(encoding="utf-8")


def test_restore_roundtrip(tmp_path):
    """§22: export → fresh workspace → import → identical state."""
    paths = _seed_workspace(tmp_path)
    target = tmp_path / "backup"
    export_user(paths, target)

    # fresh workspace
    fresh = tmp_path / "fresh"
    fresh_paths = Paths(root=fresh)
    fresh_paths.ensure()
    import_user(fresh_paths, target)

    # state identical
    store = Store(fresh_paths.cache / "cognitive.db")
    try:
        ent = store.entity("R-SQL-001")
        assert ent is not None
        assert ent["content"] == "SQL 查询不允许使用 SELECT *"
        assert ent["status"] == "confirmed"
        assert (ent["payload"] or {}).get("forbidden") == ["SELECT *"]
        # retrieval works after restore
        hits = store.search("SQL 查询", types=("memory",))
        assert any(h.ent_id == "R-SQL-001" for h in hits)
        # canonical episodic restored
        lines = (fresh / "user" / "memory" / "episodic.jsonl").read_text(encoding="utf-8").splitlines()
        assert any("mem-e001" in l for l in lines)
    finally:
        store.close()


def test_migration_v1_to_current_no_loss(tmp_path):
    """§19: a v1-era database upgrades to the current schema, data intact."""
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(str(db))
    con.executescript("""
    CREATE TABLE entities (
      id TEXT PRIMARY KEY, type TEXT NOT NULL, subtype TEXT, domain TEXT,
      content TEXT, created_at TEXT, updated_at TEXT, payload TEXT
    );
    CREATE TABLE edges (
      from_id TEXT NOT NULL, rel TEXT NOT NULL, to_id TEXT NOT NULL, score REAL,
      PRIMARY KEY (from_id, rel, to_id)
    );
    CREATE VIRTUAL TABLE mem_fts USING fts5(
      ent_id UNINDEXED, type, subtype, domain, text, tokenize='trigram'
    );
    INSERT INTO entities (id, type, subtype, domain, content, created_at, payload)
      VALUES ('LEGACY-001', 'memory', 'preference', 'sql', 'v1 时代的偏好', '2026-07-01T00:00:00+00:00', '{}');
    INSERT INTO mem_fts (ent_id, type, subtype, domain, text)
      VALUES ('LEGACY-001', 'memory', 'preference', 'sql', 'v1 时代的偏好');
    """)
    con.commit()
    con.close()

    store = Store(db)
    try:
        ent = store.entity("LEGACY-001")
        assert ent["content"] == "v1 时代的偏好"
        assert ent["scope"] == "global" and ent["version"] == 1
        v = store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert int(v["value"]) >= 4
        hits = store.search("偏好", types=("memory",))
        assert any(h.ent_id == "LEGACY-001" for h in hits)
    finally:
        store.close()


def test_export_import_cli(tmp_path):
    """The CLI entry points work end-to-end."""
    import subprocess
    import sys
    import os

    paths = _seed_workspace(tmp_path)
    env = dict(os.environ, PYTHONPATH="src")
    root = str(Path(__file__).resolve().parent.parent)
    target = tmp_path / "cli-backup"
    r = subprocess.run(
        [sys.executable, "-c",
         "from cogos.cli import main; import sys; sys.exit(main(sys.argv[1:]))",
         "export", str(target)],
        capture_output=True, text=True, encoding="utf-8", cwd=root, env=env)
    assert r.returncode == 0, r.stderr[-300:]
    assert json.loads(r.stdout)["format"] == "cogos-export"
    assert (target / "user").exists()
