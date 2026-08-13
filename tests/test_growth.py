"""Phase 3A tests — Memory Growth Engine.

Deterministic PatternDetector, promotion policy, confidence composition,
sleep idempotency, evidence traceability, and the hard rule that
candidates never reach agent context.

All fixtures are synthetic (no real user data, no real agent).
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cogos.growth import (
    POLICY,
    PromotionPolicy,
    compute_confidence,
    decide_promotion,
    extract_features,
    run_sleep,
)
from cogos.kernel import Context, DomainRouter, FileMemory, Kernel, Result
from cogos.paths import Paths
from cogos.retrieve import build_context, retrieve
from cogos.store import Store
from cogos.user import UserLayer

TS0 = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _ws(tmp_path: Path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    return paths, user, store


def _episodic(
    i: int,
    *,
    features=None,
    verdict="PASS",
    domain="sql",
    refs=None,
    created: datetime = TS0,
):
    return {
        "id": f"mem-e{i:03d}",
        "type": "episodic",
        "domain": domain,
        "content": f"[{verdict}] task {i} → agent=stub status=success",
        "source": "execution",
        "derived_from_execution": f"ex-20260801-{i:06d}",
        "verdict": verdict,
        "refs": refs or [],
        "features": features or [],
        "created_at": _iso(created),
    }


def _write_episodics(user: UserLayer, rows: list[dict]) -> None:
    user.memory.mkdir(parents=True, exist_ok=True)
    with (user.memory / "episodic.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sleep(store: Store, user: UserLayer, now: datetime | None = None):
    store.reindex(Paths(root=user.root.parent))
    return run_sleep(user, store, now=now)


# ---------------------------------------------------------------------------
# Test 1–3: evidence → candidate → confidence → promotion
# ---------------------------------------------------------------------------


def test_one_evidence_creates_candidate_not_preference(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [_episodic(1, features=["sql:uses_cte"])])
    report = _sleep(store, user, now=TS0 + timedelta(days=1))
    cand_path = user.memory / "candidates.jsonl"
    assert cand_path.exists()
    cands = [json.loads(l) for l in cand_path.read_text(encoding="utf-8").splitlines()]
    assert len(cands) == 1
    assert cands[0]["type"] == "candidate"
    assert cands[0]["status"] == "candidate"
    assert not (user.memory / "preferences.jsonl").exists(), "one evidence must NOT promote"


def test_repeated_evidence_increases_confidence(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [_episodic(1, features=["sql:uses_cte"])])
    _sleep(store, user, now=TS0 + timedelta(days=1))
    c1 = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])

    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    _sleep(store, user, now=TS0 + timedelta(days=3))
    c2 = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert c2["id"] == c1["id"], "same pattern must update the same candidate"
    assert c2["evidence_count"] > c1["evidence_count"]
    assert c2["confidence"] > c1["confidence"]


def test_threshold_reached_promotes_to_preference(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    # promotion has a 24h cool-down: sleep well after the candidate's creation
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    assert report.memories_promoted, "3 verified evidences should promote"
    pid = report.memories_promoted[0]
    assert pid.startswith("P-")
    pref_path = user.memory / "preferences.jsonl"
    prefs = [json.loads(l) for l in pref_path.read_text(encoding="utf-8").splitlines()]
    assert any(p["id"] == pid and p["status"] == "confirmed" for p in prefs)


# ---------------------------------------------------------------------------
# Test 4–5: rule promotion is stricter
# ---------------------------------------------------------------------------


def test_rule_candidate_not_promoted_by_ordinary_evidence(tmp_path):
    paths, user, store = _ws(tmp_path)
    # sql:uses_select_star is a rule-type feature; 3 evidences with 1 verify pass
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_select_star"], verdict="PASS"),
        _episodic(2, features=["sql:uses_select_star"], verdict="AMBIGUOUS", created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_select_star"], verdict="AMBIGUOUS", created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    assert not report.memories_promoted, "rule needs 3 verify PASS — ordinary evidence must not promote"


def test_rule_promotes_after_three_verify_pass(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_select_star"], verdict="PASS"),
        _episodic(2, features=["sql:uses_select_star"], verdict="PASS", created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_select_star"], verdict="PASS", created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    assert report.memories_promoted
    rid = report.memories_promoted[0]
    assert rid.startswith("R-")
    rule = json.loads((user.root / "rules" / f"{rid}.json").read_text(encoding="utf-8"))
    assert "SELECT *" in rule["forbidden"], "rule must carry the deterministic forbidden pattern"


# ---------------------------------------------------------------------------
# Test 6–8: idempotency, evidence traceability, episodics preserved
# ---------------------------------------------------------------------------


def test_sleep_is_idempotent(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    r1 = _sleep(store, user, now=TS0 + timedelta(days=4))
    r2 = _sleep(store, user, now=TS0 + timedelta(days=4))
    r3 = _sleep(store, user, now=TS0 + timedelta(days=4))
    # idempotency = no DUPLICATE cognition: the promotion happens once,
    # later sleeps must not re-promote (or the store would accumulate
    # P-001, P-002, P-003 for the same pattern)
    assert len(r1.memories_promoted) == 1
    assert r2.memories_promoted == []
    assert r3.memories_promoted == []
    prefs = (user.memory / "preferences.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(prefs) == 1, "sleep must not duplicate promoted preferences"
    cands = (user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(cands) == 1


def test_evidence_traces_to_executions(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    pid = report.memories_promoted[0]
    pref = store.entity(pid)
    assert pref["evidence_count"] == 3
    assert "source_executions" in pref["payload"]
    assert len(pref["payload"]["source_executions"]) == 3
    # edges: preference derived_from each episodic
    rows = store._conn.execute("SELECT to_id FROM edges WHERE from_id=? AND rel='derived_from'", (pid,)).fetchall()
    assert len(rows) == 3


def test_episodics_survive_promotion(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    _sleep(store, user, now=TS0 + timedelta(days=4))
    epis = (user.memory / "episodic.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(epis) == 3, "promotion must never delete episodic history"
    store.reindex(Paths(root=tmp_path))
    hits = store.search("task", types=("memory",))
    assert any(h.subtype == "episodic" for h in hits)


# ---------------------------------------------------------------------------
# Test 9: supersede keeps the old version
# ---------------------------------------------------------------------------


def test_superseded_preference_still_exists(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    pid = report.memories_promoted[0]
    # simulate a newer preference superseding it (3B mechanism, data model only)
    store.upsert_entity(pid, "memory", subtype="preference", domain="sql",
                        content="updated", status="superseded")
    assert store.entity(pid) is not None, "superseded memory must not be deleted"
    assert store.entity(pid)["status"] == "superseded"
    # and it must no longer be retrieved
    assert not any(h.ent_id == pid for h in store.search("SQL", types=("memory",)))


# ---------------------------------------------------------------------------
# Test 10: candidates never enter agent context
# ---------------------------------------------------------------------------


def test_candidate_never_enters_agent_context(tmp_path):
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [_episodic(1, features=["sql:uses_cte"])])
    _sleep(store, user, now=TS0 + timedelta(days=1))
    cand_id = json.loads((user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0])["id"]

    rset = retrieve(store, "帮我写一个 SQL 查询", domain="sql")
    assert not any(h.ent_id == cand_id for h in rset.hits), "candidate must not be retrieved"
    block = build_context(rset, "帮我写一个 SQL 查询")
    assert cand_id not in block.text
    # store-level guarantee too
    assert not any(h.ent_id == cand_id for h in store.search("CTE", types=("memory",)))


def test_promoted_candidate_still_excluded_from_retrieval(tmp_path):
    """Regression: a promoted candidate's status flips to 'confirmed', but it
    must STILL never be retrieved — exclusion is subtype-level, not status-level."""
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_cte"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_cte"], created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    cand_id = report.memories_promoted and json.loads(
        (user.memory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )["id"]
    assert cand_id
    ent = store.entity(cand_id)
    assert ent["status"] == "confirmed"  # promoted
    hits = store.search("CTE", types=("memory",))
    assert not any(h.ent_id == cand_id for h in hits), "promoted candidate must stay out of retrieval"
    # its promoted preference IS retrievable
    assert any(h.ent_id.startswith("P-") for h in hits)


# ---------------------------------------------------------------------------
# Counter-examples: the detector must NOT learn from noise
# ---------------------------------------------------------------------------


def test_no_preference_from_mixed_behaviors(tmp_path):
    """CTE once, subquery once, JOIN once — no pattern, no preference."""
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_cte"]),
        _episodic(2, features=["sql:uses_subquery"], created=TS0 + timedelta(days=1)),
        _episodic(3, features=["sql:uses_join"], created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    assert not report.memories_promoted
    # each candidate has only 1 evidence — no promotion, no CTE preference
    assert not (user.memory / "preferences.jsonl").exists()


def test_single_anomaly_does_not_pollute_cognition(tmp_path):
    """One SELECT * anomaly among normal runs — must not yield a preference."""
    paths, user, store = _ws(tmp_path)
    _write_episodics(user, [
        _episodic(1, features=["sql:uses_select_star"], verdict="FAIL"),
        _episodic(2, features=[], created=TS0 + timedelta(days=1)),
        _episodic(3, features=[], created=TS0 + timedelta(days=2)),
    ])
    report = _sleep(store, user, now=TS0 + timedelta(days=4))
    assert not report.memories_promoted


# ---------------------------------------------------------------------------
# Confidence composition + policy unit tests
# ---------------------------------------------------------------------------


def test_confidence_is_evidence_derived():
    weak = compute_confidence(observations=2)
    strong = compute_confidence(observations=5, applied_verified=1)
    confirmed = compute_confidence(observations=5, applied_verified=1, user_confirmed=True)
    assert weak < strong <= confirmed
    assert 0.3 <= weak < 0.7
    assert strong >= 0.7
    assert confirmed >= 0.97


def test_policy_cool_down_holds_promotion():
    created = _iso(TS0)
    decision, reason = decide_promotion(
        target_type="preference", confidence=0.9, evidence_count=5,
        verify_pass_count=3, user_confirmed=False, created_at=created,
        now=TS0 + timedelta(hours=1),
    )
    assert decision == "hold"
    assert "cool-down" in reason


def test_extract_features_is_deterministic():
    out = "```sql\nWITH x AS (SELECT id FROM t)\nSELECT id, name FROM x JOIN u ON x.id=u.id\n```"
    feats = extract_features("sql", out)
    assert "sql:uses_cte" in feats
    assert "sql:uses_join" in feats
    assert "sql:uses_select_star" not in feats
    # explanation text mentioning SELECT * is not behavior
    out2 = "注意不要使用 SELECT *，以下是合规查询:\n```sql\nSELECT id FROM t\n```"
    assert "sql:uses_select_star" not in extract_features("sql", out2)


# ---------------------------------------------------------------------------
# Migration test: a Phase 2 (v1) database stays readable after v2 migration
# ---------------------------------------------------------------------------


def test_v1_database_migrates_and_stays_readable(tmp_path):
    db = tmp_path / "v1.db"
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
    INSERT INTO entities (id, type, subtype, domain, content, payload)
      VALUES ('R-OLD-001', 'memory', 'rule', 'sql', 'legacy rule', '{}');
    INSERT INTO mem_fts (ent_id, type, subtype, domain, text)
      VALUES ('R-OLD-001', 'memory', 'rule', 'sql', 'legacy rule');
    """)
    con.commit()
    con.close()

    store = Store(db)  # opens v1 db → migration runs
    try:
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(entities)")}
        assert "status" in cols and "confidence" in cols
        v = store._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        assert v and v["value"] == "2"
        ent = store.entity("R-OLD-001")
        assert ent is not None and ent["content"] == "legacy rule"
        hits = store.search("legacy", types=("memory",))
        assert any(h.ent_id == "R-OLD-001" for h in hits)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Golden Path regression guard (kernel-level, deterministic fake)
# ---------------------------------------------------------------------------


def test_golden_path_rule_still_learns_and_retrieves(tmp_path):
    """Phase 2 behavior must be intact after Phase 3A changes."""

    class FakeAdapter:
        agent_id = "fake"

        def execute(self, task, context: Context) -> Result:
            return Result(task_id=task.id, status="success", output="SELECT id FROM sales")

        def bootstrap_query(self, prompt):
            return None

    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    adapter = FakeAdapter()
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "m.jsonl"),
        router=DomainRouter([adapter]),
        adapters=[adapter],
        store=store,
        user=user,
        llm_fn=None,
        allow_semantic=False,
    )
    r1 = kernel.run_input("以后我的 SQL 不允许使用 SELECT *。")
    assert r1.status == "learned" and r1.memory_written[0].startswith("R-SQL-")
    r2 = kernel.run_input("帮我写一个查询销售数据的 SQL。")
    assert r2.verdict == "PASS" and "rules=1" in r2.retrieved_summary
    # Phase 3A addition: the episodic now carries deterministic features
    epis = json.loads((user.memory / "episodic.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert isinstance(epis.get("features"), list)


def test_temporary_statement_never_enters_permanent_store(tmp_path):
    """'今天' scoped statements → temporary entity, excluded from retrieval."""

    class FakeAdapter:
        agent_id = "fake"

        def execute(self, task, context):
            return Result(task_id=task.id, status="success", output="ok")

        def bootstrap_query(self, prompt):
            return None

    paths = Paths(root=tmp_path)
    paths.ensure()
    user = UserLayer(root=tmp_path / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    kernel = Kernel(
        memory=FileMemory(store_path=paths.cache / "m.jsonl"),
        router=DomainRouter([FakeAdapter()]),
        adapters=[FakeAdapter()],
        store=store, user=user, llm_fn=None, allow_semantic=False,
    )
    r = kernel.run_input("今天我的 SQL 可以用 SELECT *。")
    assert r.status == "learned"
    assert r.memory_written[0].startswith("tmp-")
    assert (user.memory / "temporary.jsonl").exists()
    assert not list((user.root / "rules").glob("R-*.json")), "temporary must not create permanent rules"
    assert not any(h.ent_id.startswith("tmp-") for h in store.search("SELECT", types=("memory",)))
