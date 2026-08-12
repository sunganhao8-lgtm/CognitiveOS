# CognitiveOS v0.1 — Quick Start

This walks you through 第一个 end-到-end 运行.

## Prerequisites

- Python 3.10+
- 在 least one 的: Hermes, Claude Code, Codex, OpenClaw installed locally

## 安装

```bash
git clone <repo>
cd CognitiveOS
pip install -e .
```

## Bootstrap

```bash
cogos bootstrap
```

Expected output (truncated):

```json
{
  "started_at": "...",
  "discovered": [{"agent_id": "hermes", ...}],
  "bootstrap_agent": "hermes",
  "harvested_files": 1603,
  "wiki_pages": 2,
  "dashboard": "D:\\...\\CognitiveOS\\dashboard\\index.html"
}
```

After it finishes, your 默认 browser opens 该 dashboard.

## Where things go

| 路径                            | What it contains                            |
|---------------------------------|---------------------------------------------|
| `knowledge/sources/<agent>/`    | Raw 文件们 harvested 来自 每个 Agent         |
| `knowledge/normalized/`         | Cross-Agent index                           |
| `knowledge/wiki/`               | Human-readable Markdown wiki                |
| `dashboard/index.html`          | Self-contained HTML dashboard               |
| `.cogos/last_report.json`       | Machine-readable report 的 最后一个 运行     |

## Re-running

`cogos bootstrap` 是 idempotent. 该 来源们 tree 是 refreshed 在
place, normalized 和 wiki layers 是 recomputed, 和 该 dashboard 是
re-rendered.

## Inspecting what 是 harvested

```bash
ls knowledge/sources/hermes/
ls knowledge/sources/hermes/profiles/
```

## 状态 不使用 bootstrapping

```bash
cogos status
```

Prints 该 JSON 的 该 most recent bootstrap 运行.

## 下一个 steps

- 添加 more Adapters (Claude Code, Codex, OpenClaw)
- Extend 该 normalizer 到 parse 每个 Agent's 记忆 文件 format
- Wire 该 Kernel DESIGN into a runtime loop
- Replace 该 dashboard template 使用 a richer one 当 v0.2 lands