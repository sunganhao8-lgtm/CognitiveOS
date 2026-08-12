# Architecture Decisions

本文件 records key design decisions 用于 CognitiveOS.

每个 decision 应该 describe:

- Context
- Options considered
- Decision
- Consequences

---

## DEC-001 — Package layout: `src/cogos/`

**Context.** We needed a clear namespace 用于 CognitiveOS code 也就是说
distinct 来自 该 project's 目录 name.

**Decision.** 所有 runtime code lives under `src/cogos/`. 该 CLI entry
point `cogos` 是 exposed via `pyproject.toml` `[project.scripts]`.

**Consequences.** 测试 可以 import `cogos` cleanly, 和 `pip install -e .`
makes 该 command available system-wide.

---

## DEC-002 — Agent discovery 是 一个列表 probes, 不 a switch statement

**Context.** Adding a 新 Agent (Codex, Claude Code, OpenClaw, …) 必须
不 require editing a central dispatcher.

**Decision.** 每个 Agent 是 discovered 通过 a small `Probe` function 在
`cogos.probes`. `discovery.discover()` 运行 每个 probe 和 unions 该
results.

**Consequences.** Adding a 新 Adapter = one 新 probe + one Adapter
模块. 无 central code 是 touched.

---

## DEC-003 — Adapters 是 该 only place that knows Agent internals

**Context.** Agents store their state 在 wildly 不同 ways.

**Decision.** A single `Adapter` protocol (`describe / harvest /
bootstrap_query`) hides every implementation detail.

**Consequences.** Discovery, normalization, 和 该 dashboard 从不
import 一个 Agent-具体 模块. Replacing 该 Hermes Adapter 使用 a
Codex Adapter 需要 无 changes outside `cogos/adapters/<agent>/`.

---

## DEC-004 — Three-layer knowledge base (来源们 / normalized / wiki)

**Context.** 用户 explicitly required raw data 到 remain traceable
和 该 structure itself 到 convey meaning.

**Decision.** 每个 harvested 文件 是 stored verbatim under
`knowledge/sources/<agent>/`. A normalizer produces
`knowledge/normalized/index.json`. A wiki renderer produces one Markdown
page per Agent under `knowledge/wiki/`.

**Consequences.** 任何 wiki page 可以 为 traced back 到 a 来源 文件 通过
following 路径 recorded 在 its frontmatter. 无 piece 的 knowledge
exists 不使用 provenance.

---

## DEC-005 — Hermes whitelist 在 v0.1 (无 caches, 无 auth, 无 sessions)

**Context.** A naive "copy everything" harvest picked up `state.db`,
`auth.json`, session JSONLs, cache 目录们, 和 该 profiles
`.git/` history. These 是 runtime state 和 credentials, 不 knowledge.

**Decision.** `HermesAdapter.SAFE_TOP_LEVEL` 和
`SAFE_PROFILE_FILES` 是 explicit whitelists. Cache, auth, sessions,
state.db, logs, 和 `.git/` 是 从不 copied.

**Consequences.** Bootstrap reports `~1600` 技能 文件们 plus a handful
的 `*.md` / `config.yaml`. 用户 可以 audit 该 harvested set
quickly, 和 无 credentials ever leave 该 Hermes 安装.

---

## DEC-006 — Dashboard 是 local HTML, 无 framework

**Context.** 用户 asked 用于 a self-contained, local-第一 interface
that an AI Agent 可以 rewrite easily.

**Decision.** `dashboard/index.html` 是 rendered 来自 a Jinja2 template
plus a single embedded `<style>` block. 无 React, 无 Vue, 无 CDN.

**Consequences.** 该 dashboard works offline, 是 one 文件, 和 可以 为
regenerated 或 hand-edited 不使用 a build step.

---

## DEC-007 — Single-process v0.1

**Context.** Distributed 和 multi-process concerns 是 out 的 scope.

**Decision.** v0.1 是 single-process. 该 bootstrap pipeline 运行 top 到
bottom 在 one Python invocation.

**Consequences.** Simpler debugging, simpler reasoning about state, 和
zero infrastructure dependencies. Multi-process 是 a v1.x concern.