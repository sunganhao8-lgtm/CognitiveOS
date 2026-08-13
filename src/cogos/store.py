"""Cognitive Store — SQLite index / projection over canonical user/ data.

Layering (see docs/cognitive-architecture.md §4):

    Canonical: user/** (md + jsonl + rules) + knowledge/sources/ (raw snapshots)
    Index:     .cogos/cognitive.db  (this module — disposable, rebuildable)
    Projection: index.html          (dashboard reads the index)

The database is NEVER a fact source. ``cogos reindex`` rebuilds it entirely
from canonical files; deleting the .db loses nothing but query convenience.

Schema: entities (typed nodes) + edges (typed relations) + FTS5 (retrieval)
+ executions / trace_events / verifications (projection of user/traces/).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import Paths
from .user import UserLayer

SCHEMA_VERSION = 2
"""Schema version recorded in the ``meta`` table. v2 (Phase 3) adds growth
fields (status/confidence/evidence_count/last_observed/verify_pass_count/
user_confirmed) to ``entities`` — applied to v1 databases via ALTER TABLE."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS entities (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL,
  subtype    TEXT,
  domain     TEXT,
  content    TEXT,
  created_at TEXT,
  updated_at TEXT,
  payload    TEXT,
  status             TEXT DEFAULT '',
  confidence         REAL,
  evidence_count     INTEGER DEFAULT 0,
  last_observed      TEXT DEFAULT '',
  verify_pass_count  INTEGER DEFAULT 0,
  user_confirmed     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS edges (
  from_id TEXT NOT NULL,
  rel     TEXT NOT NULL,
  to_id   TEXT NOT NULL,
  score   REAL,
  PRIMARY KEY (from_id, rel, to_id)
);
CREATE TABLE IF NOT EXISTS executions (
  execution_id TEXT PRIMARY KEY,
  task         TEXT,
  intent_type  TEXT,
  agent_id     TEXT,
  status       TEXT,
  verdict      TEXT,
  context_chars INTEGER,
  started_at   TEXT,
  finished_at  TEXT,
  payload      TEXT
);
CREATE TABLE IF NOT EXISTS trace_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT,
  step         TEXT,
  detail       TEXT,
  refs_json    TEXT,
  ts           TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT,
  rule_id      TEXT,
  verdict      TEXT,
  detail       TEXT,
  ts           TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5(
  ent_id UNINDEXED, type, subtype, domain, text, tokenize='trigram'
);
CREATE INDEX IF NOT EXISTS idx_exec_started ON executions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_exec ON trace_events(execution_id);
CREATE INDEX IF NOT EXISTS idx_ver_rule ON verifications(rule_id);
"""

#: Entity types the retriever may surface (memory covers all subtypes).
MEMORY_SUBTYPES = ("preference", "rule", "episodic", "semantic", "project_note")

#: Statuses that must NEVER influence retrieval / agent context.
#: superseded/rejected/suppressed = retired or corrected.
#: subtype-level exclusion (candidate / temporary) is enforced separately —
#: a promoted candidate's status becomes "confirmed" but it must STILL never
#: be retrieved (it lives on as its promoted preference/rule).
EXCLUDED_STATUSES = ("superseded", "rejected", "suppressed")
EXCLUDED_SUBTYPES = ("candidate", "temporary")

USER_ID = "u-master"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ReindexReport:
    entities: int = 0
    edges: int = 0
    fts_rows: int = 0
    executions: int = 0
    skills: int = 0

    def to_dict(self) -> dict:
        return {
            "entities": self.entities,
            "edges": self.edges,
            "fts_rows": self.fts_rows,
            "executions": self.executions,
            "skills": self.skills,
        }


@dataclass
class SearchHit:
    ent_id: str
    type: str
    subtype: str
    domain: str
    score: float
    content: str
    payload: dict = field(default_factory=dict)


class Store:
    """SQLite cognitive store. All writes are idempotent upserts; the db is
    disposable and rebuildable via :meth:`reindex`."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Apply additive migrations to older databases (idempotent).

        v1 → v2: add growth columns to ``entities``. Existing rows keep
        defaults ('' status, NULL confidence) — old data stays readable.
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(entities)")}
        for col, decl in (
            ("status", "TEXT DEFAULT ''"),
            ("confidence", "REAL"),
            ("evidence_count", "INTEGER DEFAULT 0"),
            ("last_observed", "TEXT DEFAULT ''"),
            ("verify_pass_count", "INTEGER DEFAULT 0"),
            ("user_confirmed", "INTEGER DEFAULT 0"),
        ):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE entities ADD COLUMN {col} {decl}")
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ write

    def upsert_entity(
        self,
        ent_id: str,
        type_: str,
        *,
        subtype: str = "",
        domain: str = "",
        content: str = "",
        payload: dict | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        status: str = "",
        confidence: float | None = None,
        evidence_count: int = 0,
        last_observed: str = "",
        verify_pass_count: int = 0,
        user_confirmed: bool = False,
    ) -> None:
        ts = created_at or now_iso()
        self._conn.execute(
            """
            INSERT INTO entities (id, type, subtype, domain, content,
                                  created_at, updated_at, payload,
                                  status, confidence, evidence_count,
                                  last_observed, verify_pass_count, user_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              subtype=excluded.subtype, domain=excluded.domain,
              content=excluded.content, updated_at=excluded.updated_at,
              payload=excluded.payload,
              status=excluded.status, confidence=excluded.confidence,
              evidence_count=excluded.evidence_count,
              last_observed=excluded.last_observed,
              verify_pass_count=excluded.verify_pass_count,
              user_confirmed=excluded.user_confirmed
            """,
            (
                ent_id, type_, subtype, domain, content, ts,
                updated_at or ts, json.dumps(payload or {}, ensure_ascii=False),
                status, confidence, evidence_count, last_observed,
                verify_pass_count, 1 if user_confirmed else 0,
            ),
        )
        self._conn.commit()

    def add_edge(self, from_id: str, rel: str, to_id: str, score: float | None = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO edges (from_id, rel, to_id, score) VALUES (?, ?, ?, ?)",
            (from_id, rel, to_id, score),
        )
        self._conn.commit()

    def add_fts(self, ent_id: str, type_: str, subtype: str, domain: str, text: str) -> None:
        self._conn.execute(
            "INSERT INTO mem_fts (ent_id, type, subtype, domain, text) VALUES (?, ?, ?, ?, ?)",
            (ent_id, type_, subtype, domain, text),
        )
        self._conn.commit()

    # ---------------------------------------------------------------- project

    def record_execution(self, exec_row: dict) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO executions
            (execution_id, task, intent_type, agent_id, status, verdict,
             context_chars, started_at, finished_at, payload)
            VALUES (:execution_id, :task, :intent_type, :agent_id, :status,
                    :verdict, :context_chars, :started_at, :finished_at, :payload)
            """,
            exec_row,
        )
        self._conn.commit()

    def record_event(self, execution_id: str, step: str, detail: str, refs: list | None, ts: str) -> None:
        self._conn.execute(
            "INSERT INTO trace_events (execution_id, step, detail, refs_json, ts) VALUES (?, ?, ?, ?, ?)",
            (execution_id, step, detail, json.dumps(refs or [], ensure_ascii=False), ts),
        )
        self._conn.commit()

    def record_verification(self, execution_id: str, rule_id: str, verdict: str, detail: str, ts: str) -> None:
        self._conn.execute(
            "INSERT INTO verifications (execution_id, rule_id, verdict, detail, ts) VALUES (?, ?, ?, ?, ?)",
            (execution_id, rule_id, verdict, detail, ts),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ read

    def search(self, query: str, *, types: tuple[str, ...] = ("memory", "skill"), limit: int = 10) -> list[SearchHit]:
        """Retrieve top hits for ``query``.

        FTS5 trigram MATCH first (substring-capable, CJK-friendly); falls
        back to a Python substring scan when the MATCH yields nothing —
        keeps retrieval deterministic for short queries like "SQL".
        """
        q = query.replace('"', " ").strip()
        if not q:
            return []

        type_clause = " AND type IN (%s)" % ",".join("?" for _ in types) if types else ""
        hits: dict[str, SearchHit] = {}
        fts_q = _fts_query(q)
        if fts_q:
            try:
                rows = self._conn.execute(
                    "SELECT ent_id, type, subtype, domain, bm25(mem_fts) AS r "
                    "FROM mem_fts WHERE mem_fts MATCH ?" + type_clause + " ORDER BY r LIMIT ?",
                    (fts_q, *types, limit),
                ).fetchall()
                for row in rows:
                    hit = self._hit_from_row(row, rank=float(row["r"] or 0.0))
                    if hit is not None:
                        hits[row["ent_id"]] = hit
            except sqlite3.Error:
                hits = {}

        if not hits:
            hits = self._substring_scan(q, types, limit)

        scored = list(hits.values())
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]

    def _hit_from_row(self, row: sqlite3.Row, rank: float) -> SearchHit | None:
        """Build a SearchHit; returns None when the entity is excluded
        (candidate / temporary / superseded / rejected / suppressed)."""
        ent = self._conn.execute(
            "SELECT content, payload, created_at, status, subtype, domain, confidence "
            "FROM entities WHERE id=?", (row["ent_id"],)
        ).fetchone()
        if ent is None:
            return None
        if (ent["subtype"] or "") in EXCLUDED_SUBTYPES:
            return None
        if (ent["status"] or "") in EXCLUDED_STATUSES:
            return None
        content, payload, created_at = ent["content"], ent["payload"], ent["created_at"]
        try:
            payload_d = json.loads(payload or "{}")
        except json.JSONDecodeError:
            payload_d = {}
        # bm25 is "lower is better" — invert into a positive score.
        score = -rank if rank < 0 else 1.0
        if created_at:
            score += _recency_boost(created_at)
        if ent["confidence"] is not None:
            score += 0.2 * float(ent["confidence"])
        return SearchHit(
            ent_id=row["ent_id"],
            type=row["type"],
            subtype=ent["subtype"] or row["subtype"] or "",
            domain=ent["domain"] or row["domain"] or "",
            score=round(score, 3),
            content=content,
            payload=payload_d,
        )

    def _substring_scan(self, q: str, types: tuple[str, ...], limit: int) -> dict[str, SearchHit]:
        hits: dict[str, SearchHit] = {}
        terms = _query_terms(q)
        if not terms:
            return {}
        rows = self._conn.execute(
            "SELECT id, type, subtype, domain, content, payload, created_at, status, confidence FROM entities"
        ).fetchall()
        for row in rows:
            content = (row["content"] or "").lower()
            if not any(t in content for t in terms):
                continue
            if (row["subtype"] or "") in EXCLUDED_SUBTYPES:
                continue
            if (row["status"] or "") in EXCLUDED_STATUSES:
                continue
            t = row["type"] or "memory"
            if types and t not in types:
                continue
            try:
                payload = json.loads(row["payload"] or "{}")
            except json.JSONDecodeError:
                payload = {}
            # score by how many terms matched
            matched = sum(1 for tm in terms if tm in content)
            score = matched + _recency_boost(row["created_at"] or "")
            if row["confidence"] is not None:
                score += 0.2 * float(row["confidence"])
            hits[row["id"]] = SearchHit(
                ent_id=row["id"],
                type=t,
                subtype=row["subtype"] or "",
                domain=row["domain"] or "",
                score=score,
                content=row["content"] or "",
                payload=payload,
            )
        return hits

    def entity(self, ent_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM entities WHERE id=?", (ent_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload"] or "{}")
        except json.JSONDecodeError:
            d["payload"] = {}
        return d

    def recent_executions(self, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM executions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = json.loads(d["payload"] or "{}")
            except json.JSONDecodeError:
                d["payload"] = {}
            d["events"] = self.execution_events(d["execution_id"])
            d["verifications"] = self.execution_verifications(d["execution_id"])
            out.append(d)
        return out

    def execution_events(self, execution_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT step, detail, refs_json, ts FROM trace_events WHERE execution_id=? ORDER BY id",
            (execution_id,),
        ).fetchall()
        out = []
        for row in rows:
            try:
                refs = json.loads(row["refs_json"] or "[]")
            except json.JSONDecodeError:
                refs = []
            out.append({"step": row["step"], "detail": row["detail"], "refs": refs, "ts": row["ts"]})
        return out

    def execution_verifications(self, execution_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT rule_id, verdict, detail, ts FROM verifications WHERE execution_id=? ORDER BY id",
            (execution_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def execution_count_on(self, date_prefix: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM executions WHERE execution_id LIKE ?",
            (f"{date_prefix}-%",),
        ).fetchone()
        return int(row["c"] or 0)

    def memory_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT subtype, COUNT(*) AS c FROM entities WHERE type='memory' GROUP BY subtype"
        ).fetchall()
        return {r["subtype"] or "memory": r["c"] for r in rows}

    def memories_for_regions(self) -> dict[str, list[dict]]:
        """Map real memory items onto dashboard brain regions by subtype."""
        mapping = {
            "prefrontal": ("preference",),
            "hippocampus": ("rule",),
            "cortex": ("semantic", "project_note"),
            "reflection": ("episodic",),
        }
        out: dict[str, list[dict]] = {}
        rows = self._conn.execute(
            "SELECT id, subtype, domain, content, created_at FROM entities WHERE type='memory'"
        ).fetchall()
        for row in rows:
            for region, subtypes in mapping.items():
                if (row["subtype"] or "") in subtypes:
                    out.setdefault(region, []).append(
                        {
                            "id": row["id"],
                            "subtype": row["subtype"],
                            "domain": row["domain"],
                            "content": (row["content"] or "")[:600],
                            "created_at": row["created_at"],
                        }
                    )
        for region in out:
            out[region].sort(key=lambda m: m["created_at"] or "", reverse=True)
            out[region] = out[region][:4]
        return out

    def skill_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM entities WHERE type='skill'").fetchone()
        return int(row["c"] or 0)

    # ---------------------------------------------------------------- reindex

    def reindex(self, paths: Paths) -> ReindexReport:
        """Rebuild the whole index from canonical sources. Idempotent."""
        user = UserLayer(root=paths.root / "user")
        report = ReindexReport()

        self._conn.execute("DELETE FROM entities")
        self._conn.execute("DELETE FROM edges")
        self._conn.execute("DELETE FROM mem_fts")
        self._conn.execute("DELETE FROM executions")
        self._conn.execute("DELETE FROM trace_events")
        self._conn.execute("DELETE FROM verifications")
        self._conn.commit()

        self.upsert_entity(
            USER_ID, "user", content="master", payload={"name": "master"},
        )
        report.entities = 1

        report.entities += self._index_rules(user)
        report.entities += self._index_memory_jsonl(user)
        report.entities += self._index_markdown_prefs(user)
        n_skills, n_agents = self._index_skills(paths)
        report.skills = n_skills
        report.entities += n_skills + n_agents

        report.executions = self._replay_traces(user)

        report.fts_rows = int(
            self._conn.execute("SELECT COUNT(*) AS c FROM mem_fts").fetchone()["c"]
        )
        report.edges = int(
            self._conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
        )
        return report

    # ---- canonical scanners ------------------------------------------------

    def _index_rules(self, user: UserLayer) -> int:
        n = 0
        rules_dir = user.root / "rules"
        if not rules_dir.exists():
            return 0
        for path in sorted(rules_dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rid = rec.get("id") or f"rule-{path.stem}"
            text = " ".join(
                str(rec.get(k, ""))
                for k in ("rule_zh", "rule_en", "probe_zh", "probe_en")
            ).strip()
            domain = rec.get("domain", "general")
            self.upsert_entity(
                rid, "memory", subtype="rule", domain=domain, content=text, payload=rec,
                status=rec.get("status", "confirmed"),
                confidence=rec.get("confidence"),
                evidence_count=int(rec.get("evidence_count", 0) or 0),
                last_observed=rec.get("last_observed", ""),
                verify_pass_count=int(rec.get("verify_pass_count", 0) or 0),
                user_confirmed=bool(rec.get("user_confirmed")),
                created_at=rec.get("created_at"),
            )
            self.add_edge(USER_ID, "owns", rid)
            self.add_fts(rid, "memory", "rule", domain, text)
            n += 1
        return n

    def _index_memory_jsonl(self, user: UserLayer) -> int:
        n = 0
        mem_dir = user.memory
        if not mem_dir.exists():
            return 0
        for path in sorted(mem_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mid = rec.get("id") or f"mem-{path.stem}-{n}"
                subtype = rec.get("type") or "episodic"
                text = rec.get("content") or ""
                domain = rec.get("domain", "general")
                self.upsert_entity(
                    mid, "memory", subtype=subtype, domain=domain, content=text,
                    payload=rec, created_at=rec.get("created_at"),
                    status=rec.get("status", ""),
                    confidence=rec.get("confidence"),
                    evidence_count=int(rec.get("evidence_count", 0) or 0),
                    last_observed=rec.get("last_observed", ""),
                    verify_pass_count=int(rec.get("verify_pass_count", 0) or 0),
                    user_confirmed=bool(rec.get("user_confirmed")),
                )
                self.add_edge(USER_ID, "owns", mid)
                if rec.get("derived_from_execution"):
                    self.add_edge(mid, "derived_from", str(rec["derived_from_execution"]))
                for src_id in rec.get("source_memories", []):
                    self.add_edge(mid, "derived_from", str(src_id))
                self.add_fts(mid, "memory", subtype, domain, text)
                n += 1
        return n

    def _index_markdown_prefs(self, user: UserLayer) -> int:
        """Index human-authored preference docs as paragraph-level entries."""
        n = 0
        for name in ("preferences.md", "style.md"):
            path = user.root / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for i, para in enumerate(_split_md_paragraphs(text)):
                mid = f"mem-{path.stem}-{i:03d}"
                self.upsert_entity(
                    mid, "memory", subtype="preference", domain="general",
                    content=para,
                    payload={"source": f"user/{name}", "_type": "memory", "_subtype": "preference"},
                    status="confirmed", confidence=0.95, user_confirmed=True,
                )
                self.add_edge(USER_ID, "owns", mid)
                self.add_fts(mid, "memory", "preference", "general", para)
                n += 1
        return n

    def _index_skills(self, paths: Paths) -> tuple[int, int]:
        """Index skill registrations. Returns (n_skills, n_agents)."""
        n_skills = 0
        n_agents = 0
        sources_root = paths.sources
        if not sources_root.exists():
            return 0, 0
        for agent_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
            agent_id = agent_dir.name
            self.upsert_entity(
                f"agent-{agent_id}", "agent", content=agent_id,
                payload={"agent_id": agent_id, "_type": "agent"},
            )
            n_agents += 1
            for skill_md in sorted(agent_dir.rglob("SKILL.md")):
                name = skill_md.parent.name
                skill_id = f"skill-{agent_id}:{name}"
                title, desc = _skill_summary(skill_md)
                text = f"{name} {title} {desc}"
                rel = str(skill_md.parent.relative_to(sources_root))
                self.upsert_entity(
                    skill_id, "skill", domain=agent_id, content=text,
                    payload={
                        "name": name, "description": desc, "agent": agent_id,
                        "path": str(rel), "_type": "skill",
                    },
                )
                self.add_edge(skill_id, "provided_by", f"agent-{agent_id}")
                self.add_fts(skill_id, "skill", "", agent_id, text)
                n_skills += 1
        return n_skills, n_agents

    def _replay_traces(self, user: UserLayer) -> int:
        n = 0
        traces_dir = user.traces
        if not traces_dir.exists():
            return 0
        for path in sorted(traces_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "execution":
                    payload = {k: v for k, v in rec.items() if k != "type"}
                    refs = payload.pop("refs", [])
                    self.record_execution(
                        {
                            "execution_id": rec["execution_id"],
                            "task": rec.get("task", ""),
                            "intent_type": rec.get("intent_type", ""),
                            "agent_id": rec.get("agent_id") or "",
                            "status": rec.get("status", ""),
                            "verdict": rec.get("verdict", ""),
                            "context_chars": rec.get("context_chars") or 0,
                            "started_at": rec.get("started_at", ""),
                            "finished_at": rec.get("finished_at", ""),
                            "payload": json.dumps(payload, ensure_ascii=False),
                        }
                    )
                    n += 1
                elif rec.get("type") == "event":
                    self.record_event(
                        rec["execution_id"], rec.get("step", ""),
                        rec.get("detail", ""), rec.get("refs"), rec.get("ts", ""),
                    )
                elif rec.get("type") == "verification":
                    self.record_verification(
                        rec["execution_id"], rec.get("rule_id", ""),
                        rec.get("verdict", ""), rec.get("detail", ""), rec.get("ts", ""),
                    )
        return n


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _split_md_paragraphs(text: str) -> list[str]:
    """Split a markdown doc into block paragraphs; skip headings/empty lines."""
    blocks: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            if buf:
                blocks.append("\n".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        blocks.append("\n".join(buf))
    return [b for b in blocks if b.strip() and not b.strip().startswith("#")]


def _fts_query(q: str) -> str | None:
    """Build an OR-of-terms FTS5 query.

    The default FTS5 multi-token MATCH is AND semantics — a query like
    "写一个 SQL 查询" would require ALL tokens to appear, killing recall.
    We OR the terms (ascii tokens + CJK bigrams) instead: any term present
    counts, bm25 ranks the multi-term matches first.
    """
    terms = _query_terms(q)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def _query_terms(q: str, max_terms: int = 40) -> list[str]:
    """Split a query into matchable terms: ascii tokens + CJK bigrams.

    The whole-string substring match fails for real queries (task text and
    memory text only overlap on keywords like "SQL"), so we match on terms:
    any term present in the candidate content counts as a hit, more matched
    terms score higher.
    """
    terms: list[str] = []
    for t in re.findall(r"[a-zA-Z0-9_]+", q):
        lt = t.lower()
        if lt not in terms:
            terms.append(lt)
    zh = re.sub(r"[^\u4e00-\u9fff]+", " ", q)
    for chunk in zh.split():
        if len(chunk) < 2:
            continue
        for i in range(len(chunk) - 1):
            bg = chunk[i : i + 2]
            if bg not in terms:
                terms.append(bg)
        if len(terms) >= max_terms:
            break
    return terms[:max_terms]


def _skill_summary(path: Path, max_chars: int = 500) -> tuple[str, str]:
    """(title, description) from a SKILL.md frontmatter; falls back to first lines."""
    title, desc = "", ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    in_fm = False
    for line in text.splitlines()[:40]:
        s = line.strip()
        if s == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm:
            if s.startswith("name:"):
                title = s.split(":", 1)[1].strip()
            elif s.startswith("description:"):
                desc = s.split(":", 1)[1].strip().strip('"\'')
    if not desc:
        body = "\n".join(
            l for l in text.splitlines() if l.strip() and not l.startswith(("#", "---", "name:", "description:"))
        )[: max_chars]
        desc = body
    return title, desc[:max_chars]


def _recency_boost(created_at: str) -> float:
    """+0.3 fresh, decaying to ~0 after ~90 days."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0
    if age_days < 0:
        age_days = 0
    return 0.3 * (2.71828 ** (-age_days / 30.0))
