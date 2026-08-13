"""Cognitive Kernel — the orchestration loop.

Two entry points:

* ``run(task)`` — the v0.1 protocol loop (context assembly → routing →
  execution → reflection → memory write). Kept for the pluggable-subsystem
  contract and its tests.

* ``run_input(user_input)`` — the REAL cognitive loop introduced in Phase 2B
  (docs/cognitive-architecture.md):

      observe/classify → remember? → retrieve → build context → execute
      → verify → learn → trace (every step)

  This is the entry point of ``cogos run``. It requires the Cognitive Store
  (SQLite index), a Retriever, the user layer, and optionally an LLM helper
  for semantic classification / rule extraction.

Trace discipline: only observable system events are recorded — retrieved
memory ids, selected agent, verdicts. Never model-internal reasoning.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .paths import Paths
from .store import Store, USER_ID
from .user import UserLayer
from . import classify as classify_mod
from . import retrieve as retrieve_mod
from . import trace as trace_mod
from . import verify as verify_mod


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    id: str
    intent: str
    domain: str
    required_memory: tuple[str, ...] = ()


@dataclass(frozen=True)
class Context:
    task: Task
    memory_entries: list = field(default_factory=list)
    context_block: str = ""  # Phase 2B: assembled SYSTEM CONTEXT injected into the agent
    refs: list = field(default_factory=list)


@dataclass(frozen=True)
class RouteDecision:
    agent_id: str
    reason: str
    confidence: float


@dataclass
class Result:
    task_id: str
    status: str  # "success" | "failed"
    output: str
    artifacts: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    routed_to: str | None = None
    routing_reason: str | None = None


@dataclass
class RunResult:
    """Result of the full cognitive loop (``run_input``)."""
    execution_id: str
    intent_type: str  # "rule" | "task"
    task: str
    agent_id: str = ""
    status: str = ""  # "learned" | "success" | "failed"
    verdict: str = ""  # "" (nothing to verify) | PASS | FAIL | AMBIGUOUS
    context_chars: int = 0
    retrieved_summary: str = ""
    memory_written: list = field(default_factory=list)
    output: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Subsystem contracts
# ---------------------------------------------------------------------------


class MemoryProvider(Protocol):
    def read(self, query: list[str]) -> list: ...
    def write(self, entry: dict) -> None: ...


class Router(Protocol):
    def decide(self, task: Task, context: Context) -> RouteDecision: ...


class AgentAdapter(Protocol):
    agent_id: str

    def execute(self, task: Task, context: Context) -> Result: ...
    def bootstrap_query(self, prompt: str) -> str | None: ...


# ---------------------------------------------------------------------------
# Default implementations (v0.1)
# ---------------------------------------------------------------------------


class FileMemory:
    """Trivial JSON-line memory store under ``.cogos/memory.jsonl``.

    Kept for the v0.1 protocol tests. The Cognitive Store (SQLite index +
    ``user/memory/*.jsonl`` canonical) supersedes it in the full loop.
    """

    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self, query: list[str]) -> list:
        if not self.store_path.exists():
            return []
        entries = []
        for line in self.store_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if any(q in rec.get("keys", []) for q in query) or not query:
                entries.append(rec)
        return entries

    def write(self, entry: dict) -> None:
        if "created_at" not in entry:
            entry = {**entry, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with self.store_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class DomainRouter:
    """Rule-based router for v0.1.

    Picks the first registered adapter whose ``handles`` includes the
    task's domain. If none matches, picks the first adapter (fail-open).
    """

    def __init__(self, adapters: list[AgentAdapter], *, domain_map: dict[str, str] | None = None) -> None:
        self.adapters = {a.agent_id: a for a in adapters}
        self.domain_map = domain_map or {}

    def decide(self, task: Task, context: Context) -> RouteDecision:
        if not self.adapters:
            return RouteDecision(agent_id="<none>", reason="no adapters", confidence=0.0)

        target_id = self.domain_map.get(task.domain)
        if target_id and target_id in self.adapters:
            return RouteDecision(
                agent_id=target_id,
                reason=f"domain '{task.domain}' explicitly mapped to '{target_id}'",
                confidence=0.95,
            )

        first_id = next(iter(self.adapters))
        return RouteDecision(
            agent_id=first_id,
            reason=f"domain '{task.domain}' fell back to first available adapter",
            confidence=0.6,
        )


# ---------------------------------------------------------------------------
# Kernel
# ---------------------------------------------------------------------------


class Kernel:
    def __init__(
        self,
        *,
        memory: MemoryProvider,
        router: Router,
        adapters: list[AgentAdapter],
        store: Store | None = None,
        retriever=None,          # callable(store, query, domain=...) -> RetrievedSet
        user: UserLayer | None = None,
        llm_fn=None,              # callable(prompt, timeout=...) -> str | None
        context_budget: int = retrieve_mod.DEFAULT_BUDGET,
        allow_semantic: bool = True,
    ) -> None:
        self.memory = memory
        self.router = router
        self.adapters = {a.agent_id: a for a in adapters}
        self.store = store
        self.retriever = retriever or (lambda s, q, domain="", limit=12: retrieve_mod.retrieve(s, q, domain=domain, limit=limit))
        self.user = user
        self.llm_fn = llm_fn
        self.context_budget = context_budget
        self.allow_semantic = allow_semantic

    # --- v0.1 protocol loop -------------------------------------------------

    def run(self, task: Task) -> Result:
        """The original pluggable-subsystem loop (kept for the contract)."""
        # 1. Context assembly
        context = Context(task=task, memory_entries=self.memory.read(list(task.required_memory)))

        # 2. Routing
        decision = self.router.decide(task, context)
        adapter = self.adapters.get(decision.agent_id)
        if adapter is None:
            return Result(
                task_id=task.id,
                status="failed",
                output=f"router selected '{decision.agent_id}' but no adapter is registered",
            )

        # 3. Execution
        result = adapter.execute(task, context)
        result.routed_to = decision.agent_id
        result.routing_reason = decision.reason

        # 4. Reflection (single observation per run for v0.1)
        observation = {
            "task_id": task.id,
            "domain": task.domain,
            "agent": decision.agent_id,
            "status": result.status,
            "note": f"kernel selected {decision.agent_id} for domain '{task.domain}'",
        }
        result.observations.append(observation["note"])

        # 5. Memory write (episodic)
        self.memory.write(
            {
                "task_id": task.id,
                "domain": task.domain,
                "agent": decision.agent_id,
                "intent": task.intent,
                "status": result.status,
                "keys": list(task.required_memory),
                "kind": "episodic",
            }
        )

        return result

    # --- Phase 2B full cognitive loop ---------------------------------------

    def run_input(self, user_input: str) -> RunResult:
        """Execute the complete loop: observe → remember? → retrieve →
        context → execute → verify → learn → trace."""
        if self.store is None or self.user is None:
            raise RuntimeError("run_input requires a Cognitive Store and a user layer (use kernel_from_paths)")

        text = (user_input or "").strip()
        if not text:
            raise ValueError("empty user input")

        t0 = time.time()
        ex_id = trace_mod.new_execution_id(self.store)
        trace_mod.append_event(self.user, self.store, ex_id, "execution_started", detail=text[:120])

        # 1. Observe / classify
        intent = classify_mod.classify_intent(text, self.llm_fn)
        trace_mod.append_event(
            self.user, self.store, ex_id, "task_classified",
            detail=f"type={intent.type} domain={intent.domain} method={intent.method}",
        )

        # 2. Remember (rule path)
        if intent.type == "rule":
            return self._learn_rule(ex_id, text, intent, t0)

        # 3-8. Task path
        task = Task(id=f"tk-{ex_id}", intent=text, domain=intent.domain)
        context = self._assemble(task, ex_id)

        decision = self.router.decide(task, context)
        adapter = self.adapters.get(decision.agent_id)
        if adapter is None:
            trace_mod.append_event(
                self.user, self.store, ex_id, "agent_selected",
                detail=f"no adapter for '{decision.agent_id}'",
            )
            out = Result(task_id=task.id, status="failed",
                         output=f"router selected '{decision.agent_id}' but no adapter is registered")
            verdict = ""
        else:
            trace_mod.append_event(
                self.user, self.store, ex_id, "agent_selected",
                detail=f"agent={decision.agent_id} reason={decision.reason}",
            )
            out = adapter.execute(task, context)
            out.routed_to = decision.agent_id
            out.routing_reason = decision.reason
            trace_mod.append_event(
                self.user, self.store, ex_id, "agent_executed",
                detail=f"status={out.status} chars={len(out.output or '')}",
            )
            verdict = self._verify(ex_id, task, context, out)

        mem_id = self._learn(ex_id, task, out, verdict, context.refs)

        elapsed = time.time() - t0
        started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if verdict == "FAIL":
            final_status = "failed"
        elif verdict in ("AMBIGUOUS",) and out.status == "failed":
            final_status = "failed"
        else:
            final_status = out.status

        exec_row = {
            "execution_id": ex_id,
            "task": text,
            "intent_type": intent.type,
            "agent_id": decision.agent_id if out.routed_to else "",
            "status": final_status,
            "verdict": verdict,
            "context_chars": len(context.context_block),
            "started_at": started_at,
            "finished_at": finished_at,
            "refs": context.refs,
            "memory_written": [mem_id] if mem_id else [],
            "retrieved_summary": " ".join(
                f"{k}={v}" for k, v in sorted(self._last_sections.items()) if v
            ) if getattr(self, "_last_sections", None) else "",
        }
        trace_mod.append_execution(self.user, self.store, exec_row)
        trace_mod.append_event(self.user, self.store, ex_id, "execution_completed", detail=final_status)

        return RunResult(
            execution_id=ex_id,
            intent_type=intent.type,
            task=text,
            agent_id=decision.agent_id if out.routed_to else "",
            status=final_status,
            verdict=verdict,
            context_chars=len(context.context_block),
            retrieved_summary=exec_row["retrieved_summary"],
            memory_written=[mem_id] if mem_id else [],
            output=(out.output or "")[:2000],
            elapsed=round(elapsed, 2),
        )

    # ---- internal steps -----------------------------------------------------

    def _assemble(self, task: Task, ex_id: str) -> Context:
        """Retrieve → build bounded context (trace both steps)."""
        retrieved = self.retriever(self.store, task.intent, domain=task.domain)
        self._last_retrieved = list(retrieved.hits)
        trace_mod.append_event(
            self.user, self.store, ex_id, "memory_retrieved",
            detail=retrieved.summary(), refs=retrieved.refs(),
        )
        block = retrieve_mod.build_context(retrieved, task.intent, budget=self.context_budget)
        self._last_sections = dict(block.sections)
        trace_mod.append_event(
            self.user, self.store, ex_id, "context_built",
            detail=f"chars={block.chars} truncated={block.truncated}",
        )
        return Context(
            task=task,
            memory_entries=[],
            context_block=block.text,
            refs=retrieved.refs(),
        )

    def _verify(self, ex_id: str, task: Task, context: Context, out: Result) -> str:
        """Judge the agent's output against every retrieved rule.

        Three stages (reused from cogos.verify): forbidden → FAIL;
        required missing → AMBIGUOUS → LLM semantic judge.
        """
        rules = [h for h in self._retrieved_for(ex_id) if h.type == "memory" and h.subtype == "rule"]
        if not rules:
            trace_mod.append_event(
                self.user, self.store, ex_id, "verification_completed",
                detail="no rules retrieved — nothing to verify",
            )
            return ""

        verdicts: list[str] = []
        target = _verification_target(out.output or "")
        scope = "code_blocks" if target != (out.output or "") else "full_text"
        for h in rules:
            p = h.payload or {}
            rule = verify_mod.Rule(
                id=h.ent_id,
                rule_en=p.get("rule_en", ""),
                rule_zh=p.get("rule_zh", ""),
                probe_en=p.get("probe_en", ""),
                probe_zh=p.get("probe_zh", ""),
                expectation_en=p.get("expectation_en", ""),
                expectation_zh=p.get("expectation_zh", ""),
                forbidden=tuple(p.get("forbidden", ())),
                required=tuple(p.get("required", ())),
            )
            verdict, detail = verify_mod.judge(rule, target)
            if verdict == "AMBIGUOUS" and self.allow_semantic:
                verdict, sdetail = verify_mod.semantic_judge(rule, target)
                detail = f"{detail} -> semantic: {sdetail}"
            trace_mod.append_verification(self.user, self.store, ex_id, h.ent_id, verdict, detail)
            verdicts.append(verdict)

        overall = "PASS"
        if "FAIL" in verdicts:
            overall = "FAIL"
        elif "AMBIGUOUS" in verdicts:
            overall = "AMBIGUOUS"
        trace_mod.append_event(
            self.user, self.store, ex_id, "verification_completed",
            detail=f"verdict={overall} checked={len(verdicts)} scope={scope}",
        )
        return overall

    def _retrieved_for(self, ex_id: str):
        # The retrieved hits are stashed during _assemble so _verify can
        # judge the output against the same rules that were injected.
        return getattr(self, "_last_retrieved", [])

    def _learn(self, ex_id: str, task: Task, out: Result, verdict: str, refs: list) -> str:
        """Write the episodic memory entry (canonical + index)."""
        mem_id = f"mem-{ex_id}"
        content = (
            f"[{verdict or 'n/a'}] {task.intent[:200]} "
            f"→ agent={out.routed_to or '?'} status={out.status}"
        )
        rec = {
            "id": mem_id,
            "type": "episodic",
            "domain": task.domain,
            "content": content,
            "source": "execution",
            "derived_from_execution": ex_id,
            "verdict": verdict,
            "refs": [r["id"] for r in refs],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.user.memory.mkdir(parents=True, exist_ok=True)
        with (self.user.memory / "episodic.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.store.upsert_entity(
            mem_id, "memory", subtype="episodic", domain=task.domain,
            content=rec["content"], payload=rec, created_at=rec["created_at"],
        )
        self.store.add_edge(mem_id, "derived_from", ex_id)
        self.store.add_edge(USER_ID, "owns", mem_id)
        self.store.add_fts(mem_id, "memory", "episodic", task.domain, rec["content"])
        trace_mod.append_event(
            self.user, self.store, ex_id, "memory_written",
            detail=f"episodic={mem_id}", refs=[{"type": "memory", "id": mem_id}],
        )
        return mem_id

    def _learn_rule(self, ex_id: str, text: str, intent, t0: float) -> RunResult:
        """Rule path: structure the statement → persist → trace → done."""
        draft = classify_mod.extract_rule(text, self.llm_fn)
        rid = classify_mod.next_rule_id(self.user.root / "rules", draft.domain)
        rule_dict = {
            "id": rid,
            "domain": draft.domain,
            "rule_en": draft.rule_en,
            "rule_zh": draft.rule_zh,
            "probe_en": draft.probe_en,
            "probe_zh": draft.probe_zh,
            "expectation_en": draft.expectation_en,
            "expectation_zh": draft.expectation_zh,
            "forbidden": list(draft.forbidden),
            "required": list(draft.required),
            "source": "user_statement",
            "extract_method": draft.method,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        rules_dir = self.user.root / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / f"{rid}.json").write_text(
            json.dumps(rule_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        fts_text = " ".join(
            str(rule_dict.get(k, ""))
            for k in ("rule_zh", "rule_en", "probe_zh", "probe_en")
        ).strip()
        self.store.upsert_entity(
            rid, "memory", subtype="rule", domain=draft.domain,
            content=fts_text, payload=rule_dict, created_at=rule_dict["created_at"],
        )
        self.store.add_edge(USER_ID, "owns", rid)
        self.store.add_fts(rid, "memory", "rule", draft.domain, fts_text)
        trace_mod.append_event(
            self.user, self.store, ex_id, "memory_written",
            detail=f"rule={rid} method={draft.method} forbidden={list(draft.forbidden)}",
            refs=[{"type": "memory", "subtype": "rule", "id": rid}],
        )

        elapsed = time.time() - t0
        exec_row = {
            "execution_id": ex_id,
            "task": text,
            "intent_type": "rule",
            "agent_id": "",
            "status": "learned",
            "verdict": "",
            "context_chars": 0,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "refs": [{"type": "memory", "subtype": "rule", "id": rid}],
            "memory_written": [rid],
            "retrieved_summary": "",
        }
        trace_mod.append_execution(self.user, self.store, exec_row)
        trace_mod.append_event(self.user, self.store, ex_id, "execution_completed", detail="learned")
        return RunResult(
            execution_id=ex_id,
            intent_type="rule",
            task=text,
            status="learned",
            memory_written=[rid],
            output=f"已记住规则 {rid}（domain={draft.domain}，提取方式={draft.method}）",
            elapsed=round(elapsed, 2),
        )


def _verification_target(output: str) -> str:
    """Pick the text verification runs against.

    Rules like "no SELECT * in SQL" govern the DELIVERABLE, not the agent's
    explanation. When the output contains fenced code blocks, verify only
    the code — otherwise a compliant answer that *mentions* the rule
    ("根据 R-SQL-001 我不能使用 SELECT *") would be judged a violation.
    Without code blocks, the full text is checked (scope recorded in trace).
    """
    import re

    blocks = re.findall(r"```[a-zA-Z]*\s*\n(.*?)```", output, re.DOTALL)
    if blocks:
        return "\n".join(b.strip() for b in blocks if b.strip())
    return output


# ---------------------------------------------------------------------------
# Helpers for callers
# ---------------------------------------------------------------------------


def kernel_from_paths(
    paths: Paths,
    adapters: list[AgentAdapter],
    *,
    domain_map: dict[str, str] | None = None,
    llm_fn=None,
    context_budget: int = retrieve_mod.DEFAULT_BUDGET,
    allow_semantic: bool = True,
) -> Kernel:
    """Build a Kernel wired against the project's local paths.

    Includes the Cognitive Store (index) and the user layer so the full
    cognitive loop (``run_input``) works out of the box.
    """
    store = Store(paths.cache / "cognitive.db")
    user = UserLayer(root=paths.root / "user")
    user.ensure()
    memory = FileMemory(paths.cache / "memory.jsonl")
    router = DomainRouter(adapters, domain_map=domain_map)
    return Kernel(
        memory=memory,
        router=router,
        adapters=adapters,
        store=store,
        user=user,
        llm_fn=llm_fn,
        context_budget=context_budget if context_budget else retrieve_mod.DEFAULT_BUDGET,
        allow_semantic=allow_semantic,
    )


def report_to_dict(result: Result) -> dict:
    return asdict(result)
