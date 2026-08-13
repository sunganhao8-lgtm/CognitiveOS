"""Conflict detection & resolution — Phase 3B.

CognitiveOS must distinguish THREE concepts (user hard rule §10):

* **supersede**  — cognition EVOLVED (explicit user statement or a newer
  confirmed version replaces an old one; history kept)
* **exception**   — task-scoped temporary override; long-term cognition is
  untouched and comes back when the task ends
* **conflict**    — two confirmed cognitions contradict each other and no
  policy tier can pick a winner → status=conflicted, surfaced to the user

Hard rules:

* NEVER delete cognition history (supersede keeps the old entity).
* The LLM may at most judge "are these two semantically conflicting?"
  — it NEVER decides the winner.
* The winner is decided ONLY by scope / explicit-statement / confirmation /
  version / confidence tiers.
* Unresolved conflicts are shown, not silently resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .store import Store

#: scope precedence: a narrower scope always overrides a broader one.
#: (temporary/task > project > global). Time NEVER outranks scope (§5).
SCOPE_RANK = {
    "temporary": 4,
    "task": 3,
    "project": 2,
    "global": 1,
}

#: source precedence: an explicit user statement outranks behavior-derived
#: cognition (§12). sleep_promotion (behavior evidence) must never
#: overwrite a user statement.
SOURCE_RANK = {
    "user_statement": 4,
    "manual": 3,
    "user_confirmed": 3,
    "sleep_promotion": 1,
    "execution": 0,
    "": 0,
}


@dataclass
class Conflict:
    """A detected contradiction between two confirmed cognitions."""
    a_id: str
    b_id: str
    kind: str  # "rule_rule" | "preference_semantic"
    detail: str
    resolved: bool = False
    winner: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "a_id": self.a_id,
            "b_id": self.b_id,
            "kind": self.kind,
            "detail": self.detail,
            "resolved": self.resolved,
            "winner": self.winner,
            "reason": self.reason,
        }


def _patterns(payload: dict) -> tuple[set, set]:
    return (
        {str(x) for x in payload.get("forbidden", ())},
        {str(x) for x in payload.get("required", ())},
    )


def rule_rule_conflict(a: dict, b: dict) -> bool:
    """Deterministic: A forbids what B requires (or vice versa)."""
    a_forb, a_req = _patterns(a.get("payload") or {})
    b_forb, b_req = _patterns(b.get("payload") or {})
    return bool((a_forb & b_req) or (a_req & b_forb))


def detect_conflicts(
    store: Store,
    domain: str | None = None,
    *,
    llm_fn=None,
) -> list[Conflict]:
    """Find conflicts among CURRENT confirmed long-term cognitions.

    Rule-vs-rule contradictions are caught deterministically (pattern
    intersection). Preference-vs-preference semantic contradictions are
    flagged only when an LLM judge confirms them — and that judge only
    answers "conflict or not", never "who wins".
    """
    out: list[Conflict] = []
    rows = store._conn.execute(
        "SELECT * FROM entities WHERE type='memory' AND status='confirmed'"
        + (" AND domain=?" if domain else "")
        + " ORDER BY created_at",
        ((domain,) if domain else ()),
    ).fetchall()
    ents = []
    import json as _json

    for r in rows:
        d = dict(r)
        try:
            d["payload"] = _json.loads(d["payload"] or "{}")
        except _json.JSONDecodeError:
            d["payload"] = {}
        ents.append(d)

    for i, a in enumerate(ents):
        for b in ents[i + 1 :]:
            if a["subtype"] == "rule" and b["subtype"] == "rule":
                if rule_rule_conflict(a, b):
                    out.append(Conflict(
                        a_id=a["id"], b_id=b["id"], kind="rule_rule",
                        detail=f"forbidden/required patterns contradict",
                    ))
            elif {a["subtype"], b["subtype"]} <= {"preference", "semantic"}:
                if llm_fn is not None and _semantic_conflict(a, b, llm_fn):
                    out.append(Conflict(
                        a_id=a["id"], b_id=b["id"], kind="preference_semantic",
                        detail="semantic judge flagged contradiction",
                    ))
    return out


def _semantic_conflict(a: dict, b: dict, llm_fn) -> bool:
    """LLM answers ONE question: do these two cognitions contradict?
    (Not who wins — the policy decides that.)"""
    try:
        raw = llm_fn(
            "Two user cognitions (preferences or rules). Reply with ONLY JSON: "
            '{"conflict": true or false}\n\n'
            f"A: {a.get('content', '')[:400]}\n\nB: {b.get('content', '')[:400]}\n\n"
            "conflict=true only if A and B directly contradict each other "
            "(evolution/refinement is NOT a conflict)."
        )
        if raw:
            import re
            m = re.search(r"\{[^{}]*\"conflict\"[^{}]*\}", raw)
            if m:
                import json as _json
                return bool(_json.loads(m.group(0)).get("conflict", False))
    except Exception:
        pass
    return False


@dataclass(frozen=True)
class ResolutionPolicy:
    """Central, testable winner-selection tiers (in order)."""

    #: tier order is the policy itself — never "newer wins" alone
    tiers: tuple[str, ...] = (
        "temporary",          # task-scoped override bound to current execution
        "scope",              # narrower scope outranks broader (never time)
        "explicit_statement",  # user_statement beats behavior evidence
        "user_confirmed",     # human-confirmed beats unconfirmed
        "newer_version",      # same scope+source: newer confirmed wins
        "higher_confidence",  # same scope+source+age: stronger evidence wins
    )


POLICY = ResolutionPolicy()


def resolve_conflict(store: Store, conflict: Conflict, *, policy: ResolutionPolicy = POLICY) -> Conflict:
    """Pick a winner using ONLY the policy tiers. Unresolvable → conflicted."""
    a = store.entity(conflict.a_id)
    b = store.entity(conflict.b_id)
    if a is None or b is None:
        return conflict

    def winner_by_tier() -> tuple[str, str]:
        # temporary: an ACTIVE temporary bound to nothing wins for its task
        a_temp = a["subtype"] == "temporary" and a["status"] == "temporary"
        b_temp = b["subtype"] == "temporary" and b["status"] == "temporary"
        if a_temp != b_temp:
            return (a["id"], "temporary override") if a_temp else (b["id"], "temporary override")

        ra, rb = SCOPE_RANK.get(a["scope"], 1), SCOPE_RANK.get(b["scope"], 1)
        if ra != rb:
            return (a["id"], f"scope {a['scope']} outranks {b['scope']}") if ra > rb else (
                b["id"], f"scope {b['scope']} outranks {a['scope']}")

        sa = SOURCE_RANK.get(str((a["payload"] or {}).get("source", "")), 0)
        sb = SOURCE_RANK.get(str((b["payload"] or {}).get("source", "")), 0)
        if sa != sb:
            return (a["id"], "explicit user statement outranks behavior evidence") if sa > sb else (
                b["id"], "explicit user statement outranks behavior evidence")

        if bool(a["user_confirmed"]) != bool(b["user_confirmed"]):
            return (a["id"], "user-confirmed outranks unconfirmed") if a["user_confirmed"] else (
                b["id"], "user-confirmed outranks unconfirmed")

        ca, cb = a["created_at"] or "", b["created_at"] or ""
        if ca != cb:
            return (a["id"], "newer confirmed version") if ca > cb else (b["id"], "newer confirmed version")

        fa, fb = a["confidence"] or 0.0, b["confidence"] or 0.0
        if fa != fb:
            return (a["id"], "higher confidence") if fa > fb else (b["id"], "higher confidence")

        return ("", "no policy tier can decide")

    winner, reason = winner_by_tier()
    if winner:
        conflict.resolved = True
        conflict.winner = winner
        conflict.reason = reason
        loser = conflict.b_id if winner == conflict.a_id else conflict.a_id
        store._conn.execute(
            "UPDATE entities SET status='conflicted' WHERE id=?", (loser,)
        )
        store._conn.commit()
    return conflict
