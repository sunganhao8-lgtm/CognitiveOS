"""Phase 3E tests — MemoryService: list/show/why/confirm/reject/forget/modify,
canonical persistence, user_corrected traces, ViewModel cards.

All actions go through the service; canonical `user/**` files are always
kept in sync so corrections survive `delete db → reindex`.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.growth import run_sleep
from cogos.memory_service import MemoryService
from cogos.paths import Paths
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


def _ws(tmp_path: Path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    return paths, user, store


def _episodic(i, *, features=None, verdict="PASS", created=TS0):
    return {
        "id": f"mem-e{i:03d}", "type": "episodic", "domain": "sql",
        "content": f"[{verdict}] task {i}", "source": "execution",
        "derived_from_execution": f"ex-20260801-{i:06d}",
        "verdict": verdict, "refs": [], "features": features or [],
        "created_at": created.isoformat(timespec="seconds"),
    }


def _make_candidate(tmp_path, *, n_evidences=1, feature="sql:uses_cte") -> str:
    """Seed episodic evidence + sleep → returns the candidate id."""
    paths, user, store = _ws(tmp_path)
    user.memory.mkdir(parents=True, exist_ok=True)
    rows = [_episodic(i, features=[feature], created=TS0 + timedelta(days=i)) for i in range(1, n_evidences + 1)]
    (user.memory / "episodic.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    store.reindex(paths)
    run_sleep(user, store, now=TS0 + timedelta(days=10))
    cand = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    store.close()
    return cand["id"]


def _confirmed_pref(tmp_path: Path, pid="P-SQL-001", content="SQL 偏好使用 CTE") -> Paths:
    paths, user, store = _ws(tmp_path)
    store.upsert_entity(
        pid, "memory", subtype="preference", domain="sql", content=content,
        payload={"source": "user_statement", "source_executions": ["ex-1", "ex-2", "ex-3"]},
        status="confirmed", confidence=0.91, evidence_count=3,
        verify_pass_count=3, user_confirmed=False, version=1,
        created_at=TS0.isoformat(timespec="seconds"),
    )
    store.add_fts(pid, "memory", "preference", "sql", content)
    # canonical mirror
    user.memory.mkdir(parents=True, exist_ok=True)
    (user.memory / "preferences.jsonl").write_text(
        json.dumps({
            "id": pid, "type": "preference", "domain": "sql", "content": content,
            "source": "user_statement", "status": "confirmed", "confidence": 0.91,
            "evidence_count": 3, "verify_pass_count": 3,
            "source_executions": ["ex-1", "ex-2", "ex-3"],
            "user_confirmed": False, "version": 1,
            "created_at": TS0.isoformat(timespec="seconds"),
        }, ensure_ascii=False) + "\n",
        encoding="utf-8")
    store.close()
    return paths


# ---------------------------------------------------------------------------
# list / show / card
# ---------------------------------------------------------------------------


def test_list_lists_cognitions(tmp_path):
    paths, user, store = _ws(tmp_path)
    store.upsert_entity("P-X", "memory", subtype="preference", domain="sql",
                        content="x", payload={}, status="confirmed", version=1)
    svc = MemoryService(paths)
    try:
        rows = svc.list()
        assert any(r["id"] == "P-X" for r in rows)
    finally:
        svc.close()


def test_card_view_model(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        card = svc.card("P-SQL-001")
        assert card["id"] == "P-SQL-001"
        assert card["status"] == "confirmed"
        assert "modify" in card["actions"] and "forget" in card["actions"]
        assert card["confidence"] == 0.91 and card["evidence_count"] == 3
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


def test_confirm_candidate_promotes_and_retains_evidence(tmp_path):
    cand_id = _make_candidate(tmp_path, n_evidences=3)
    paths = Paths(root=tmp_path)
    svc = MemoryService(paths)
    try:
        out = svc.confirm(cand_id)
        new_id = out["confirmed"]
        ent = svc.store.entity(new_id)
        assert ent["status"] == "confirmed"
        assert ent["user_confirmed"] == 1
        assert ent["evidence_count"] == 3, "evidence must be retained"
        assert (ent["payload"] or {}).get("source_executions")
        # the candidate itself stays subtype=candidate (never retrieved, 3A rule)
        cand = svc.store.entity(cand_id)
        assert cand["status"] == "confirmed"
        assert cand["subtype"] == "candidate"
        assert not any(h.ent_id == cand_id for h in svc.store.search("CTE", types=("memory",)))
        # new cognition IS retrievable
        assert any(h.ent_id == new_id for h in svc.store.search("CTE", types=("memory",)))
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


def test_reject_candidate_keeps_history_and_blocks_retrieval(tmp_path):
    cand_id = _make_candidate(tmp_path, n_evidences=1)
    paths = Paths(root=tmp_path)
    svc = MemoryService(paths)
    try:
        svc.reject(cand_id, reason="wrong inference")
        ent = svc.store.entity(cand_id)
        assert ent["status"] == "rejected"
        assert not any(h.ent_id == cand_id for h in svc.store.search("CTE", types=("memory",)))
        # rejection fingerprint recorded
        rej = json.loads((svc.user.memory / "rejections.jsonl").read_text(encoding="utf-8").splitlines()[0])
        assert rej["memory_id"] == cand_id and rej["fingerprint"] == "sql:uses_cte"
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------


def test_forget_confirmed_memory_suppresses_and_keeps_history(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        svc.forget("P-SQL-001", reason="no longer relevant")
        ent = svc.store.entity("P-SQL-001")
        assert ent["status"] == "suppressed"
        # canonical mirror also suppressed
        from cogos.growth import _read_jsonl_lines

        rows = _read_jsonl_lines(svc.user.memory / "preferences.jsonl")
        assert rows[0]["status"] == "suppressed"
        # not retrieved anymore
        assert not any(h.ent_id == "P-SQL-001" for h in svc.store.search("CTE", types=("memory",)))
        # but still visible via why
        why = svc.why("P-SQL-001")
        assert why["status"] == "suppressed"
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# modify (version supersede chain)
# ---------------------------------------------------------------------------


def test_modify_creates_new_version_and_supersedes_old(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        out = svc.modify("P-SQL-001", "复杂 SQL 使用 CTE，简单 SQL 优先子查询")
        new_id = out["new"]
        old = svc.store.entity("P-SQL-001")
        assert old["status"] == "superseded"
        assert old["superseded_by"] == new_id
        assert old["confidence"] == 0.91, "historical confidence must be untouched"
        new = svc.store.entity(new_id)
        assert new["status"] == "confirmed"
        assert new["version"] == 2
        assert new["user_confirmed"] == 1
        assert new["evidence_count"] == 3, "evidence carried to the new version"
        chain = svc.store.version_chain(new_id)
        assert [c["id"] for c in chain] == ["P-SQL-001", new_id]
        # retrieval sees only the new version
        hits = [h.ent_id for h in svc.store.search("CTE", types=("memory",))]
        assert new_id in hits and "P-SQL-001" not in hits
        # canonical sync: old superseded, new present
        rows = [json.loads(l) for l in (svc.user.memory / "preferences.jsonl").read_text(encoding="utf-8").splitlines()]
        old_row = next(r for r in rows if r["id"] == "P-SQL-001")
        assert old_row["status"] == "superseded"
        assert any(r["id"] == new_id and r["status"] == "confirmed" for r in rows)
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# why (evidence-based explanation, NO chain-of-thought)
# ---------------------------------------------------------------------------


def test_why_explains_with_evidence_and_corrections(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        svc.modify("P-SQL-001", "复杂 SQL 使用 CTE，简单 SQL 优先子查询")
        why = svc.why("P-SQL-001")
        assert why["evidence_count"] == 3
        assert why["verify_pass_count"] == 3
        assert "ex-1" in why["source_executions"]
        assert why["superseded_history"], "supersede history must be visible"
        assert any("user_corrected" and c.get("action") == "modify" for c in why["user_corrections"])
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------


def test_correction_produces_user_corrected_trace(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        svc.forget("P-SQL-001")
        svc.close()
        svc = MemoryService(paths)
        rows = svc.store._conn.execute(
            "SELECT step, detail FROM trace_events WHERE step='user_corrected' ORDER BY id"
        ).fetchall()
        assert rows, "user_corrected trace must exist"
        detail = json.loads(rows[-1]["detail"])
        assert detail["action"] == "forget"
        assert detail["old_status"] == "confirmed" and detail["new_status"] == "suppressed"
        assert detail["memory"] == "P-SQL-001"
    finally:
        svc.close()


# ---------------------------------------------------------------------------
# canonical persistence across reindex (§24/§25)
# ---------------------------------------------------------------------------


def test_corrections_survive_delete_and_reindex(tmp_path):
    paths = _confirmed_pref(tmp_path)
    svc = MemoryService(paths)
    try:
        svc.forget("P-SQL-001")
    finally:
        svc.close()

    db = paths.cache / "cognitive.db"
    db.unlink()
    store2 = Store(db)
    try:
        store2.reindex(paths)
        ent = store2.entity("P-SQL-001")
        assert ent["status"] == "suppressed", "correction must survive reindex (canonical was written)"
        assert not any(h.ent_id == "P-SQL-001" for h in store2.search("CTE", types=("memory",)))
    finally:
        store2.close()


def test_confirm_survives_reindex(tmp_path):
    cand_id = _make_candidate(tmp_path, n_evidences=3)
    paths = Paths(root=tmp_path)
    svc = MemoryService(paths)
    try:
        new_id = svc.confirm(cand_id)["confirmed"]
    finally:
        svc.close()
    (paths.cache / "cognitive.db").unlink()
    store2 = Store(paths.cache / "cognitive.db")
    try:
        store2.reindex(paths)
        assert store2.entity(new_id)["status"] == "confirmed"
    finally:
        store2.close()
