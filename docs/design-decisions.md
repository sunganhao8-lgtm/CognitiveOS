# 架构决策记录（ADR）

本文件记录 CognitiveOS 的关键设计决策。

每个决策应说明：

- 背景（Context）
- 考虑的选项（Options considered）
- 决策（Decision）
- 影响（Consequences）

---

## DEC-001 — 包布局：`src/cogos/`

**背景。** 我们需要一个清晰的命名空间来放 CognitiveOS 代码，
与项目目录名区分开。

**决策。** 所有运行时代码放在 `src/cogos/` 下。CLI 入口 `cogos`
通过 `pyproject.toml` 的 `[project.scripts]` 暴露。

**影响。** 测试可以干净地 `import cogos`；`pip install -e .`
让命令在系统级可用。

---

## DEC-002 — Agent 发现是一组探针（probes），不是 switch 语句

**背景。** 新增一个 Agent（Codex、Claude Code、OpenClaw……）不能要求
去改一个中央分发器。

**决策。** 每个 Agent 通过 `cogos.probes` 下的一个小 `Probe` 函数被发现。
`discovery.discover()` 运行所有探针并合并结果。

**影响。** 新增一个 Adapter = 一个探针 + 一个 Adapter 模块。中央代码零改动。

---

## DEC-003 — Adapter 是唯一知道 Agent 内部细节的地方

**背景。** 每个 Agent 的存储方式差异极大。

**决策。** 一个统一的 `Adapter` 协议（`describe / harvest / bootstrap_query`）
隐藏所有实现细节。

**影响。** 发现层、归一化层和仪表盘从不 import 任何 Agent 专属模块。
把 Hermes Adapter 换成 Codex Adapter，`cogos/adapters/<agent>/` 之外零改动。

---

## DEC-004 — 三层知识库（sources / normalized / wiki）

**背景。** 用户明确要求原始数据可追溯，且结构本身要有意义。

**决策。** 每个收割到的文件原样存放在 `knowledge/sources/<agent>/`。
归一化器产出 `knowledge/normalized/index.json`。wiki 渲染器为每个 Agent
生成一个 Markdown 页面，放在 `knowledge/wiki/`。

**影响。** 任何 wiki 页面都能通过 frontmatter 里记录的路径回到源文件。
没有任何知识片段是"无出处"的。

---

## DEC-005 — v0.1 Hermes 白名单（无缓存、无认证、无会话）

**背景。** 一次"全部复制"式的收割会把 `state.db`、`auth.json`、
会话 JSONL、缓存目录和 profiles 的 `.git/` 历史都收进来。
这些是运行时状态和凭据，不是知识。

**决策。** `HermesAdapter.SAFE_TOP_LEVEL` 和 `SAFE_PROFILE_FILES`
是显式白名单。缓存、认证、会话、state.db、日志和 `.git/` 从不复制。

**影响。** Bootstrap 报告约 1600 个技能文件加少量 `*.md` / `config.yaml`。
用户可以快速审计收割集合；凭据永远不会离开 Hermes 安装目录。

---

## DEC-006 — 仪表盘是本地 HTML，无框架

**背景。** 用户要求一个自包含、本地优先、AI Agent 容易改写的界面。

**决策。** `dashboard/index.html` 由 Jinja2 模板加单个内嵌 `<style>` 块渲染。
无 React、无 Vue、无 CDN。

**影响。** 仪表盘离线可用、是单个文件、可以在没有构建步骤的情况下
重新生成或手工编辑。

---

## DEC-007 — v0.1 单进程

**背景。** 分布式和多进程问题超出 v0.1 范围。

**决策。** v0.1 是单进程的。bootstrap 流水线在一次 Python 调用里从上到下跑完。

**影响。** 调试更简单、状态推理更简单、零基础设施依赖。
多进程是 v1.x 的事。
