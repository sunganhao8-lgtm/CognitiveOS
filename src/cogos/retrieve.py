"""Retrieval + context building — the Retrieve and Apply steps.

Phase 2/3A/3B: keyword retrieval (FTS5) + bounded context builder.
Phase 3C: the Retrieval Engine — three-layer model from the frozen contract
(docs/cognitive-retrieval.md):

    Eligibility (hard filter) → Relevance (keyword + semantic, RRF)
    → Priority (scope + confidence + recency + confirmation)

Every RetrievedItem carries why_retrieved so any injected cognition can
answer "why was it found / why was it injected?".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .store import SearchHit, Store

DEFAULT_BUDGET = 4000
RRF_K = 60
#: semantic channel floor: below this cosine, a memory is NOT a semantic hit
#: (§24 — "semantic similarity > 0" alone never qualifies an injection).
#: bge-family models sit ~0.5-0.6 for relevant zh pairs; unrelated text
#: typically lands 0.2-0.45.
MIN_SIMILARITY = 0.5
SECTION_CAPS = {
    "preferences": 600,
    "rules": 600,
    "memories": 1600,
    "skills": 600,
    "knowledge": 600,
    "projects": 400,
}
SECTION_LABELS = {
    "preferences": "相关用户偏好",
    "rules": "相关规则",
    "memories": "相关记忆",
    "skills": "相关技能",
    "knowledge": "相关知识",
    "projects": "相关项目上下文",
}
PER_TYPE_LIMITS = {
    "preference": 2,
    "rule": 2,
    "episodic": 4,
    "semantic": 4,
    "project_note": 1,
    "skill": 2,
}


# ---------------------------------------------------------------------------
# Phase 3C — Retrieval Engine contract types
# ---------------------------------------------------------------------------


@dataclass
class RetrievalRequest:
    task_text: str
    domain: str = "general"
    scope: str = "global"
    scope_id: str = ""
    execution_id: str = ""
    agent_id: str = ""


@dataclass
class RetrievedItem:
    memory_id: str
    retrieval_method: str = "keyword"  # keyword | semantic | hybrid
    keyword_rank: int | None = None
    semantic_rank: int | None = None
    similarity: float | None = None
    rrf_score: float = 0.0
    confidence: float | None = None
    scope: str = "global"
    scope_match: bool = False
    status: str = ""
    version: int = 1
    why_retrieved: str = ""
    content: str = ""
    subtype: str = ""

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "retrieval_method": self.retrieval_method,
            "keyword_rank": self.keyword_rank,
            "semantic_rank": self.semantic_rank,
            "similarity": self.similarity,
            "rrf_score": self.rrf_score,
            "confidence": self.confidence,
            "scope": self.scope,
            "scope_match": self.scope_match,
            "status": self.status,
            "version": self.version,
            "why_retrieved": self.why_retrieved,
        }


def _scope_match(request: RetrievalRequest, ent: dict) -> bool:
    """Does this cognition's scope apply to the task's scope?"""
    if request.scope == "global":
        return ent.get("scope", "global") == "global"
    if ent.get("scope") == "global":
        return True  # global cognition applies everywhere
    if ent.get("scope") == request.scope:
        return not request.scope_id or ent.get("scope_id", "") == request.scope_id
    return False


def _scope_priority(request: RetrievalRequest, ent: dict) -> int:
    """Scope-based priority: exact project/task match > global > other."""
    s = ent.get("scope", "global")
    if request.scope != "global" and s == request.scope and ent.get("scope_id", "") == request.scope_id:
        return 3
    if request.scope != "global" and s == request.scope:
        return 3
    if s == "global":
        return 2
    return 1


def eligibility_filter(store: Store, request: RetrievalRequest, hits: list[SearchHit]) -> list[SearchHit]:
    """① Eligibility (hard filter, BEFORE scoring — contract §3).

    store.search already excludes candidate/temporary/superseded/rejected/
    suppressed (subtype/status level). Here we additionally drop conflicted
    entries (they must never inject as ordinary cognitions) and entries
    whose scope cannot apply to the task.
    """
    out: list[SearchHit] = []
    for h in hits:
        ent = store.entity(h.ent_id)
        if ent is None:
            continue
        if ent.get("status") == "conflicted":
            continue
        out.append(h)
    return out


def semantic_rank_items(
    store: Store, provider, request: RetrievalRequest, eligible_ids: list[str],
    *, min_similarity: float = MIN_SIMILARITY,
) -> dict[str, tuple[int, float]]:
    """② semantic channel: cosine over the eligible set.

    Returns id → (rank, similarity) for entries ABOVE the similarity floor.
    Missing vectors are embedded on the fly (eligible set is small) and
    cached into the store — embedding is derived data, so write-through is
    safe.
    """
    if provider is None or not eligible_ids:
        return {}
    from . import embedding as emb

    vecs = store.vectors_for(eligible_ids, model=provider.name)
    missing = [eid for eid in eligible_ids if eid not in vecs]
    if missing:
        contents = store.eligible_content(missing)
        try:
            new_vecs = provider.embed([contents.get(mid, "") for mid in missing])
            for mid, vec in zip(missing, new_vecs):
                store.upsert_vector(
                    mid,
                    content_hash=emb.content_hash(contents.get(mid, "")),
                    model=provider.name,
                    dimension=provider.dimension,
                    vector=emb.pack_vector(vec),
                )
                vecs[mid] = vec
        except Exception:
            pass  # degrade: semantic channel skips what it can't embed
    try:
        q_vec = provider.embed([request.task_text])[0]
    except Exception:
        return {}
    scored = [(mid, emb.cosine(q_vec, v)) for mid, v in vecs.items()]
    scored = [(mid, sim) for mid, sim in scored if sim >= min_similarity]
    scored.sort(key=lambda t: t[1], reverse=True)
    return {mid: (i + 1, round(sim, 4)) for i, (mid, sim) in enumerate(scored)}


def rrf(keyword_rank: int | None, semantic_rank: int | None, *, k: int = RRF_K) -> float:
    """Reciprocal Rank Fusion (contract §3): Σ 1/(k + rank)."""
    score = 0.0
    if keyword_rank is not None:
        score += 1.0 / (k + keyword_rank)
    if semantic_rank is not None:
        score += 1.0 / (k + semantic_rank)
    return round(score, 6)


def retrieve_ranked(
    store: Store,
    provider,
    request: RetrievalRequest,
    *,
    mode: str = "auto",  # keyword | semantic | hybrid | auto
    limit: int = 12,
    k: int = RRF_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[RetrievedItem]:
    """The 3C retrieval engine — eligibility → relevance → priority.

    mode:
      keyword  — FTS5 only (the Phase 2/3A/3B behavior, always available)
      semantic — embedding only
      hybrid   — FTS5 + embedding + RRF
      auto     — hybrid when a provider is available, else keyword
    """
    use_sem = (mode in ("semantic", "hybrid")) or (mode == "auto" and provider is not None)
    use_kw = mode != "semantic"

    if use_sem and provider is None:
        use_sem = False
        mode = "keyword" if mode != "auto" else "keyword"

    hits = store.search(request.task_text, types=("memory", "skill"), limit=50)
    eligible = eligibility_filter(store, request, hits)

    kw_ranks: dict[str, int] = {}
    if use_kw:
        kw_ranks = {h.ent_id: i + 1 for i, h in enumerate(eligible)}

    sem_ranks: dict[str, tuple[int, float]] = {}
    if use_sem:
        # The semantic channel ranks the FULL eligible set independently of
        # keyword hits (contract §3②) — otherwise semantic can never rescue
        # a query that shares no token with the memory ("帮我查销售数据").
        sem_ranks = semantic_rank_items(
            store, provider, request, store.all_eligible_memory_ids(),
            min_similarity=min_similarity,
        )

    union_ids: set[str] = set(kw_ranks) | set(sem_ranks)
    items: list[RetrievedItem] = []
    for eid in union_ids:
        ent = store.entity(eid)
        if ent is None:
            continue
        if ent.get("status") == "conflicted":
            continue
        kw_r = kw_ranks.get(eid)
        sem_r = sem_ranks.get(eid)
        sim = sem_r[1] if sem_r else None
        score = rrf(kw_r, sem_r[0] if sem_r else None, k=k)
        if score <= 0.0:
            continue
        method = "hybrid" if (kw_r is not None and sem_r is not None) else (
            "semantic" if sem_r is not None else "keyword"
        )
        sm = _scope_match(request, ent)
        reasons = []
        if kw_r is not None:
            reasons.append(f"关键词命中 rank={kw_r}")
        if sem_r is not None:
            reasons.append(f"语义相似 {sim}")
        reasons.append(f"scope={ent.get('scope', 'global')}{' (匹配任务范围)' if sm else ''}")
        items.append(RetrievedItem(
            memory_id=eid,
            retrieval_method=method,
            keyword_rank=kw_r,
            semantic_rank=sem_r[0] if sem_r else None,
            similarity=sim,
            rrf_score=score,
            confidence=ent.get("confidence"),
            scope=ent.get("scope", "global"),
            scope_match=sm,
            status=ent.get("status", ""),
            version=ent.get("version", 1),
            why_retrieved="; ".join(reasons),
            content=ent.get("content", ""),
            subtype=ent.get("subtype", ""),
        ))

    # ③ Priority: relevance picks the pool (2×limit), priority orders it.
    items.sort(key=lambda i: i.rrf_score, reverse=True)
    pool = items[: limit * 2]

    def priority(item: RetrievedItem) -> tuple:
        ent = store.entity(item.memory_id) or {}
        sp = _scope_priority(request, ent)
        conf = (ent.get("confidence") or 0.0)
        uc = 1.0 if ent.get("user_confirmed") else 0.0
        return (-(sp * 10 + conf * 0.5 + uc * 0.5), -item.rrf_score)

    pool.sort(key=priority)
    final = pool[:limit]

    # per-type caps still apply (same contract as Phase 2)
    capped: list[RetrievedItem] = []
    used: dict[str, int] = {}
    for item in final:
        key = item.subtype or "skill"
        cap = PER_TYPE_LIMITS.get(key, 2)
        if used.get(key, 0) >= cap:
            continue
        capped.append(item)
        used[key] = used.get(key, 0) + 1
    return capped


# ---------------------------------------------------------------------------
# Phase 2/3A/3B — keyword retrieval + context builder (unchanged behavior)
# ---------------------------------------------------------------------------


@dataclass
class RetrievedSet:
    hits: list[SearchHit] = field(default_factory=list)

    def by_section(self) -> dict[str, list[SearchHit]]:
        sections: dict[str, list[SearchHit]] = {}
        for h in self.hits:
            if h.type == "skill":
                key = "skills"
            elif h.type == "memory" and h.subtype in ("preference",):
                key = "preferences"
            elif h.type == "memory" and h.subtype == "rule":
                key = "rules"
            elif h.type == "memory" and h.subtype == "project_note":
                key = "projects"
            elif h.type == "memory":
                key = "memories"
            else:
                key = "knowledge"
            sections.setdefault(key, []).append(h)
        return sections

    def refs(self) -> list[dict]:
        return [
            {"type": h.type, "subtype": h.subtype, "id": h.ent_id, "score": h.score}
            for h in self.hits
        ]

    def rules(self) -> list[SearchHit]:
        return [h for h in self.hits if h.type == "memory" and h.subtype == "rule"]

    def summary(self) -> str:
        sec = self.by_section()
        return " ".join(f"{k}={len(v)}" for k, v in sorted(sec.items()) if v) or "empty"


@dataclass
class ContextBlock:
    text: str = ""
    chars: int = 0
    truncated: bool = False
    sections: dict[str, int] = field(default_factory=dict)


def retrieve(store: Store, query: str, *, domain: str = "", limit: int = 12) -> RetrievedSet:
    """Search the store and cap each type's contribution."""
    hits = store.search(query, types=("memory", "skill"), limit=limit)
    capped: list[SearchHit] = []
    used: dict[str, int] = {}
    for h in hits:
        key = h.subtype if h.type == "memory" else "skill"
        cap = PER_TYPE_LIMITS.get(key, 2)
        if used.get(key, 0) >= cap:
            continue
        capped.append(h)
        used[key] = used.get(key, 0) + 1
    return RetrievedSet(hits=capped)


def build_context(retrieved: RetrievedSet, task_intent: str, *, budget: int = DEFAULT_BUDGET) -> ContextBlock:
    """Assemble the bounded SYSTEM CONTEXT block.

    Section order and caps are fixed; items are truncated inside their
    section budget, and the whole block never exceeds ``budget`` chars.
    """
    sections = retrieved.by_section()
    remaining = budget
    parts: list[str] = []
    counts: dict[str, int] = {}
    truncated = False

    for key in ("preferences", "rules", "memories", "skills", "knowledge", "projects"):
        items = sections.get(key, [])
        if not items:
            continue
        section_cap = SECTION_CAPS[key]
        block: list[str] = []
        block.append(f"## {SECTION_LABELS[key]}")
        used = 0
        for h in items:
            line = f"- ({h.ent_id}) {h.content}"
            if used + len(line) > section_cap:
                truncated = True
                break
            block.append(line)
            used += len(line)
        if len(block) == 1:  # nothing fit
            continue
        sec_text = "\n".join(block)
        if remaining - len(sec_text) < 0:
            truncated = True
            break
        parts.append(sec_text)
        remaining -= len(sec_text)
        counts[key] = len(block) - 1

    body = "\n\n".join(parts)
    task_section = f"## 当前任务\n{task_intent}"
    # task section must always fit; hard-truncate the body if needed
    if len(body) + len(task_section) > budget:
        body = body[: budget - len(task_section)]
        truncated = True
    text = body + "\n\n" + task_section

    return ContextBlock(text=text, chars=len(text), truncated=truncated, sections=counts)
