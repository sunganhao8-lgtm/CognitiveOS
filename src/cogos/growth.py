"""Cognitive Growth Engine — the Phase 3A Memory Growth mechanism.

    Execution → Episodic Memory → Pattern Detection → Candidate
    → Evidence Accumulation → Promotion Decision → Preference / Semantic / Rule

Hard rules (user-approved):

1. The PatternDetector is DETERMINISTIC. Observable evidence only.
   The LLM may at most polish the human-readable description of a
   candidate — it NEVER decides promotion.
2. Candidates never enter agent context, never affect retrieval ranking
   or rule selection.
3. Promotion conditions live in one place (:class:`PromotionPolicy`),
   testable and auditable.
4. Confidence is derived from evidence + verification + recency +
   consistency + user confirmation — never from an LLM's self-opinion.
5. Promotion is idempotent: running sleep twice on the same evidence
   yields the same cognition (no duplicates).

``cogos sleep`` is the offline consolidation cycle. It reads history, never
modifies it — promotions are interpretations of the past, expressed as new
nodes with ``derived_from`` / ``promoted_from`` edges.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .store import Store, USER_ID
from .user import UserLayer
from . import trace as trace_mod

# ---------------------------------------------------------------------------
# Promotion policy (single source of truth — user hard rule #3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromotionPolicy:
    """Concentrated, testable promotion conditions.

    Preference / Semantic:
        confidence >= min_confidence AND evidence >= min_evidence
        AND verify_pass >= min_verify_pass
    Rule:
        user_confirmed OR verify_pass >= rule_min_verify_pass
    """

    base_confidence: float = 0.30
    max_confidence: float = 0.99

    min_confidence: float = 0.70
    min_evidence: int = 3
    min_verify_pass: int = 1
    rule_min_verify_pass: int = 3

    # evidence weights (confidence composition — hard rule #4)
    w_user_statement: float = 0.50
    w_applied_verified: float = 0.15
    w_applied_ambiguous: float = 0.05
    w_observation: float = 0.10
    w_verify_fail: float = -0.05

    confirmed_bonus: float = 0.70

    candidate_expire_days: int = 30
    cool_down_hours: int = 24


POLICY = PromotionPolicy()


def compute_confidence(
    *,
    user_statements: int = 0,
    applied_verified: int = 0,
    applied_ambiguous: int = 0,
    observations: int = 0,
    verify_fails: int = 0,
    user_confirmed: bool = False,
    policy: PromotionPolicy = POLICY,
) -> float:
    """Deterministic confidence from evidence composition.

    NEVER fed by an LLM's self-opinion. Every term traces to a countable
    observation (see caller: evidence rows carry execution ids).
    """
    p = policy
    conf = p.base_confidence
    conf += p.w_user_statement * user_statements
    conf += p.w_applied_verified * applied_verified
    conf += p.w_applied_ambiguous * applied_ambiguous
    conf += p.w_observation * observations
    conf += p.w_verify_fail * verify_fails
    if user_confirmed:
        conf += p.confirmed_bonus
    return round(max(0.0, min(conf, p.max_confidence)), 4)


def decide_promotion(
    *,
    target_type: str,  # "preference" | "semantic" | "rule"
    confidence: float,
    evidence_count: int,
    verify_pass_count: int,
    user_confirmed: bool,
    created_at: str,
    policy: PromotionPolicy = POLICY,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Return (decision, reason). decision ∈ {"hold", "promote", "expire"}."""
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        created = now
    age_hours = (now - created).total_seconds() / 3600

    if (now - created).total_seconds() / 86400 > policy.candidate_expire_days:
        return ("expire", f"candidate expired after {policy.candidate_expire_days} days without new evidence")

    if target_type == "rule":
        if user_confirmed:
            return ("promote", "user_confirmed")
        if verify_pass_count >= policy.rule_min_verify_pass and evidence_count >= policy.min_evidence:
            return ("promote", f"verify_pass={verify_pass_count} >= {policy.rule_min_verify_pass}")
        return ("hold", f"rule needs user_confirmed or {policy.rule_min_verify_pass} verify PASS "
                        f"(has {verify_pass_count})")

    if age_hours < policy.cool_down_hours:
        return ("hold", f"cool-down: created {age_hours:.1f}h ago (< {policy.cool_down_hours}h)")

    if confidence >= policy.min_confidence and evidence_count >= policy.min_evidence and verify_pass_count >= policy.min_verify_pass:
        return ("promote", f"confidence={confidence:.2f} evidence={evidence_count} verify_pass={verify_pass_count}")
    return ("hold", f"below threshold: confidence={confidence:.2f}/{policy.min_confidence}, "
                    f"evidence={evidence_count}/{policy.min_evidence}, "
                    f"verify_pass={verify_pass_count}/{policy.min_verify_pass}")


# ---------------------------------------------------------------------------
# Behavioral features (deterministic extraction from agent output)
# ---------------------------------------------------------------------------

#: feature → (target_type, forbidden pattern if rule-like)
FEATURE_REGISTRY: dict[str, dict] = {
    "sql:uses_cte":         {"target": "preference", "label_zh": "反复使用 CTE（WITH）结构"},
    "sql:uses_select_star": {"target": "rule",       "label_zh": "出现 SELECT *", "forbidden": ["SELECT *"]},
    "sql:uses_join":        {"target": "preference", "label_zh": "反复使用 JOIN 关联"},
    "sql:uses_subquery":    {"target": "preference", "label_zh": "反复使用子查询"},
}


def extract_features(domain: str, output: str) -> list[str]:
    """Deterministic behavioral features from an agent output.

    v0: sql-domain code patterns only. Never an LLM — patterns must be
    checkable by inspection of the output text.
    """
    features: list[str] = []
    if not output:
        return features
    if domain != "sql":
        return features
    # only inspect fenced code blocks — explanation text is not behavior
    blocks = re.findall(r"```[a-zA-Z]*\s*\n(.*?)```", output, re.DOTALL)
    code = "\n".join(blocks) if blocks else output
    if re.search(r"\bWITH\b", code, re.IGNORECASE):
        features.append("sql:uses_cte")
    if re.search(r"\bSELECT\s+\*", code, re.IGNORECASE):
        features.append("sql:uses_select_star")
    if re.search(r"\bJOIN\b", code, re.IGNORECASE):
        features.append("sql:uses_join")
    if re.search(r"\(\s*SELECT\b", code, re.IGNORECASE):
        features.append("sql:uses_subquery")
    return features


def feature_slug(feature: str) -> str:
    return feature.replace(":", "-")


# ---------------------------------------------------------------------------
# Pattern detection (deterministic aggregation over episodic memory)
# ---------------------------------------------------------------------------


@dataclass
class SleepReport:
    sleep_id: str = ""
    patterns_detected: int = 0
    candidates_created: int = 0
    candidates_updated: int = 0
    promotions_evaluated: int = 0
    memories_promoted: list[str] = field(default_factory=list)
    rule_evidence_updated: int = 0

    def to_dict(self) -> dict:
        return {
            "sleep_id": self.sleep_id,
            "patterns_detected": self.patterns_detected,
            "candidates_created": self.candidates_created,
            "candidates_updated": self.candidates_updated,
            "promotions_evaluated": self.promotions_evaluated,
            "memories_promoted": self.memories_promoted,
            "rule_evidence_updated": self.rule_evidence_updated,
        }


def _read_jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _upsert_jsonl(path: Path, rec_id: str, rec: dict) -> None:
    """Idempotent row upsert in a canonical JSONL file (atomic write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl_lines(path)
    rows = [r for r in rows if r.get("id") != rec_id]
    rows.append(rec)
    rows.sort(key=lambda r: r.get("created_at", ""))
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_sleep(
    user: UserLayer,
    store: Store,
    *,
    llm_fn=None,
    policy: PromotionPolicy = POLICY,
    now: datetime | None = None,
) -> SleepReport:
    """One offline cognitive-consolidation cycle (idempotent)."""
    now = now or datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    sleep_id = trace_mod.new_run_id(store, prefix="slp")

    report = SleepReport(sleep_id=sleep_id)

    trace_mod.append_event(user, store, sleep_id, "sleep_started", detail="consolidation cycle")

    # ---- 1. read history (never modified) ---------------------------------
    episodic = _read_jsonl_lines(user.memory / "episodic.jsonl")
    rules_dir = user.root / "rules"
    candidates = _read_jsonl_lines(user.memory / "candidates.jsonl")
    cand_by_id = {c["id"]: c for c in candidates}
    preferences = _read_jsonl_lines(user.memory / "preferences.jsonl")

    # ---- 2. rule evidence accumulation (rules the user already declared) --
    rule_evidence_updated = 0
    if rules_dir.exists():
        for rule_path in sorted(rules_dir.glob("R-*.json")):
            try:
                rule = json.loads(rule_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rid = rule.get("id") or rule_path.stem
            applied = [e for e in episodic if rid in (e.get("refs") or [])]
            if not applied:
                continue
            passes = [e for e in applied if e.get("verdict") == "PASS"]
            last_ts = max((e.get("created_at", "") for e in applied), default="")
            rule["evidence_count"] = len(applied)
            rule["verify_pass_count"] = len(passes)
            rule["last_observed"] = last_ts
            rule["source_executions"] = [e.get("derived_from_execution", "") for e in applied if e.get("derived_from_execution")]
            rule["status"] = rule.get("status", "confirmed")
            rule["confidence"] = compute_confidence(
                user_statements=1 if rule.get("source") == "user_statement" else 0,
                applied_verified=len(passes),
                applied_ambiguous=sum(1 for e in applied if e.get("verdict") == "AMBIGUOUS"),
                verify_fails=sum(1 for e in applied if e.get("verdict") == "FAIL"),
                user_confirmed=bool(rule.get("user_confirmed")),
                policy=policy,
            )
            rule_path.write_text(json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8")
            store.upsert_entity(
                rid, "memory", subtype="rule", domain=rule.get("domain", "general"),
                content=" ".join(str(rule.get(k, "")) for k in ("rule_zh", "rule_en", "probe_zh", "probe_en")).strip(),
                payload=rule, created_at=rule.get("created_at"),
                status=rule["status"], confidence=rule["confidence"],
                evidence_count=rule["evidence_count"], last_observed=rule["last_observed"],
                verify_pass_count=rule["verify_pass_count"],
                user_confirmed=bool(rule.get("user_confirmed")),
            )
            rule_evidence_updated += 1

    # ---- 3. feature aggregation → candidates ------------------------------
    feature_groups: dict[tuple[str, str], list[dict]] = {}
    for e in episodic:
        for feat in e.get("features", []):
            feature_groups.setdefault((e.get("domain", "general"), feat), []).append(e)

    patterns_detected = len(feature_groups)
    report.patterns_detected = patterns_detected

    for (domain, feature), evs in feature_groups.items():
        registry = FEATURE_REGISTRY.get(feature)
        if registry is None:
            continue
        # dedupe by execution — repeated behavior in ONE execution is one evidence
        execs: dict[str, dict] = {}
        for e in evs:
            exid = e.get("derived_from_execution") or e.get("id") or ""
            if exid and exid not in execs:
                execs[exid] = e
        deduped = list(execs.values())
        if not deduped:
            continue

        cand_id = f"cand-{domain}-{feature_slug(feature)}"
        passes = [e for e in deduped if e.get("verdict") == "PASS"]
        evidence_count = len(deduped)
        verify_pass_count = len(passes)
        last_ts = max((e.get("created_at", "") for e in deduped), default=ts)

        conf = compute_confidence(
            observations=evidence_count,
            applied_verified=verify_pass_count,
            applied_ambiguous=sum(1 for e in deduped if e.get("verdict") == "AMBIGUOUS"),
            verify_fails=sum(1 for e in deduped if e.get("verdict") == "FAIL"),
            policy=policy,
        )

        existing = cand_by_id.get(cand_id)
        # Idempotency: a candidate that was already promoted (or retired)
        # is NOT re-evaluated — evidence keeps accumulating in the episodic
        # store, but the promotion happened once.
        if existing and existing.get("status") in ("confirmed", "superseded"):
            store.upsert_entity(
                cand_id, "memory", subtype="candidate", domain=domain,
                content=existing.get("content", ""), payload=existing,
                status=existing.get("status", "candidate"),
                confidence=existing.get("confidence"),
                evidence_count=existing.get("evidence_count", 0),
                last_observed=existing.get("last_observed", ""),
                verify_pass_count=existing.get("verify_pass_count", 0),
            )
            continue

        # candidate's creation time = its FIRST evidence (cool-down counts from
        # the first observation, not from the first sleep that saw it)
        created_at = (existing or {}).get("created_at") or min(
            (e.get("created_at", "") for e in deduped if e.get("created_at")),
            default=ts,
        )
        cand = {
            "id": cand_id,
            "type": "candidate",
            "target_type": registry["target"],
            "domain": domain,
            "feature": feature,
            "content": (
                f"在 {domain} 域中观察到行为特征 {registry['label_zh']}"
                f"（{evidence_count} 次独立执行）"
            ),
            "status": "candidate",
            "confidence": conf,
            "evidence_count": evidence_count,
            "verify_pass_count": verify_pass_count,
            "last_observed": last_ts,
            "source_memories": [e.get("id", "") for e in deduped if e.get("id")],
            "source_executions": [e.get("derived_from_execution", "") for e in deduped if e.get("derived_from_execution")],
            "user_confirmed": False,
            "version": (existing or {}).get("version", 0) + 1,
            "created_at": created_at,
            "updated_at": ts,
        }
        _upsert_jsonl(user.memory / "candidates.jsonl", cand_id, cand)
        if existing:
            report.candidates_updated += 1
        else:
            report.candidates_created += 1

        store.upsert_entity(
            cand_id, "memory", subtype="candidate", domain=domain,
            content=cand["content"], payload=cand,
            created_at=cand["created_at"], updated_at=cand["updated_at"],
            status="candidate", confidence=conf, evidence_count=evidence_count,
            last_observed=last_ts, verify_pass_count=verify_pass_count,
            user_confirmed=False,
        )
        for m in cand["source_memories"]:
            store.add_edge(cand_id, "derived_from", m)
        store.add_edge(USER_ID, "owns", cand_id)
        store.add_fts(cand_id, "memory", "candidate", domain, cand["content"])

        # ---- 4. promotion decision -----------------------------------------
        decision, reason = decide_promotion(
            target_type=registry["target"],
            confidence=conf,
            evidence_count=evidence_count,
            verify_pass_count=verify_pass_count,
            user_confirmed=False,
            created_at=cand["created_at"],
            policy=policy,
            now=now,
        )
        report.promotions_evaluated += 1
        trace_mod.append_event(
            user, store, sleep_id, "promotions_evaluated",
            detail=f"{cand_id} decision={decision} reason={reason}",
            refs=[{"type": "memory", "subtype": "candidate", "id": cand_id}],
        )
        if decision == "expire":
            cand["status"] = "superseded"
            cand["superseded_reason"] = "expired"
            _upsert_jsonl(user.memory / "candidates.jsonl", cand_id, cand)
            store.upsert_entity(
                cand_id, "memory", subtype="candidate", domain=domain,
                content=cand["content"], payload=cand,
                status="superseded", confidence=conf,
                evidence_count=evidence_count, last_observed=last_ts,
                verify_pass_count=verify_pass_count,
            )
            continue
        if decision == "promote":
            promoted = _promote_candidate(
                user, store, cand, llm_fn=llm_fn, sleep_id=sleep_id, policy=policy,
            )
            if promoted:
                report.memories_promoted.append(promoted)
                cand["status"] = "confirmed"
                cand["promoted_to"] = promoted
                _upsert_jsonl(user.memory / "candidates.jsonl", cand_id, cand)
                store.upsert_entity(
                    cand_id, "memory", subtype="candidate", domain=domain,
                    content=cand["content"], payload=cand,
                    status="confirmed", confidence=conf,
                    evidence_count=evidence_count, last_observed=last_ts,
                    verify_pass_count=verify_pass_count,
                )

    trace_mod.append_event(
        user, store, sleep_id, "patterns_detected",
        detail=f"feature_groups={patterns_detected}",
    )
    trace_mod.append_event(
        user, store, sleep_id, "candidates_created",
        detail=f"created={report.candidates_created}",
    )
    trace_mod.append_event(
        user, store, sleep_id, "candidates_updated",
        detail=f"updated={report.candidates_updated}",
    )
    trace_mod.append_event(
        user, store, sleep_id, "memories_promoted",
        detail=",".join(report.memories_promoted) or "(none)",
    )
    trace_mod.append_event(
        user, store, sleep_id, "sleep_completed",
        detail=f"rules_evidence_updated={rule_evidence_updated}",
    )

    # sleep is itself a traceable execution (dashboard shows when we learned)
    trace_mod.append_execution(
        user, store,
        {
            "execution_id": sleep_id,
            "task": "cogos sleep — 离线认知整理周期",
            "intent_type": "sleep",
            "agent_id": "cogos-sleep",
            "status": "success",
            "verdict": "",
            "context_chars": 0,
            "started_at": ts,
            "finished_at": ts,
            "refs": [{"type": "memory", "subtype": "candidate", "id": c} for c in cand_by_id],
            "memory_written": list(report.memories_promoted),
            "retrieved_summary": "",
        },
    )
    report.rule_evidence_updated = rule_evidence_updated
    return report


def _promote_candidate(
    user: UserLayer,
    store: Store,
    cand: dict,
    *,
    llm_fn=None,
    sleep_id: str,
    policy: PromotionPolicy,
) -> str | None:
    """Promote a candidate to a confirmed long-term memory (idempotent).

    preference/semantic → user/memory/preferences.jsonl
    rule               → user/rules/R-<DOMAIN>-NNN.json (forbidden pattern
                         from the deterministic FEATURE_REGISTRY)
    """
    target = cand.get("target_type", "preference")
    domain = cand.get("domain", "general")

    if target == "rule":
        from .classify import next_rule_id

        rid = next_rule_id(user.root / "rules", domain)
        feature = cand.get("feature", "")
        forbidden = list(FEATURE_REGISTRY.get(feature, {}).get("forbidden", []))
        rule = {
            "id": rid,
            "domain": domain,
            "rule_zh": cand["content"],
            "rule_en": "",
            "probe_zh": "",
            "probe_en": "",
            "expectation_zh": "",
            "expectation_en": "",
            "forbidden": forbidden,
            "required": [],
            "source": "sleep_promotion",
            "promoted_from": cand["id"],
            "source_executions": cand.get("source_executions", []),
            "status": "confirmed",
            "confidence": cand.get("confidence"),
            "evidence_count": cand.get("evidence_count", 0),
            "verify_pass_count": cand.get("verify_pass_count", 0),
            "last_observed": cand.get("last_observed", ""),
            "user_confirmed": False,
            "version": 1,
            "created_at": _now(),
        }
        (user.root / "rules").mkdir(parents=True, exist_ok=True)
        (user.root / "rules" / f"{rid}.json").write_text(
            json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fts_text = " ".join(str(rule.get(k, "")) for k in ("rule_zh", "rule_en", "probe_zh", "probe_en")).strip()
        store.upsert_entity(
            rid, "memory", subtype="rule", domain=domain, content=fts_text,
            payload=rule, created_at=rule["created_at"],
            status="confirmed", confidence=rule["confidence"],
            evidence_count=rule["evidence_count"],
            last_observed=rule["last_observed"],
            verify_pass_count=rule["verify_pass_count"],
            user_confirmed=False,
        )
        store.add_edge(rid, "promoted_from", cand["id"])
        store.add_edge(USER_ID, "owns", rid)
        store.add_fts(rid, "memory", "rule", domain, fts_text)
        trace_mod.append_event(
            user, store, sleep_id, "memories_promoted",
            detail=f"rule {rid} promoted from {cand['id']}",
            refs=[{"type": "memory", "subtype": "rule", "id": rid}],
        )
        return rid

    # preference / semantic
    from .classify import DOMAIN_SHORT

    dom_short = DOMAIN_SHORT.get(domain.lower(), domain.upper()[:6] or "GEN")
    n = 1
    for p in _read_jsonl_lines(user.memory / "preferences.jsonl"):
        if p.get("id", "").startswith(f"P-{dom_short}-"):
            try:
                n = max(n, int(p["id"].rsplit("-", 1)[1]) + 1)
            except (ValueError, IndexError):
                pass
    pid = f"P-{dom_short}-{n:03d}"
    pref = {
        "id": pid,
        "type": "preference",
        "domain": domain,
        "content": cand["content"],
        "source": "sleep_promotion",
        "promoted_from": cand["id"],
        "source_executions": cand.get("source_executions", []),
        "status": "confirmed",
        "confidence": cand.get("confidence"),
        "evidence_count": cand.get("evidence_count", 0),
        "verify_pass_count": cand.get("verify_pass_count", 0),
        "last_observed": cand.get("last_observed", ""),
        "user_confirmed": False,
        "version": 1,
        "created_at": _now(),
    }
    _upsert_jsonl(user.memory / "preferences.jsonl", pid, pref)
    store.upsert_entity(
        pid, "memory", subtype="preference", domain=domain,
        content=pref["content"], payload=pref, created_at=pref["created_at"],
        status="confirmed", confidence=pref["confidence"],
        evidence_count=pref["evidence_count"],
        last_observed=pref["last_observed"],
        verify_pass_count=pref["verify_pass_count"],
        user_confirmed=False,
    )
    store.add_edge(pid, "promoted_from", cand["id"])
    for m in cand.get("source_memories", []):
        store.add_edge(pid, "derived_from", m)
    store.add_edge(USER_ID, "owns", pid)
    store.add_fts(pid, "memory", "preference", domain, pref["content"])
    trace_mod.append_event(
        user, store, sleep_id, "memories_promoted",
        detail=f"preference {pid} promoted from {cand['id']}",
        refs=[{"type": "memory", "subtype": "preference", "id": pid}],
    )
    return pid
