# Cognitive Kernel v0.1 — Design

> Phase 2 of the CognitiveOS roadmap.
> This document defines **what the Kernel is**, not how it is implemented.
> No implementation code lives here yet; interfaces are sketches to be validated.

## 1. Position

The Kernel is the single entry point of CognitiveOS.

Everything a user or an external system wants from CognitiveOS flows through the Kernel:

```
User / External System
        │
        ▼
┌─────────────────┐
│ Cognitive Kernel │  ← this document
└─────────────────┘
        │
        ├──► Memory System     (short / long / episodic / semantic)
        ├──► Agent Router      (which agent should handle this?)
        ├──► Reflection        (what did we learn after the task?)
        └──► External Agents   (Claude Code, Codex, OpenClaw, Hermes, MCP tools)
```

The Kernel does not *do* the work of an agent. It **coordinates**:
assemble context → decide → execute → reflect → remember.

## 2. Goals for v0.1

1. Define **stable interfaces**, not implementations.
2. Establish a minimal runnable flow:
   `task in → context assembly → routing → execution → reflection → memory write`
3. Keep every subsystem **pluggable**: memory backends, routers, agent adapters can be swapped without touching the Kernel.
4. Support multiple external agents behind one protocol (see `core/protocol/README.md`).

## 3. Non-Goals for v0.1

- ❌ No storage engine implementation (memory backends land in v0.2 / v0.3).
- ❌ No learned/ML router — v0.1 routing is explicit rule-based only.
- ❌ No autonomous self-improvement loop — reflection stays manual/auditable.
- ❌ No distributed or multi-process concerns — v0.1 is single-process.

> Architecture problem found while designing: do not put policy (what to do) inside the
> Kernel; the Kernel only provides the *loop*. Policy belongs to the Router and to
> agent-specific adapters. This keeps the Kernel small and testable.

## 4. Core Flow

```
User submits Task
        │
        ▼
┌─ Kernel.run(task) ───────────────────────────────┐
│                                                  │
│  1. Assemble context                             │
│     memory.read({domain, task.required_memory})  │
│                                                  │
│  2. Route                                        │
│     router.decide(task, context)                 │
│     → RouteDecision(agent_id, reason)            │
│                                                  │
│  3. Execute                                      │
│     adapter.execute(task, context)               │
│     → Result(status, output, artifacts)          │
│                                                  │
│  4. Reflect (post-task hook)                     │
│     reflection.analyze(task, result)             │
│     → observations                               │
│                                                  │
│  5. Remember                                     │
│     memory.write(episodic + semantic entries)    │
│                                                  │
└──────────────────────────────────────────────────┘
        │
        ▼
   Result returned to caller
```

## 5. Core Abstractions

Python-style protocol sketches (actual language binding is a later decision):

```python
class Task:
    id: str
    intent: str                 # free-form description of what the user wants
    domain: str                 # e.g. "oracle", "coding", "writing"
    required_memory: list[str]  # memory keys the task needs, e.g. ["sql_experience"]
    constraints: dict           # optional: budget, deadline, tool restrictions

class Context:
    task: Task
    memory_entries: list        # assembled from MemoryProvider.read()

class RouteDecision:
    agent_id: str               # e.g. "claude_code", "hermes", "codex"
    reason: str                 # human-readable explanation (auditable routing)
    confidence: float           # 0..1

class Result:
    status: str                 # "success" | "failed" | "partial"
    output: str
    artifacts: list[str]        # paths / handles of produced files
    observations: list[str]     # raw material for reflection

# --- subsystem contracts ---

class MemoryProvider(Protocol):
    def read(self, query: MemoryQuery) -> list[MemoryEntry]: ...
    def write(self, entry: MemoryEntry) -> None: ...

class Router(Protocol):
    def decide(self, task: Task, context: Context) -> RouteDecision: ...

class AgentAdapter(Protocol):
    agent_id: str
    def execute(self, task: Task, context: Context) -> Result: ...

class Kernel:
    def __init__(self, memory, router, reflection, adapters): ...
    def run(self, task: Task) -> Result: ...
```

## 6. Memory Contract (v0.1)

CognitiveOS memory is **not only storage** (see `memory/README.md`). v0.1 defines the
contract; implementations come later.

| Store          | Contents                              | Volatility | Written by            |
|----------------|---------------------------------------|------------|-----------------------|
| short_term     | current task context                  | session    | Kernel (context build)|
| long_term      | stable knowledge / user preferences   | persistent | Kernel (confirmed)    |
| episodic       | specific experiences (task records)   | persistent | Reflection hook       |
| semantic       | generalized knowledge extracted       | persistent | Reflection (dedup)    |

Design rule: **a task may only *read* the stores listed in `required_memory`**
(plus short_term). This is the v0.1 guard against the "all memory mixed together"
problem — the same problem this project was born from.

## 7. Agent Protocol (v0.1)

Request (user-facing, minimal):

```json
{
  "task": "write an Oracle query",
  "domain": "oracle",
  "required_memory": ["sql_experience", "oracle_issues"]
}
```

Response (CognitiveOS-side):

```json
{
  "agent_selection": "claude_code",
  "memory_context": ["sql_experience: ...", "oracle_issues: ..."],
  "execution_plan": "..."
}
```

Full wire format lives in `core/protocol/` and must stay agent-agnostic.

## 8. Directory Mapping

| Path              | Role in this design                              |
|-------------------|--------------------------------------------------|
| `core/kernel/`    | Kernel orchestration loop (this design)          |
| `core/router/`    | Router contract + rule-based default             |
| `core/state/`     | Runtime state of the Kernel loop                 |
| `core/protocol/`  | Agent-agnostic request/response schemas          |
| `memory/*`        | MemoryProvider implementations (v0.2+)           |
| `agents/*`        | AgentAdapter implementations                     |
| `reflection/`     | Post-task analysis pipeline (v0.3)               |
| `tests/`          | Contract tests against the protocol sketches     |

## 9. Open Questions (for phase 3 and beyond)

1. Python vs TypeScript as the primary binding? (Python is the assumed default.)
2. Should `required_memory` be inferred automatically in later phases (semantic routing)?
3. Where does the Planner live — inside the Kernel loop or as a separate subsystem?
4. How do multiple Kernels (multi-user / multi-tenant) share one memory system?
5. Is the reflection hook synchronous (blocks the result) or async (fire-and-forget)?

None of these block v0.1; they are tracked here so phase 3 does not silently pick
answers without a decision record (see `docs/design-decisions.md`).
