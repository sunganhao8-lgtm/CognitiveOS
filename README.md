# CognitiveOS

**一个本地、可观察、可纠正、可追溯、可持续学习的 Agent Cognitive Runtime。**

换管家、换电脑、换产品——你的偏好、项目、经验都不丢。

## 这是什么？

CognitiveOS 不是 AI Memory Manager，不是 Agent Dashboard，也不是 RAG 系统。
它是 Agent 的认知操作系统：让 Agent 观察你、记住你、在任务中应用你的认知、
验证是否用对、接受你的纠正，并让你**看见**这一切。

```
Task → Classify → Remember → Retrieve → Context → Agent
     → Verify → Learn → Trace → Impact → Dashboard → User Correction
```

## 为什么存在？

AI Agent 会换（Hermes / Claude Code / Codex），但你的认知应该跟随你。
用户永远拥有最终控制权：确认、拒绝、修改、遗忘。

## 安装

```bash
git clone https://github.com/sunganhao8-lgtm/CognitiveOS.git
cd CognitiveOS
pip install -r requirements.txt      # 或 uv sync
pip install fastembed                 # 本地语义检索（可选，无则自动降级 FTS5）
```

## 初始化

```bash
PYTHONPATH=src python -m cogos.cli bootstrap --no-browser   # 生成 dashboard
PYTHONPATH=src python -m cogos.cli reindex                  # 重建索引
```

## 接 Agent

`cogos run "<任务>"` 通过统一 AgentAdapter 调用本机 Agent（Hermes 已内置）；
每个执行自动产生 trace。查看已注册 Agent：

```bash
PYTHONPATH=src python -m cogos.cli agent list
```

## 运行

```bash
PYTHONPATH=src python -m cogos.cli run "帮我写一个查询销售数据的 SQL。"
PYTHONPATH=src python -m cogos.cli sleep        # 离线认知整理（幂等）
PYTHONPATH=src python -m cogos.cli status       # 系统健康
```

## 查看 Memory

```bash
PYTHONPATH=src python -m cogos.cli memory list
PYTHONPATH=src python -m cogos.cli memory show R-SQL-001
PYTHONPATH=src python -m cogos.cli memory why  R-SQL-001   # 证据式解释
```

## 纠正 Memory

```bash
PYTHONPATH=src python -m cogos.cli memory confirm cand-001   # 确认候选
PYTHONPATH=src python -m cogos.cli memory reject  cand-001   # 拒绝推断
PYTHONPATH=src python -m cogos.cli memory forget  P-SQL-002  # 停止使用
PYTHONPATH=src python -m cogos.cli memory modify  P-SQL-002 --content "新认知"
```

## 查看 Dashboard

```bash
# 静态模式（双击 index.html 即可，按钮复制 CLI 命令）
PYTHONPATH=src python -m cogos.cli dashboard build
# 本地服务模式（127.0.0.1，按钮直接执行——confirm/reject/forget）
PYTHONPATH=src python -m cogos.cli dashboard serve
```

## 备份

```bash
PYTHONPATH=src python -m cogos.cli export  ~/cogos-backup-2026-08-14
PYTHONPATH=src python -m cogos.cli import  ~/cogos-backup-2026-08-14
```

导出为可读的 md/json/jsonl（不是二进制），`cogos import` 在任意机器还原。

## 文档

- 架构：`docs/architecture.md`、`docs/cognitive-architecture.md`
- 认知图谱 / 成长 / 检索 / 影响：`docs/cognitive-graph.md`、`docs/cognitive-growth.md`、
  `docs/cognitive-retrieval.md`、`docs/impact-integrity.md`
- 隐私与治理：`docs/privacy-remediation.md`、`docs/project-hygiene.md`
- 开发：`CONTRIBUTING.md`、`docs/development.md`

## 隐私边界

公开仓库只含代码、文档、合成 fixture 与 demo；`user/`（真实认知、对话、偏好、
trace）永不出现在 Git 与远程。本地优先，远程 embedding 需显式配置。
