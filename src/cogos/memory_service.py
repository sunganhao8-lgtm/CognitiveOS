"""MemoryService — the single control surface for cognitive state (Phase 3E).

User owns the cognitive state. Every action goes through this service:

    validate → apply → persist (canonical + index) → trace (user_corrected) → verify

CLI, future Dashboard and future local APIs all consume THIS service — they
never touch SQLite or canonical files directly.

Canonical persistence is mandatory: corrections written to `user/**` files
survive `delete cognitive.db → cogos reindex` (§24/§25).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import Paths
from .store import Store, USER_ID
from .user import UserLayer
from . import trace as trace_mod

from .growth import _read_jsonl_lines, _upsert_jsonl, FEATURE_REGISTRY

#: statuses each action produces — semantic clarity per contract §7
#: reject = "your inference is wrong" (candidate-level denial)
#: forget = "stop using this cognition from now on" (no longer relevant)
ACTION_STATUSES = ("confirmed", "superseded", "rejected", "suppressed", "expired")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryService:
    def __init__(self, paths: Paths, store: Store | None = None) -> None:
        self.paths = paths
        self.user = UserLayer(root=paths.root / "user")
        self.user.ensure()
        self._owns_store = store is None
        self.store = store or Store(paths.cache / "cognitive.db")

    def close(self) -> None:
        if self._owns_store:
            try:
                self.store.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ core

    def _action_id(self) -> str:
        """A user action is itself a traceable event chain (usr-…)."""
        return trace_mod.new_run_id(self.store, prefix="usr")

    def _trace(self, exec_id: str, *, action: str, memory_id: str,
               old_status: str, new_status: str, reason: str,
               old_version: int | None = None, new_version: int | None = None,
               target: str = "") -> None:
        """One auditable user_corrected event (canonical trace + index)."""
        detail = {
            "action": action,
            "memory": memory_id,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
            "source": "user",
        }
        if old_version is not None:
            detail["old_version"] = old_version
        if new_version is not None:
            detail["new_version"] = new_version
        if target:
            detail["target"] = target
        trace_mod.append_event(
            self.user, self.store, exec_id, "user_corrected",
            detail=json.dumps(detail, ensure_ascii=False),
            refs=[{"type": "memory", "subtype": "correction", "id": memory_id}],
        )

    def _canonical_target(self, ent: dict) -> tuple[Path, str]:
        """(canonical file, kind) for an entity — never None for memory types."""
        sub = ent.get("subtype", "")
        if sub == "rule":
            return self.user.root / "rules" / f"{ent['id']}.json", "rule"
        if sub == "candidate":
            return self.user.memory / "candidates.jsonl", "jsonl"
        if sub in ("temporary",):
            return self.user.memory / "temporary.jsonl", "jsonl"
        return self.user.memory / "preferences.jsonl", "jsonl"

    def _write_canonical(self, kind: str, path: Path, rec: dict) -> None:
        if kind == "rule":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            _upsert_jsonl(path, rec["id"], rec)

    def _update_entity(self, ent_id: str, **fields) -> dict:
        """Apply fields to the store entity AND the canonical record.

        ``payload`` (if given) is MERGED into the existing payload — never
        assigned wholesale (avoids self-reference and data loss).
        """
        ent = self.store.entity(ent_id)
        if ent is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        new_payload = fields.pop("payload", None)
        if new_payload is not None:
            ent["payload"] = {**(ent.get("payload") or {}), **new_payload}
        ent.update(fields)
        ent["updated_at"] = _now()
        # canonical file
        path, kind = self._canonical_target(ent)
        if path.exists():
            rec = {}
            if kind == "rule":
                try:
                    rec = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    rec = {}
            else:
                for row in _read_jsonl_lines(path):
                    if row.get("id") == ent_id:
                        rec = row
                        break
            rec.update(ent.get("payload") or {})
            for k in ("status", "user_confirmed", "confidence", "updated_at"):
                if k in ent:
                    rec[k] = ent[k]
            rec["updated_at"] = _now()
            self._write_canonical(kind, path, rec)
        # store
        payload = ent.get("payload") or {}
        self.store.upsert_entity(
            ent_id, ent["type"], subtype=ent.get("subtype", ""),
            domain=ent.get("domain", ""), content=ent.get("content", ""),
            payload=payload,
            created_at=ent.get("created_at"), updated_at=_now(),
            status=ent.get("status", ""), confidence=ent.get("confidence"),
            evidence_count=ent.get("evidence_count", 0),
            last_observed=ent.get("last_observed", ""),
            verify_pass_count=ent.get("verify_pass_count", 0),
            user_confirmed=bool(ent.get("user_confirmed")),
            scope=ent.get("scope", "global"), scope_id=ent.get("scope_id", ""),
            version=ent.get("version", 1),
            superseded_at=ent.get("superseded_at", ""),
            superseded_by=ent.get("superseded_by", ""),
            superseded_reason=ent.get("superseded_reason", ""),
        )
        return ent

    # ------------------------------------------------------------------ list

    def list(self, *, status: str | None = None, limit: int = 50) -> list[dict]:
        """All current cognitions (default: every status except superseded)."""
        rows = self.store._conn.execute(
            "SELECT id, subtype, domain, status, confidence, evidence_count, "
            "scope, version, created_at, content FROM entities "
            "WHERE type='memory'"
            + (" AND status=?" if status else " AND status NOT IN ('superseded','expired')")
            + " ORDER BY created_at DESC LIMIT ?",
            ((status,) if status else ()) + (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ show

    def show(self, ent_id: str) -> dict:
        """Full state of one cognition — current + version history."""
        chain = self.store.version_chain(ent_id)
        if not chain:
            raise KeyError(f"no memory with id {ent_id!r}")
        cur = chain[-1]
        return {
            "id": ent_id,
            "domain": cur["domain"],
            "subtype": cur["subtype"],
            "scope": cur["scope"],
            "scope_id": cur["scope_id"],
            "status": cur["status"],
            "current_content": cur["content"],
            "confidence": cur["confidence"],
            "evidence_count": cur["evidence_count"],
            "verify_pass_count": cur["verify_pass_count"],
            "user_confirmed": bool(cur["user_confirmed"]),
            "version_history": [
                {
                    "id": e["id"],
                    "version": e["version"],
                    "status": e["status"],
                    "content": e["content"][:200],
                    "confidence": e["confidence"],
                    "created_at": e["created_at"],
                    "superseded_at": e["superseded_at"],
                    "superseded_by": e["superseded_by"],
                    "superseded_reason": e["superseded_reason"],
                }
                for e in chain
            ],
        }

    # ------------------------------------------------------------------ why

    def why(self, ent_id: str) -> dict:
        """Evidence-based explanation of the CURRENT belief (§10).

        NEVER chain-of-thought — only verifiable system events.
        """
        cur = self.store.entity(ent_id)
        if cur is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        payload = cur.get("payload") or {}
        chain = self.store.version_chain(ent_id)
        # user corrections touching this cognition (walk the whole chain)
        corrections: list[dict] = []
        chain_ids = {e["id"] for e in chain} | {ent_id}
        for row in self.store._conn.execute(
            "SELECT detail, ts FROM trace_events WHERE step='user_corrected' ORDER BY id"
        ):
            try:
                d = json.loads(row["detail"])
            except json.JSONDecodeError:
                continue
            if d.get("memory") in chain_ids or d.get("target") in chain_ids:
                corrections.append({**d, "ts": row["ts"]})
        return {
            "id": ent_id,
            "belief": cur["content"],
            "confidence": cur["confidence"],
            "evidence_count": cur["evidence_count"],
            "verify_pass_count": cur["verify_pass_count"],
            "source_executions": payload.get("source_executions", []),
            "created_at": cur["created_at"],
            "last_observed": cur["last_observed"],
            "version": cur["version"],
            "scope": cur["scope"],
            "scope_id": cur["scope_id"],
            "status": cur["status"],
            "user_confirmed": bool(cur["user_confirmed"]),
            "superseded_history": [
                {"id": e["id"], "status": e["status"], "superseded_by": e["superseded_by"],
                 "superseded_reason": e["superseded_reason"]}
                for e in chain[:-1]
            ],
            "user_corrections": corrections,
        }

    # ------------------------------------------------------------------ card

    def card(self, ent_id: str) -> dict:
        """Dashboard ViewModel (§23) — UI consumes only this shape."""
        cur = self.store.entity(ent_id)
        if cur is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        actions: list[str] = []
        if cur["subtype"] == "candidate":
            actions = ["confirm", "reject"]
        elif cur["status"] in ("confirmed",):
            actions = ["modify", "forget", "reject"]
        return {
            "id": ent_id,
            "content": cur["content"],
            "confidence": cur["confidence"],
            "evidence_count": cur["evidence_count"],
            "status": cur["status"],
            "scope": cur["scope"],
            "version": cur["version"],
            "actions": actions,
        }

    # ------------------------------------------------------------------ confirm

    def confirm(self, ent_id: str, *, reason: str = "user confirmation") -> dict:
        """Candidate → confirmed long-term cognition (never loses evidence).

        The candidate stays subtype=candidate (permanently excluded from
        retrieval, 3A hard rule) — a NEW preference/rule entity is created
        and promoted_from the candidate, exactly like a user-blessed sleep
        promotion.
        """
        ent = self.store.entity(ent_id)
        if ent is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        if ent.get("subtype") != "candidate":
            raise ValueError(f"{ent_id} is not a candidate — use modify/forget/reject")
        if ent.get("status") in ("rejected", "suppressed", "superseded"):
            raise ValueError(f"{ent_id} is {ent['status']}; cannot confirm")

        cand = ent
        cand_payload = cand.get("payload") or {}
        from .growth import _promote_candidate

        action_id = self._action_id()
        promoted = _promote_candidate(
            self.user, self.store, cand_payload, llm_fn=None,
            sleep_id=action_id, policy=None, user_confirmed=True,
        )
        # candidate record: confirmed + user_confirmed (evidence untouched)
        self._update_entity(ent_id, status="confirmed", user_confirmed=True,
                            confidence=cand.get("confidence"),
                            payload={**cand_payload, "user_confirmed": True,
                                     "promoted_to": promoted, "confirmed_by": "user"})
        self._trace(action_id, action="confirm", memory_id=ent_id,
                    old_status="candidate", new_status="confirmed",
                    reason=reason, target=promoted)
        return {"confirmed": promoted, "from": ent_id, "status": "confirmed"}

    # ------------------------------------------------------------------ reject

    def reject(self, ent_id: str, *, reason: str = "user rejection") -> dict:
        """"Your inference is wrong" — status=rejected, history kept.

        For candidates a rejection fingerprint is recorded so sleep won't
        immediately resurrect the same pattern (§20) — unless new explicit
        user evidence arrives later (§21).
        """
        ent = self.store.entity(ent_id)
        if ent is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        old_status = ent.get("status") or ""
        self._update_entity(ent_id, status="rejected",
                            payload={**(ent.get("payload") or {}),
                                     "rejected_reason": reason})
        action_id = self._action_id()
        self._trace(action_id, action="reject", memory_id=ent_id,
                    old_status=old_status, new_status="rejected", reason=reason)
        # fingerprint so the same pattern cannot immediately resurface
        if ent.get("subtype") == "candidate":
            p = ent.get("payload") or {}
            fp = {
                "id": f"rej-{ent_id}",
                "fingerprint": p.get("feature", ""),
                "domain": p.get("domain", ""),
                "feature": p.get("feature", ""),
                "memory_id": ent_id,
                # microsecond precision: a statement and a rejection can
                # land in the same second — the revival check must be able
                # to tell which came first
                "rejected_at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            }
            _upsert_jsonl(self.user.memory / "rejections.jsonl", fp["id"], fp)
        return {"id": ent_id, "status": "rejected"}

    # ------------------------------------------------------------------ forget

    def forget(self, ent_id: str, *, reason: str = "no longer relevant") -> dict:
        """"Stop using this from now on" — status=suppressed, never deleted."""
        ent = self.store.entity(ent_id)
        if ent is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        if ent.get("status") not in ("confirmed", "conflicted"):
            raise ValueError(f"{ent_id} is {ent.get('status')}; forget applies to confirmed cognitions")
        old_status = ent.get("status")
        self._update_entity(ent_id, status="suppressed",
                            payload={**(ent.get("payload") or {}),
                                     "suppressed_reason": reason})
        action_id = self._action_id()
        self._trace(action_id, action="forget", memory_id=ent_id,
                    old_status=old_status, new_status="suppressed", reason=reason)
        return {"id": ent_id, "status": "suppressed"}

    # ------------------------------------------------------------------ modify

    def modify(self, ent_id: str, content: str, *, reason: str = "user explicit modification") -> dict:
        """Correction WITHOUT overwrite: a new version supersedes the old one.

        Old: status=superseded (confidence/evidence/source_executions kept).
        New: version+1, status=confirmed, user_confirmed=true, source=user_modification.
        """
        ent = self.store.entity(ent_id)
        if ent is None:
            raise KeyError(f"no memory with id {ent_id!r}")
        if ent.get("subtype") not in ("preference", "rule", "semantic"):
            raise ValueError(f"{ent_id} is {ent.get('subtype')}; modify applies to long-term cognitions")
        if ent.get("status") != "confirmed":
            raise ValueError(f"{ent_id} is {ent.get('status')}; only confirmed cognitions can be modified")

        domain = ent.get("domain", "general")
        old_version = ent.get("version", 1)
        payload = ent.get("payload") or {}
        action_id = self._action_id()

        if ent.get("subtype") == "rule":
            from .classify import next_rule_id

            new_id = next_rule_id(self.user.root / "rules", domain)
            new_rec = {
                "id": new_id,
                "domain": domain,
                "rule_zh": content,
                "rule_en": payload.get("rule_en", ""),
                "probe_zh": payload.get("probe_zh", ""),
                "probe_en": payload.get("probe_en", ""),
                "expectation_zh": payload.get("expectation_zh", ""),
                "expectation_en": payload.get("expectation_en", ""),
                "forbidden": payload.get("forbidden", []),
                "required": payload.get("required", []),
                "source": "user_modification",
                "status": "confirmed",
                "user_confirmed": True,
                "version": old_version + 1,
                "supersedes": ent_id,
                "evidence_count": ent.get("evidence_count", 0),
                "verify_pass_count": ent.get("verify_pass_count", 0),
                "source_executions": payload.get("source_executions", []),
                "last_observed": ent.get("last_observed", ""),
                "created_at": _now(),
            }
            self._write_canonical("rule", self.user.root / "rules" / f"{new_id}.json", new_rec)
            fts_text = " ".join(str(new_rec.get(k, "")) for k in ("rule_zh", "rule_en", "probe_zh", "probe_en")).strip()
            self.store.upsert_entity(
                new_id, "memory", subtype="rule", domain=domain, content=fts_text,
                payload=new_rec, created_at=new_rec["created_at"],
                status="confirmed", confidence=max(ent.get("confidence") or 0.0, 0.9),
                evidence_count=new_rec["evidence_count"],
                verify_pass_count=new_rec["verify_pass_count"],
                last_observed=new_rec["last_observed"],
                user_confirmed=True, scope=ent.get("scope", "global"),
                scope_id=ent.get("scope_id", ""), version=old_version + 1,
            )
            self.store.add_edge(new_id, "supersedes", ent_id)
            self.store.add_edge(USER_ID, "owns", new_id)
            self.store.add_fts(new_id, "memory", "rule", domain, fts_text)
        else:
            from .classify import DOMAIN_SHORT

            dom_short = DOMAIN_SHORT.get(domain.lower(), domain.upper()[:6] or "GEN")
            n = 0
            # id sequence from BOTH canonical and store (canonical may lag
            # behind entities created by tests/other paths)
            for p in _read_jsonl_lines(self.user.memory / "preferences.jsonl"):
                if p.get("id", "").startswith(f"P-{dom_short}-"):
                    try:
                        n = max(n, int(p["id"].rsplit("-", 1)[1]))
                    except (ValueError, IndexError):
                        pass
            for row in self.store._conn.execute(
                "SELECT id FROM entities WHERE subtype='preference' AND id LIKE ?",
                (f"P-{dom_short}-%",),
            ):
                try:
                    n = max(n, int(row["id"].rsplit("-", 1)[1]))
                except (ValueError, IndexError):
                    pass
            new_id = f"P-{dom_short}-{n + 1:03d}"
            if new_id == ent_id:  # defensive: never overwrite the original
                new_id = f"P-{dom_short}-{n + 2:03d}"
            new_rec = {
                "id": new_id,
                "type": "preference",
                "domain": domain,
                "content": content,
                "source": "user_modification",
                "supersedes": ent_id,
                "status": "confirmed",
                "user_confirmed": True,
                "version": old_version + 1,
                "evidence_count": ent.get("evidence_count", 0),
                "verify_pass_count": ent.get("verify_pass_count", 0),
                "source_executions": payload.get("source_executions", []),
                "last_observed": ent.get("last_observed", ""),
                "created_at": _now(),
            }
            self._write_canonical("jsonl", self.user.memory / "preferences.jsonl", new_rec)
            self.store.upsert_entity(
                new_id, "memory", subtype="preference", domain=domain,
                content=content, payload=new_rec, created_at=new_rec["created_at"],
                status="confirmed", confidence=max(ent.get("confidence") or 0.0, 0.9),
                evidence_count=new_rec["evidence_count"],
                verify_pass_count=new_rec["verify_pass_count"],
                last_observed=new_rec["last_observed"],
                user_confirmed=True, scope=ent.get("scope", "global"),
                scope_id=ent.get("scope_id", ""), version=old_version + 1,
            )
            self.store.add_edge(new_id, "supersedes", ent_id)
            self.store.add_edge(USER_ID, "owns", new_id)
            self.store.add_fts(new_id, "memory", "preference", domain, content)

        # old version → superseded (canonical + store; history untouched)
        self.store.supersede(ent_id, new_id, reason=reason)
        path, kind = self._canonical_target(ent)
        if path.exists():
            if kind == "rule":
                try:
                    rec = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    rec = {}
                rec["status"] = "superseded"
                rec["superseded_by"] = new_id
                rec["superseded_reason"] = reason
                self._write_canonical("rule", path, rec)
            else:
                for row in _read_jsonl_lines(path):
                    if row.get("id") == ent_id:
                        row["status"] = "superseded"
                        row["superseded_by"] = new_id
                        row["superseded_reason"] = reason
                        self._write_canonical("jsonl", path, row)
                        break

        self._trace(action_id, action="modify", memory_id=ent_id,
                    old_status="confirmed", new_status="superseded",
                    reason=reason, old_version=old_version, new_version=old_version + 1,
                    target=new_id)
        return {"new": new_id, "superseded": ent_id, "version": old_version + 1}
