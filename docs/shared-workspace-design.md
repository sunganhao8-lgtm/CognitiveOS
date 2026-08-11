# CognitiveOS 多 Agent 共享工作目录设计方案

## 目标

实现"多个 Agent（Claude Code / Codex / Hermes / MiniMax Code）同时工作在一个共享工作区，
互相感知进度、互相审查代码、同一 PR 内协作"的能力。

对应场景（用户原话）：
> 前一秒在 Claude Code 说改代码，后一秒在 Hermes 问进度 → Hermes 答"Claude Code 正在改，
> 进度 50%，在改页面效果"→ 用户让 Hermes 审查 Claude Code 改的代码 → 发现问题直接让
> Claude Code 修改 → 两个 Agent 同时掌控进度 → 修改互相可见（因为在一个 PR 里）。

## 核心机制（3 层）

### 第 1 层：共享工作目录（Shared Workspace）

所有 Agent 的工作目录指向**同一个根**：

```
<SHARED_ROOT>/                    e.g. D:\GitHub_Project\SharedWorkspace\
├── .cogos/                       ← CognitiveOS 状态（进度、锁、消息）
│   ├── tasks/                    ← 任务注册表（每个任务一个 json）
│   ├── locks/                    ← Agent 互斥锁（同一文件只一个 Agent 写）
│   └── messages/                 ← Agent↔Agent 消息队列（mailbox）
├── <repo1>/                      ← 实际项目仓库（git）
├── <repo2>/
└── ...
```

关键点：
- **所有 Agent 用同一个 git 仓库**（同一个 `.git`），这是"一个 PR 里协作"的基础
- CognitiveOS 在 `.cogos/` 下维护**任务状态 + 锁 + 消息**，这些是 git 之外的运行时状态
- Hermes/Codex/Claude Code 通过环境变量 `COGOS_WORKSPACE` 获知共享根

### 第 2 层：任务注册表 + 进度追踪（Task Registry）

```json
// .cogos/tasks/TASK-001.json
{
  "id": "TASK-001",
  "title": "修改首页布局效果",
  "assignee": "claude_code",          // 哪个 Agent 在执行
  "status": "in_progress",            // pending / in_progress / review / done
  "progress": 50,                     // 0-100，由执行 Agent 上报
  "current_file": "src/index.html",   // 正在改的文件
  "branch": "feature/homepage-fix",   // git 分支
  "pr_url": "https://github.com/.../pull/12",
  "updated_at": "2026-08-10T18:00:00Z",
  "history": [
    {"t": "2026-08-10T17:55:00Z", "msg": "claude_code: 开始任务"},
    {"t": "2026-08-10T17:58:00Z", "msg": "claude_code: 完成布局重构，进度 50%"}
  ]
}
```

- **Hermes 问"进度如何"** → 读 `tasks/` → 回答"Claude Code 正在改，50%，在改 index.html"
- **Hermes 审查** → 读任务 + git diff → 给出审查意见
- **Agent 上报进度** → 写 `tasks/TASK-001.json`（用文件锁防并发写坏）

### 第 3 层：跨 Agent 消息队列（Mailbox）

```json
// .cogos/messages/TO_claude_code/2026-08-10T18-01-00.json
{
  "from": "hermes",
  "to": "claude_code",
  "type": "review_request",       // review_request / fix_request / progress_query
  "task_id": "TASK-001",
  "content": "请查看 src/index.html 的改动，顶部导航被遮挡了",
  "attachments": ["git diff --stat"]
}
```

- **每个 Agent 有自己的收件箱目录**（`TO_<agent_id>/`）
- Agent 启动时/定期检查收件箱，处理 `review_request` / `fix_request`
- Claude Code 可以用 `claude -p --append-system-prompt "检查 .cogos/messages/TO_claude_code/ 的新消息"` 主动处理

## 各 Agent 接入方式

| Agent | 工作目录共享 | 执行方式 | 状态上报 | 收信 |
|---|---|---|---|---|
| Hermes | 天然支持（cogos 就在项目里） | cogos CLI | `cogos task update` | `cogos inbox check` |
| Claude Code | `claude -p` + `--dangerously-skip-permissions`（受限） | adapter | 任务完成后由 CognitiveOS 扫描 git log 自动更新 | 启动时注入收件箱检查 |
| Codex | `codex exec --workdir <shared>` | adapter | 同上 | 同上 |
| MiniMax Code | **有 GUI，无 CLI** → 只共享磁盘目录，对话不落本地 | 暂无执行通道 | 无法自动上报（GUI 手动） | 无法自动收信 |

## 进度追踪的两种模式

1. **主动上报**（Hermes）：Agent 调 `cogos task update TASK-001 --progress 60 --note "改了侧边栏"`，精确
2. **被动推断**（Claude Code / Codex）：CognitiveOS 定时扫 `git log` + 工作区文件改动时间，推断"这个 Agent 刚动了哪些文件、进度到哪"——**零侵入**

## 锁机制（防两 Agent 写同一文件）

- 写文件前：`cogos lock acquire <repo>/<file>` → 写 `.cogos/locks/<repo>/<file>.lock`
- 写完：`cogos lock release`
- 冲突检测：两个 Agent 同时改同文件 → 后到者收到 `LOCK_CONFLICT` 消息
- 简单实现：基于文件 mtime + git 状态，不引入分布式锁

## 实施阶段

- **P0（基础）**：`cogos workspace init` 建共享目录骨架 + `cogos task` 命令（create/update/list/show）+ `cogos inbox` 命令（send/check）——Hermes 先接入
- **P1（被动追踪）**：`cogos workspace scan` 扫 git log 推断各 Agent 进度 → dashboard 显示"各 Agent 当前在做什么"
- **P2（Claude/Codex 接入）**：adapter 加 `--workdir` + 启动时收件箱注入；完成时自动更新任务状态
- **P3（PR 级协作）**：任务注册表加 PR URL；Hermes 审查指令自动变成 `review_request` 消息发到 Claude Code 收件箱；git 分支策略（每任务一分支，一个 PR）

## 风险与对策

| 风险 | 对策 |
|---|---|
| 两 Agent 写同一文件 | 文件锁 + 冲突检测消息 |
| MiniMax Code 无 CLI 无法自动化 | 接受限制：它作为"人工参与型 Agent"，共享目录可手动同步；对话不落本地的事实记录进 knowledge base |
| Claude Code 额度/权限 | 用 `--output-format text` + 受限权限，配额由 cron 监控 |
| git 冲突 | 每个任务一个分支 + 独立 PR（用户要求"在一个 PR 里"则用同一分支 + 顺序提交） |
| 消息丢失 | mailbox 是持久文件，Agent 离线也能收（下次启动检查） |
