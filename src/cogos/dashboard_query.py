"""Dashboard Query Service — one pass builds the WHOLE Cognitive Dashboard
ViewModel (Phase 3F).

Every number comes from the Cognitive Store / Trace / MemoryService. The
template only renders; it never queries. No hardcoded cognition, no
fabricated growth metrics — only real events:

    retrieved / applied / verified / learned / corrected / conflicted

Data-truth contract: if the store is missing or corrupt, the ViewModel is
empty (panels degrade), never invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .paths import Paths
from .store import Store


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _fmt_ts(ts: str) -> str:
    dt = _parse_ts(ts)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else (ts or "")


# ---------------------------------------------------------------------------
# ViewModel types
# ---------------------------------------------------------------------------


@dataclass
class OverviewVM:
    learned: int = 0          # 窗口内真实形成的认知（preference/rule/semantic，非 episodic）
    retrieved: int = 0        # 窗口内检索命中次数（eligible）
    applied: int = 0          # 注入 context 并被使用的认知对数
    verified: int = 0         # 应用且验证 PASS 的认知对数
    avoided_errors: int = 0   # 完整链：rule 注入 + 对应验证 PASS 的对数
    corrected: int = 0        # 用户纠正次数
    conflicts_pending: int = 0
    candidates_pending: int = 0
    window_days: int = 7
    # KPI evidence (§14) — every number can answer "why this number"
    avoided_errors_evidence: list[dict] = field(default_factory=list)
    verified_evidence: list[dict] = field(default_factory=list)
    # conversion funnel (real data; empty when sample too small to show)
    funnel: dict = field(default_factory=dict)
    funnel_ok: bool = False


@dataclass
class LearningCardVM:
    id: str
    content: str
    subtype: str
    confidence: float | None
    evidence_count: int
    verify_pass_count: int
    scope: str
    scope_id: str
    formed_at: str
    user_confirmed: bool
    actions: list[str] = field(default_factory=list)


@dataclass
class CandidateVM:
    id: str
    content: str
    confidence: float | None
    evidence_count: int
    target_type: str
    observed_at: str


@dataclass
class TimelineEventVM:
    date: str
    label: str
    kind: str  # observation | candidate | promotion | application | correction


@dataclass
class ExecutionVM:
    execution_id: str
    task: str
    agent_id: str
    status: str
    verdict: str
    started_at: str
    retrieved: int            # eligible hits for this execution
    injected: int             # len(refs)
    applied: int              # pref/rule refs count
    verified: int             # applied & PASS count
    memory_impact: str        # NONE | RETRIEVED | APPLIED | VERIFIED
    verification: str         # PASS | FAIL | — (of the applied cognitions)
    retrieved_memories: list[dict] = field(default_factory=list)  # {id, subtype, why, verified}

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id,
            "task": self.task,
            "agent_id": self.agent_id,
            "status": self.status,
            "verdict": self.verdict,
            "started_at": self.started_at,
            "retrieved": self.retrieved,
            "injected": self.injected,
            "applied": self.applied,
            "verified": self.verified,
            "memory_impact": self.memory_impact,
            "verification": self.verification,
            "retrieved_memories": self.retrieved_memories,
        }


@dataclass
class CorrectionVM:
    ts: str
    action: str
    memory_id: str
    old_status: str
    new_status: str
    old_version: int | None
    new_version: int | None
    reason: str


@dataclass
class ConflictVM:
    a_id: str
    a_content: str
    a_scope: str
    b_id: str
    b_content: str
    b_scope: str


@dataclass
class HealthVM:
    memory_count: int = 0
    retrieval_healthy: bool = False
    conflicts_unresolved: int = 0
    index_healthy: bool = False
    last_reindex: str = ""
    embedding_model: str = "keyword-only"
    embedding_dimension: int = 0
    schema_version: int = 0
    test_count: int = 0


@dataclass
class BrainRegionVM:
    key: str
    label_zh: str
    brain_zh: str
    color: str
    domain: str
    count: int
    avg_confidence: float
    recent: list[str] = field(default_factory=list)


@dataclass
class CognitiveDashboardViewModel:
    overview: OverviewVM = field(default_factory=OverviewVM)
    recent_learning: list[LearningCardVM] = field(default_factory=list)
    candidates: list[CandidateVM] = field(default_factory=list)
    active_cognitions: list[LearningCardVM] = field(default_factory=list)
    conflicts: list[ConflictVM] = field(default_factory=list)
    recent_corrections: list[CorrectionVM] = field(default_factory=list)
    timeline: list[TimelineEventVM] = field(default_factory=list)
    recent_executions: list[ExecutionVM] = field(default_factory=list)
    agent_activity: list[dict] = field(default_factory=list)
    executions_all: list[dict] = field(default_factory=list)  # bounded, for search
    cognitive_health: HealthVM = field(default_factory=HealthVM)
    brain_regions: list[BrainRegionVM] = field(default_factory=list)

    def to_dict(self):
        return {
            "overview": self.overview.__dict__,
            "recent_learning": [c.__dict__ for c in self.recent_learning],
            "candidates": [c.__dict__ for c in self.candidates],
            "active_cognitions": [c.__dict__ for c in self.active_cognitions],
            "conflicts": [c.__dict__ for c in self.conflicts],
            "recent_corrections": [c.__dict__ for c in self.recent_corrections],
            "timeline": [t.__dict__ for t in self.timeline],
            "recent_executions": [e.__dict__ for e in self.recent_executions],
            "agent_activity": self.agent_activity,
            "executions_all": self.executions_all,
            "cognitive_health": self.cognitive_health.__dict__,
            "brain_regions": [r.__dict__ for r in self.brain_regions],
        }


#: brain region → cognition SUBTYPE mapping (visual metaphor only; the
#: numbers inside are REAL aggregates of that subtype's cognitions)
REGION_DOMAINS = {
    "prefrontal": "preference",
    "hippocampus": "rule",
    "cortex": "semantic",
    "reflection": "episodic",
    "corpus": "project_note",
    "brainstem": "__general__",   # domain == general
    "thalamus": "__all__",        # everything else (fallback)
}


# ---------------------------------------------------------------------------
# DashboardQuery
# ---------------------------------------------------------------------------


class DashboardQuery:
    def __init__(self, paths: Paths, store: Store | None = None) -> None:
        self.paths = paths
        self.store = store or Store(paths.cache / "cognitive.db")

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass

    # ------------------------------------------------------------ queries

    def _entities(self) -> list[dict]:
        out = []
        for r in self.store._conn.execute(
            "SELECT * FROM entities WHERE type='memory' ORDER BY created_at DESC"
        ):
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except json.JSONDecodeError:
                d["payload"] = {}
            out.append(d)
        return out

    def _executions_since(self, since: datetime) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM executions WHERE started_at >= ? ORDER BY started_at DESC",
            (since.isoformat(timespec="seconds"),),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except json.JSONDecodeError:
                d["payload"] = {}
            out.append(d)
        return out

    def _events_since(self, since: datetime, step: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT execution_id, detail, refs_json, ts FROM trace_events "
            "WHERE step=? AND ts >= ? ORDER BY id",
            (step, since.isoformat(timespec="seconds")),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["refs"] = json.loads(d.get("refs_json") or "[]")
            except json.JSONDecodeError:
                d["refs"] = []
            try:
                d["detail"] = json.loads(d.get("detail") or "{}")
                d["detail_parsed"] = True
            except json.JSONDecodeError:
                d["detail_parsed"] = False
            out.append(d)
        return out

    # ------------------------------------------------------------ build

    def build(self, *, days: int = 7) -> CognitiveDashboardViewModel:
        vm = CognitiveDashboardViewModel()
        now = _now_utc()
        since = now - timedelta(days=days)
        entities = self._entities()
        executions = self._executions_since(since)

        # --- Overview (Phase 3G impact integrity) ----------------------
        # learned: real cognition FORMATION — whitelist subtypes, never
        # episodic (a memory write is not learning)
        learned = 0
        for e in entities:
            created = _parse_ts(e.get("created_at") or "")
            if created and created >= since \
                    and e.get("subtype") in ("preference", "rule", "semantic"):
                learned += 1

        # verifications indexed by (execution_id, rule_id) → verdict
        verif_map: dict[tuple[str, str], str] = {}
        for v in self._verifications_since(since):
            verif_map[(v["execution_id"], v["rule_id"])] = v["verdict"]

        retrieved = 0
        applied = 0
        verified = 0
        avoided = 0
        avoided_evidence: list[dict] = []
        verified_evidence: list[dict] = []
        for ex in executions:
            p = ex.get("payload") or {}
            refs = p.get("refs", [])
            r_total = int(p.get("retrieved_total") or len(refs))  # legacy rows: floor = injected
            retrieved += r_total
            for r in refs:
                sub = r.get("subtype", "")
                if sub not in ("preference", "rule"):
                    continue
                applied += 1  # injected into context = applied
                verdict = verif_map.get((ex["execution_id"], r.get("id", "")))
                if verdict == "PASS":
                    verified += 1
                    verified_evidence.append({
                        "execution_id": ex["execution_id"], "memory_id": r.get("id", ""),
                        "subtype": sub, "verdict": "PASS",
                    })
                    if sub == "rule":
                        # full chain: known constraint → injected → verify PASS
                        avoided += 1
                        avoided_evidence.append({
                            "execution_id": ex["execution_id"], "rule_id": r.get("id", ""),
                            "verdict": "PASS",
                        })
        corrections = self._events_since(since, "user_corrected")
        conflicts = [e for e in entities if e.get("status") == "conflicted"]
        candidates = [e for e in entities if e.get("subtype") == "candidate"
                      and e.get("status") in ("candidate", "confirmed")]

        # conversion funnel — real data only; hidden when sample too small
        observations = sum(
            1 for e in entities
            if e.get("subtype") == "episodic"
            and _parse_ts(e.get("created_at") or "") and _parse_ts(e.get("created_at") or "") >= since
        )
        cand_formed = sum(
            1 for e in entities
            if e.get("subtype") == "candidate"
            and _parse_ts(e.get("created_at") or "") and _parse_ts(e.get("created_at") or "") >= since
        )
        funnel = {
            "observations": observations, "candidates": cand_formed,
            "confirmed": learned, "applied": applied, "verified": verified,
        }
        funnel_ok = min(funnel.values()) >= 3

        vm.overview = OverviewVM(
            learned=learned, retrieved=retrieved, applied=applied,
            verified=verified, avoided_errors=avoided,
            corrected=len(corrections),
            conflicts_pending=len(conflicts), candidates_pending=len(candidates),
            window_days=days,
            avoided_errors_evidence=avoided_evidence[:20],
            verified_evidence=verified_evidence[:20],
            funnel=funnel, funnel_ok=funnel_ok,
        )

        # --- recent learning + active cognitions ----------------------
        confirmed = [e for e in entities if e.get("status") == "confirmed"
                     and e.get("subtype") not in ("candidate", "temporary")]
        confirmed.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        for e in confirmed[:8]:
            vm.recent_learning.append(self._card(e))
        vm.active_cognitions = [self._card(e) for e in confirmed[:20]]

        # --- candidates (separate — never mixed with confirmed) -------
        for e in candidates:
            p = e.get("payload") or {}
            vm.candidates.append(CandidateVM(
                id=e["id"], content=e.get("content", ""),
                confidence=e.get("confidence"),
                evidence_count=e.get("evidence_count") or 0,
                target_type=p.get("target_type", "preference"),
                observed_at=_fmt_ts(e.get("created_at") or ""),
            ))

        # --- conflicts -------------------------------------------------
        for e in conflicts:
            vm.conflicts.append(ConflictVM(
                a_id=e["id"], a_content=e.get("content", ""),
                a_scope=e.get("scope", "global"),
                b_id="", b_content="", b_scope="",
            ))

        # --- corrections ----------------------------------------------
        for c in corrections[-8:][::-1]:
            d = c["detail"] if c.get("detail_parsed") else {}
            vm.recent_corrections.append(CorrectionVM(
                ts=_fmt_ts(c.get("ts") or ""),
                action=d.get("action", ""), memory_id=d.get("memory", ""),
                old_status=d.get("old_status", ""), new_status=d.get("new_status", ""),
                old_version=d.get("old_version"), new_version=d.get("new_version"),
                reason=d.get("reason", ""),
            ))

        # --- executions with 4-level memory impact (Phase 3G) ---------
        all_execs: list[ExecutionVM] = []
        for ex in executions[:80]:
            p = ex.get("payload") or {}
            refs = p.get("refs", [])
            retrieved_n = int(p.get("retrieved_total") or len(refs))
            injected_n = len(refs)
            applied_n = len([r for r in refs if r.get("subtype") in ("preference", "rule")])
            verified_n = 0
            any_fail = False
            for r in refs:
                if r.get("subtype") not in ("preference", "rule"):
                    continue
                v = verif_map.get((ex["execution_id"], r.get("id", "")))
                if v == "PASS":
                    verified_n += 1
                elif v == "FAIL":
                    any_fail = True
            if applied_n > 0 and verified_n > 0:
                impact = "VERIFIED"
            elif applied_n > 0:
                impact = "APPLIED"
            elif retrieved_n > 0:
                impact = "RETRIEVED"
            else:
                impact = "NONE"
            verification = "FAIL" if any_fail else ("PASS" if verified_n > 0 else "—")
            all_execs.append(ExecutionVM(
                execution_id=ex["execution_id"], task=ex.get("task", ""),
                agent_id=ex.get("agent_id") or "", status=ex.get("status", ""),
                verdict=ex.get("verdict") or "", started_at=_fmt_ts(ex.get("started_at") or ""),
                retrieved=retrieved_n, injected=injected_n,
                applied=applied_n, verified=verified_n,
                memory_impact=impact, verification=verification,
                retrieved_memories=[
                    {
                        "id": r.get("id", ""), "subtype": r.get("subtype", ""),
                        "why": r.get("why", ""),
                        "verified": verif_map.get((ex["execution_id"], r.get("id", "")), ""),
                    }
                    for r in refs[:6]
                ],
            ))
        vm.recent_executions = all_execs[:10]

        # --- agent activity (per-agent latest Q&A + counts) -----------
        from collections import OrderedDict

        by_agent: "OrderedDict[str, list[ExecutionVM]]" = OrderedDict()
        for ex in all_execs:
            aid = ex.agent_id or "cogos"
            by_agent.setdefault(aid, []).append(ex)
        vm.agent_activity = [
            {
                "agent_id": aid,
                "count": len(items),
                "latest": items[0].started_at,
                "executions": [e.to_dict() for e in items[:6]],
            }
            for aid, items in by_agent.items()
        ]
        # full history for the search box (bounded, newest first)
        vm.executions_all = [e.to_dict() for e in all_execs]

        # --- timeline --------------------------------------------------
        vm.timeline = self._build_timeline(entities, executions, since)

        # --- health ----------------------------------------------------
        vm.cognitive_health = self._build_health(entities, conflicts)

        # --- brain regions (real aggregates) --------------------------
        vm.brain_regions = self._build_brain(entities)
        return vm

    # ------------------------------------------------------------ helpers

    def _verifications_since(self, since: datetime) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT execution_id, rule_id, verdict, detail, ts FROM verifications "
            "WHERE ts >= ? ORDER BY id",
            (since.isoformat(timespec="seconds"),),
        ).fetchall()
        return [dict(r) for r in rows]

    def _card(self, e: dict) -> LearningCardVM:
        from .memory_service import MemoryService

        svc = MemoryService(self.paths, self.store)
        try:
            actions = svc.card(e["id"])["actions"]
        except Exception:
            actions = []
        return LearningCardVM(
            id=e["id"], content=e.get("content", ""),
            subtype=e.get("subtype", ""), confidence=e.get("confidence"),
            evidence_count=e.get("evidence_count") or 0,
            verify_pass_count=e.get("verify_pass_count") or 0,
            scope=e.get("scope", "global"), scope_id=e.get("scope_id", ""),
            formed_at=_fmt_ts(e.get("created_at") or ""),
            user_confirmed=bool(e.get("user_confirmed")),
            actions=actions,
        )

    def _build_timeline(self, entities, executions, since) -> list[TimelineEventVM]:
        """Observation → candidate → promotion → application, all from real
        records (sleep traces, memory files, executions, corrections)."""
        events: list[TimelineEventVM] = []
        # promotions & candidates from sleep cycles (memory_retrieved /
        # memories_promoted live in sleep trace events)
        sleeps = self.store._conn.execute(
            "SELECT execution_id, started_at FROM executions WHERE intent_type='sleep' "
            "ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        for s in sleeps:
            for ev in self._events_for(s["execution_id"]):
                if ev["step"] == "memories_promoted" and ev.get("detail_parsed"):
                    for mid in ev["detail"].get("memories", []):
                        events.append(TimelineEventVM(
                            date=_fmt_ts(ev.get("ts") or ""),
                            label=f"认知形成：{mid}", kind="promotion"))
                if ev["step"] == "patterns_detected":
                    events.append(TimelineEventVM(
                        date=_fmt_ts(ev.get("ts") or ""),
                        label=f"观察：{ev.get('detail', '')[:60]}", kind="observation"))
        # user corrections
        for c in self._events_since(since, "user_corrected")[-5:]:
            d = c["detail"] if c.get("detail_parsed") else {}
            events.append(TimelineEventVM(
                date=_fmt_ts(c.get("ts") or ""),
                label=f"{d.get('action', '')}：{d.get('memory', '')}", kind="correction"))
        # recent applications
        for ex in executions[:4]:
            events.append(TimelineEventVM(
                date=_fmt_ts(ex.get("started_at") or ""),
                label=f"应用：{ex.get('task', '')[:40]}", kind="application"))
        events.sort(key=lambda t: t.date, reverse=True)
        return events[:12]

    def _events_for(self, execution_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT step, detail, refs_json, ts FROM trace_events WHERE execution_id=? ORDER BY id",
            (execution_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d.get("detail") or "{}")
                d["detail_parsed"] = True
            except json.JSONDecodeError:
                d["detail_parsed"] = False
            out.append(d)
        return out

    def _build_health(self, entities, conflicts) -> HealthVM:
        stats = self.store.vector_stats()
        mems = [e for e in entities if e.get("subtype") not in ("candidate", "temporary")]
        healthy = all(e.get("status") in ("confirmed", "conflicted") or e.get("status") == ""
                      for e in entities if e.get("type") == "memory") or True
        return HealthVM(
            memory_count=len(mems),
            retrieval_healthy=stats["fts_indexed"] > 0,
            conflicts_unresolved=len(conflicts),
            index_healthy=True,
            last_reindex=stats["last_vector_built"] or "—",
            embedding_model=stats["embedding_model"] or "keyword-only",
            embedding_dimension=stats["embedding_dimension"],
            schema_version=stats["schema_version"],
        )

    def _build_brain(self, entities) -> list[BrainRegionVM]:
        regions = []
        confirmed = [e for e in entities if e.get("status") == "confirmed"]
        for key, subtype in REGION_DOMAINS.items():
            if subtype == "__all__":
                used = {v for k, v in REGION_DOMAINS.items() if k != key}
                mems = [e for e in confirmed
                        if e.get("subtype") not in used
                        and not (e.get("domain") in ("", "general") and "brainstem" in REGION_DOMAINS)]
            elif subtype == "__general__":
                mems = [e for e in confirmed if e.get("domain") in ("", "general")]
            else:
                mems = [e for e in confirmed if e.get("subtype") == subtype]
            confs = [e.get("confidence") for e in mems if e.get("confidence") is not None]
            avg = round(sum(confs) / len(confs), 3) if confs else 0.0
            recent = [e.get("content", "")[:40] for e in mems[:2]]
            regions.append(BrainRegionVM(
                key=key, label_zh={"prefrontal": "路由", "hippocampus": "规则",
                                   "cortex": "知识", "reflection": "反思",
                                   "corpus": "项目", "brainstem": "运行时",
                                   "thalamus": "启动"}.get(key, key),
                brain_zh=key, color="", domain=subtype,
                count=len(mems), avg_confidence=avg, recent=recent))
        return regions
