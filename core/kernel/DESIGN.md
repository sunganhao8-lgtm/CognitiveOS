# Cognitive Kernel v0.1 — Design

> Phase 2 的 该 CognitiveOS roadmap.
> This document defines **what 该 Kernel 是**, 不 how it 是 implemented.
> 无 implementation code lives here yet; interfaces 是 sketches 到 为 validated.

## 1. Position

该 Kernel 是 该 single entry point 的 CognitiveOS.

Everything 用户 或 an external system wants 来自 CognitiveOS flows through 该 Kernel:

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

该 Kernel 做 不 *做* 该 work 的 一个 Agent. It **coordinates**:
assemble context → decide → 执行 → reflect → remember.

## 2. Goals 用于 v0.1

1. Define **stable interfaces**, 不 implementations.
2. Establish a minimal runnable flow:
   `task in → context assembly → routing → execution → reflection → memory write`
3. Keep 每个 subsystem **pluggable**: 记忆 backends, routers, Agent Adapters 可以 为 swapped 不使用 touching 该 Kernel.
4. Support multiple external Agents behind one protocol (see `core/protocol/README.md`).

## 3. Non-Goals 用于 v0.1

- ❌ 无 storage engine implementation (记忆 backends land 在 v0.2 / v0.3).
- ❌ 无 learned/ML router — v0.1 routing 是 explicit 规则-based only.
- ❌ 无 autonomous self-improvement loop — reflection stays manual/auditable.
- ❌ 无 distributed 或 multi-process concerns — v0.1 是 single-process.

> Architecture problem found while designing: 不要 put policy (what 到 做) inside 该
> Kernel; 该 Kernel only provides 该 *loop*. Policy belongs 到 该 Router 和 到
> Agent-具体 Adapters. This keeps 该 Kernel small 和 testable.

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

Python-style protocol sketches (actual language binding 是 a later decision):

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

## 6. 记忆 Contract (v0.1)

CognitiveOS 记忆 是 **不 only storage** (see `memory/README.md`). v0.1 defines 该
contract; implementations come later.

| Store          | Contents                              | Volatility | Written 通过            |
|----------------|---------------------------------------|------------|-----------------------|
| short_term     | 当前 任务 context                  | session    | Kernel (context build)|
| long_term      | stable knowledge / user preferences   | persistent | Kernel (confirmed)    |
| episodic       | 具体 experiences (任务 records)   | persistent | Reflection hook       |
| semantic       | generalized knowledge extracted       | persistent | Reflection (dedup)    |

Design 规则: **一个任务 可能 only *读取* 该 stores listed 在 `required_memory`**
(plus short_term). This 是 该 v0.1 guard against 该 "所有 记忆 mixed together"
problem — 该 相同 problem this project 是 born 来自.

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

Full wire format lives 在 `core/protocol/` 和 必须 stay Agent-agnostic.

## 8. 目录 Mapping

| 路径              | Role 在本 design                              |
|-------------------|--------------------------------------------------|
| `core/kernel/`    | Kernel orchestration loop (this design)          |
| `core/router/`    | Router contract + 规则-based 默认             |
| `core/state/`     | Runtime state 的 该 Kernel loop                 |
| `core/protocol/`  | Agent-agnostic request/response schemas          |
| `memory/*`        | MemoryProvider implementations (v0.2+)           |
| `agents/*`        | AgentAdapter implementations                     |
| `reflection/`     | Post-任务 analysis pipeline (v0.3)               |
| `tests/`          | Contract 测试 against 该 protocol sketches     |

## 9. Open Questions (用于 phase 3 和 beyond)

1. Python vs TypeScript 作为 该 primary binding? (Python 是 该 assumed 默认.)
2. 应该 `required_memory` 为 inferred 自动 在 later phases (semantic routing)?
3. Where 做 该 Planner live — inside 该 Kernel loop 或 作为 a separate subsystem?
4. How 做 multiple Kernels (multi-user / multi-tenant) share one 记忆 system?
5. 是 该 reflection hook synchronous (blocks 结果) 或 async (fire-和-forget)?

None 的 these block v0.1; they 是 tracked here so phase 3 做 不 silently pick
answers 不使用 a decision record (see `docs/design-decisions.md`).
