"""Retrieval + context building — the Retrieve and Apply steps.

Retriever: FTS5 (trigram) search over the Cognitive Store with per-type
caps, domain match and recency boost. NO embeddings in v0 — the interface
keeps room for them later.

ContextBuilder: assembles the retrieved items into a bounded SYSTEM CONTEXT
block. Hard budget (default 4000 chars); per-section caps; truncation is
recorded so the trace can report it. NEVER dumps all memory into a prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .store import SearchHit, Store

DEFAULT_BUDGET = 4000
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
