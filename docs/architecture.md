# CognitiveOS 架构

## 总览

CognitiveOS 是一个**用户层认知持久层**：主人是主人，Agent 是管家。它把"主人的偏好、项目经验、判断风格"从任何单一 Agent 里抽出来，让这些认知**跨 Agent、跨设备、可迁移**。

```
用户 / 外部系统
        │
        ▼
┌─────────────────┐
│ Cognitive Kernel │  — 编排循环（见 DESIGN.md）
└─────────────────┘
        │
        ├──► 记忆系统
        ├──► Agent 路由
        ├──► 反思（复刻校验）
        └──► 外部 Agent
             (Hermes, Claude Code, Codex, OpenClaw, MCP tools)
```

## 运行时代码布局（v0.1）

```
src/cogos/
  cli.py            — `cogos` 命令（bootstrap、status 等）
  paths.py          — 目录布局的唯一事实源
  discovery.py      — Agent 发现层（每次运行所有探针）
  probes.py         — 每个 Agent 一个探针（当前有 Hermes / Claude Code / Codex）
  adapters/         — 统一的 Agent 接口
    __init__.py
    hermes/         — 第一个具体 adapter
    claude_code/    — Claude Code adapter
    codex/          — Codex adapter
  bootstrap.py      — 编排流水线（发现 → 选择 → 收割 → wiki → 仪表盘）
  normalizer.py     — 原始 → 标准化索引
  wiki.py           — 标准化 → Markdown wiki 页面
  dashboard.py      — wiki → dashboard/index.html
  templates/
    dashboard.html.j2
```

## 数据布局（v0.1）

```
knowledge/
  sources/<agent>/     ← 原始文件，保留原路径
  normalized/index.json
  wiki/<agent>.md      ← 每个 Agent 一页，另有 index.md
dashboard/index.html   ← 每次 bootstrap 重新生成
.cogos/last_report.json
```

## Bootstrap 流水线

```
cogos bootstrap
     │
     ▼
discover()            ── 每个探针运行，返回 AgentHandles
     │
     ▼
load_adapter()        ── 为 Hermes 选择 HermesAdapter
     │
     ▼
adapter.harvest()     ── 按白名单复制到 knowledge/sources/<agent>/
     │
     ▼
build_normalized_index()
     │
     ▼
build_wiki()          ── 在 knowledge/wiki/ 下生成 Markdown 页面
     │
     ▼
render_dashboard()    ── 生成 dashboard/index.html
     │
     ▼
打开浏览器
```

## 设计原则

- **每个层都可替换**——替换某一层不需要触碰其他层。例如：换一个 Agent 只需要新写一个 probe + adapter，发现层、归一化层、仪表盘层都不用动。
- **本地优先**——数据默认留在本机，不依赖云端。
- **Agent 无关**——CognitiveOS 不属于任何 Agent；Hermes 只是第一个 adapter，不是核心。
- **可追溯**——任何 wiki 页面都可以沿 `sources/ → normalized/ → wiki/` 链路回到原始文件。
- **人可读 + 机器可读**——知识库既是给人读的文档，也方便 AI 读取。
