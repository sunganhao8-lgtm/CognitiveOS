---
name: cogos-bridge
description: |
  让 DeepSeek Harness 拥有主人的偏好、规则、临时例外、纠正历史。所有
  认知读写都通过 `cogos` CLI（本地优先，不需要服务器接入）。Agent 只
  负责在合适的时机调它，并把 CognitiveOS 已经拼好的 Context 喂给模型。
version: 0.1.0
allowed-tools:
  - Bash
  - Read
---

# CognitiveOS Bridge（for DeepSeek Harness v0.1）

CognitiveOS 永远 **local-first**——它不"接进来"，Agent **主动调**
`cogos` CLI 去读写本地 `user/` 层。本 skill 只规定调用时机 + 接口约定。

## 一、什么时候必须调

每次用户给 Agent 一条指令，**先做一次** `cogos run`：

```bash
cogos run --json "用户的原话"
```

它会**自己判断**是 rule（声明偏好）/ task（普通任务）/ temporary（临时例外），不需要你分类。

返回 JSON 关键字段：
- `intent_type` — `rule` | `task` | `temporary` | `unsupported`
- `cognitive_context` — CognitiveOS 已经按主人偏好排好序的 Context，**Agent 直接喂给模型**
- `refs` — 注入了哪些偏好/规则（事后审计用）
- `verdict` — CognitiveOS 对 Agent 输出的判定（PASS / FAIL / SKIPPED / NO）
- `memory_impact` — 4 级状态：`NONE / RETRIEVED / APPLIED / VERIFIED`（Phase 3G 定义）

Agent **不要**自己再去拼 Context，不要抄 user/ 目录，不要假设偏好——`cognitive_context` 字段就是答案。

## 二、临时例外（自动生命周期）

用户说"这次 / 这次任务 / 本次允许 X"——直接 `cogos run`：

```bash
cogos run --json "这次允许用 SELECT *。"        # 声明临时例外
cogos run --json "帮我写销售 SQL。"             # 下一次任务
# → 临时规则 tmp-... 被绑定到本次执行
# → 原本冲突的 R-SQL-001 被 SKIPPED
# → 任务结束时 临时例外自动过期
```

Agent 不需要判断"是不是下一次"——`cogos` 自己管过期。

## 三、用户纠正

用户说"忘掉""不要这样""改成……"——**必须**立刻调：

```bash
cogos memory confirm <id>  # 系统推测对了
cogos memory reject  <id>  # 系统推测错了
cogos memory forget  <id>  # 不想再被应用
cogos memory modify  <id> --content "新版认知内容"
```

**不许靠脑记**。

## 四、用户问"为什么"

```bash
cogos memory why <id>
```

只回**证据**（几条 Execution + Verify PASS + 你确认过几次），不靠模型推理。

## 五、其他命令

```bash
cogos status           # 健康、embedding 模型、上次 reindex
cogos memory list      # 全部认知
cogos sleep            # 离线学习（幂等）
cogos dashboard build  # 生成 index.html
cogos dashboard serve  # 127.0.0.1:8787，按钮真实执行 confirm/reject
```

## 六、失败回退（Agent 必读）

- **`cogos` 不在 PATH**：提示用户 `pip install -e ./CognitiveOS`
- **`user/` 未初始化**：提示 `cogs init`（v0.2 才会有）
- **embedding 加载失败**：自动降级 FTS5 keyword only，**不退化就挂**——这是 Phase 3C 设计
- **Agent adapter 不可用**：stderr `"no agent adapters available"` → 提示用户在 `~/.cognitiveos/` 配 hermes/claude-code/codex 凭据

## 七、绝对不要做的事

- 不要上传 user/ 到云端（本机优先）
- 不要回放 CoT / 不要把 `cogos memory why` 的输出改成模型自己想的
- 不要把 `applied` 当 `verified` 当 `avoided`——三者是不同语义
  （Phase 3G impact integrity）