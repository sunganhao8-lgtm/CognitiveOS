# CognitiveOS 认知架构设计（Phase 2A）

> 本文档定义 **CognitiveOS 最小正确运行闭环** 与各节点契约。它是 Phase 2B（`cogos run` 实现）、2C（Dashboard 真实数据）、2D（测试）的唯一蓝图。
> 配套文档：`cognitive-graph.md`（实体与关系）、`privacy-remediation.md`（P0 隐私修复）。
> 状态：设计定稿前讨论稿。未开始大规模编码。

---

## 0. 定位重述（先钉死方向）

CognitiveOS 不是「一个存 Memory 的系统」，也不是「一个展示 AI 记忆的 Dashboard」。

它是一台 **本地 Agent Runtime**，承担一个 Agent 自己做不到的循环：

```
Observe ─► Remember ─► Retrieve ─► Apply ─► Execute ─► Verify ─► Learn ─►(回到 Observe)
```

每步都有**可验证的产物**（文件、行、trace 记录），每步都能被测试断言。Dashboard 只是这台引擎的仪表——先让引擎转起来，再让仪表显示真实读数。

**本阶段的三条铁律**：

1. **数据真实性原则**：UI 禁止硬编码 Memory/Skill/Rule/Execution 状态。可以保留 UI 布局、脑区图例、文案，但数据必须来自真实存储。
2. **最小 retrieval，禁止全量塞 prompt**：每次执行只注入 top-k 相关条目，且总字符数有硬预算。
3. **本地、可移植、可读、可调试**：存储 = 文件系统（canonical）+ SQLite（索引/投影），无外部服务。

---

## 1. 最小正确运行闭环

```
用户输入
   │
   ▼
① Observe/Classify ── 这是规则声明还是任务？
   │                    （关键词模式 → 不确定 → LLM 语义，三阶段）
   ├── 是规则/偏好 ──► ② Remember ──► ⑧ Trace ──► 结束（学习型运行）
   │
   └── 是任务
         ▼
③ Retrieve ── Memory / Knowledge / Skill / Project 各取 top-k（FTS5 + domain + 时效）
         ▼
④ Context Build ── 组装分节上下文块（总预算 4000 字符，可配）
         ▼
⑤ Execute ── 路由 → Agent Adapter → 生成结果（context_block 真正注入 prompt）
         ▼
⑥ Verify ── 相关规则三阶段判定（关键词 → AMBIGUOUS → LLM 语义）
         ▼
⑦ Learn ── 写 episodic memory；FAIL 则追加 lesson
         ▼
⑧ Trace ── 每一步的 TraceEvent + 一条 Execution 记录（append-only JSONL）
         ▼
⑨ Dashboard ── 只读索引库，渲染真实执行/检索/学习统计
```

---

## 2. 逐节点契约（输入 / 输出 / 存储 / 读写方 / 验证方式）

### ① Observe / Classify

| 问 | 答 |
|---|---|
| 输入 | 用户原始文本（`cogos run "<text>"`） |
| 输出 | `Intent{type: rule\|task, domain: str\|null, rule_payload: dict\|null}` |
| 存储 | 不落盘（进程内），分类结果进 Trace |
| 读方 | Kernel 分类器 |
| 写方 | 无 |
| 验证 | trace 记录 `classify.verdict` + 依据（keyword 或 llm_semantic）；规则声明场景：② 产生 memory_id |

分类策略（复用 verify 的三阶段哲学）：

- **第一层（免费，确定性）**：关键词模式。匹配 `^(以后|记住|别再|不要再用|我的[^\n]*(要|不要|别))` → rule；否则 task。显式前缀 `规则:` 强制 rule。
- **第二层（诚实）**：第一层不确定时判 `AMBIGUOUS`，不猜。
- **第三层（LLM 语义）**：AMBIGUOUS 时一次轻量 LLM 分类（JSON 输出 `{"type":"rule|task","domain":"..."}`）。LLM 不可用 → 按 task 处理并在 trace 记录 `classifier=fallback`。

**rule 的结构化提取**：判为 rule 时，一次 LLM 调用把声明转成结构化 Rule（`rule_zh` + `forbidden[]` / `required[]`），落 `user/rules/R-xxx.json`——**与 `cogos verify` 现有规则 schema 完全统一**（现有 `R-DECISION-001.json` 即为实例）。LLM 不可用时存原文、patterns 留空、标记 `raw=true`。

### ② Remember

| 问 | 答 |
|---|---|
| 输入 | 结构化 Rule / Preference 条目 |
| 输出 | `memory_id`（如 `mem-<nanoid>` 或 `rule-<id>`） |
| 存储 | canonical：`user/rules/R-xxx.json`（规则）+ `user/memory/preferences.jsonl`（偏好条目） |
| 读方 | ③ Retriever（通过索引） |
| 写方 | Kernel（仅规则声明路径；人工编辑的 md 文件同样是 canonical） |
| 验证 | 文件行数 +1；trace 记录 `memory_written:[id]` |

**冲突处理**：新规则与旧规则同域冲突时，新条目 `status=candidate`，旧条目 `supersedes` 指向新条目——由 `cogos verify` 或人工确认后转 `confirmed`。绝不静默覆盖。

### ③ Retrieve

| 问 | 答 |
|---|---|
| 输入 | `task.intent` + `domain`（如有） |
| 输出 | `RetrievedSet{preferences:[], memories:[], skills:[], knowledge:[], projects:[], rules:[]}`，每项带 `id + score + type` |
| 存储 | 读：SQLite FTS5 索引（`cognitive.db`，可重建） |
| 读方 | Kernel（Retriever） |
| 写方 | `cogos reindex`（索引重建，幂等） |
| 验证 | trace 记录每类命中数 + 每个 id + score；2D 测试断言「写入的偏好下次能被检索到」 |

v0 检索 = **FTS5 BM25 + domain 标签匹配 + 时效加成**（`score = bm25 * domain_match * recency_boost`，recency = `1 + 0.3 * exp(-age_days/30)`）。**不做 embedding**（Phase 3 可选升级，接口预留 `Retriever` 协议）。

每类 cap（默认）：preference ≤ 2、rule ≤ 2、memory ≤ 4、skill ≤ 2、knowledge ≤ 2、project ≤ 1。

### ④ Context Build

| 问 | 答 |
|---|---|
| 输入 | `RetrievedSet` + task |
| 输出 | `ContextBlock{text: str, refs: [{type,id,score}], truncated: bool}` |
| 存储 | 不落盘；text 与 refs 进 Trace |
| 读方 | ⑤ Adapter（消费 text） |
| 写方 | Kernel（ContextBuilder） |
| 验证 | trace 记录 `context_chars`、各节条目数、`truncated` 标记 |

分节格式（Agent 最终收到的 SYSTEM CONTEXT）：

```
[SYSTEM CONTEXT — CognitiveOS 检索结果，按相关性排序]
## 相关用户偏好
- (mem-xxx) …
## 相关规则
- (rule-xxx) …（含 forbidden/required 模式）
## 相关记忆
- (mem-yyy) …
## 相关技能
- (skill-z) …
## 相关项目上下文
- …
[/SYSTEM CONTEXT]

[TASK]
<用户任务原文>
```

**预算**（总 ≤ 4000 字符，`COGOS_CONTEXT_BUDGET` 可调）：偏好 600 / 规则 600 / 记忆 1600 / 技能 600 / 知识 600 / 项目 400。超预算按 score 从低到高截断，trace 记录 `truncated=true`。**永不全量注入。**

### ⑤ Execute

| 问 | 答 |
|---|---|
| 输入 | `ContextBlock.text` + `task` |
| 输出 | agent 文本 + `exit_code + elapsed` |
| 存储 | 输出进 Result（内存）→ Trace |
| 读方 | AgentAdapter（消费 context block） |
| 写方 | Agent 自身（`hermes chat -q` 子进程，timeout 120s） |
| 验证 | exit code、elapsed、输出非空；trace 记录 `agent_id` |

路由 v0：保留 `DomainRouter`（domain_map → 默认第一个 adapter）。Hermes 是唯一实现 execute 的 adapter。

### ⑥ Verify

| 问 | 答 |
|---|---|
| 输入 | Result 文本 + ③ 检出的 rules（`forbidden/required` 模式） |
| 输出 | `verdict: PASS\|FAIL\|AMBIGUOUS` + detail |
| 存储 | canonical：`user/verify/<ts>_<rule-id>.json`（沿用现有） |
| 读方 | ⑦ Learn、⑨ Dashboard |
| 写方 | Kernel（复用 `verify.judge` + `semantic_judge`） |
| 验证 | verdict 进 trace；verification 行入库 |

**三阶段判定沿用现有实现**（`src/cogos/verify.py`，这是项目里最正确的模块）：forbidden 命中 → FAIL；required 缺失 → AMBIGUOUS → LLM 语义判定；LLM 不可用 → 诚实报 AMBIGUOUS。**只对 ③ 检出的相关规则做验证**（不做全量规则扫描——那是不必要的开销）。

### ⑦ Learn

| 问 | 答 |
|---|---|
| 输入 | Result + verdict + ③ 的 refs |
| 输出 | episodic memory id（+ lesson id，若 FAIL） |
| 存储 | canonical：`user/memory/episodic.jsonl` |
| 读方 | 下次运行的 ③ Retriever |
| 写方 | Kernel |
| 验证 | trace 记录 `learning:[id]`；2D 测试断言执行后产生新 memory |

episodic 条目 = `{task 摘要, agent_id, verdict, 引用的 memory/rule/skill ids, 时间}`。FAIL 时追加 lesson 条目（关联 rule id），供未来检索「这个雷踩过」。语义合并（多条 episodic → 一条 semantic）是 Phase 3 能力，Phase 2B 只留字段。

### ⑧ Trace（一等公民）

| 问 | 答 |
|---|---|
| 输入 | ①②③④⑤⑥⑦ 各节点的结构化事件 |
| 输出 | Execution 记录 + N 条 TraceEvent |
| 存储 | canonical：`user/traces/<YYYY-MM-DD>.jsonl`（append-only）；投影：`cognitive.db.executions/trace_events`（写穿，可重建） |
| 读方 | ⑨ Dashboard、`cogos status` |
| 写方 | Kernel（每节点一步，边执行边 append，崩溃不丢已写事件） |
| 验证 | 每次 `cogos run` 必产生 `execution_id`；2D 测试断言 trace 文件存在且含全部 step |

**执行 ID 格式**：`ex-20260813-000123`（日期 + 当日序号）。

**Trace 只记录可观察的系统事件**——记录「检索了哪条 memory、用了哪个 skill、verdict 是什么」；**绝不记录模型内部 Chain-of-Thought**。

```json
{"type":"execution","execution_id":"ex-20260813-000123","task":"帮我写一个SQL","agent_id":"hermes",
 "status":"success","verdict":"PASS","context_chars":812,"started_at":"...","finished_at":"...",
 "memory_written":["mem-abc"],"refs":[{"type":"preference","id":"mem-sql-001","score":2.1}]}
{"type":"event","execution_id":"ex-20260813-000123","step":"retrieve","detail":"preferences=1 rules=1 memories=0 skills=0",
 "refs":[{"type":"preference","id":"mem-sql-001","score":2.1},{"type":"rule","id":"R-SQL-001","score":1.8}],"ts":"..."}
```

---

## 3. Memory 生命周期（完整回答六问）

| 阶段 | 设计 |
|---|---|
| **写入时机** | ① 规则/偏好声明（classify=rule → ②）② 每次执行结束（⑦ episodic）③ verify FAIL（lesson）④ 人工编辑 `user/*.md` / `user/memory/*.jsonl`（永远有效，最高权威） |
| **分类** | `preference`（长期稳定偏好）/ `rule`（铁律，带 forbidden/required，可被 verify 执行）/ `episodic`（发生过什么，append-only）/ `semantic`（提炼知识，Phase 3）/ `project_note`（项目 tacit knowledge，人工） |
| **检索** | FTS5 + domain + 时效（§2-③）；规则条目天然携带模式，供 ⑥ 直接执行 |
| **注入** | ④ ContextBlock 分节注入，硬预算 4000 字符，截断留痕 |
| **验证影响** | trace 的 `refs` 记录每条被注入的 memory id → Dashboard 显示「本次应用了 N 条偏好/规则」→ ⑥ 对规则做真验证（PASS/FAIL） |
| **更新** | preference/rule：冲突 → candidate/supersedes 链，人工或 verify 确认；episodic：只追加；semantic：合并去重（Phase 3） |

---

## 4. 三套存储的归宿（Canonical Source of Truth）

**不做粗暴删除，每套存储分配明确角色**：

| 层 | 位置 | 角色 | 谁写 | 丢了怎么办 |
|---|---|---|---|---|
| **Canonical** | `user/`（md 人工 + memory/*.jsonl + rules/*.json + traces/*.jsonl + verify/） | **唯一事实源**。人可读、grep 可查、随 export/import 迁移 | 用户手写 + Kernel 显式命令 | 不可丢。这就是主人认知 |
| **Index** | `.cogos/cognitive.db`（SQLite：FTS5 + 实体/关系/执行投影表） | 检索索引 + 图查询 + Dashboard 数据源 | `cogos reindex` 重建；Kernel 写穿执行/验证投影 | 可随时 `cogos reindex` 从 canonical 重建 |
| **Snapshot** | `knowledge/sources/` | Agent 环境原始快照（skills 白名单收割），skill 注册表的**原始证据** | bootstrap harvest | 可重新收割 |
| **Projection** | `index.html` | 纯渲染产物 | bootstrap / dashboard 渲染 | 可随时重新生成 |
| **Cache** | `.cogos/last_report.json` 等 | 运行缓存 | bootstrap | 无关紧要 |
| **废弃** | `.cogos/memory.jsonl`（Kernel FileMemory） | 被 `user/memory/*.jsonl` + traces 取代 | 迁移脚本一次性搬入后删除 | — |

关键结论：

- `knowledge/` **不再是一套平行宇宙**——它是 skill/agent 注册表的 raw 证据链；检索时 skill 条目来自注册表（db），溯源指回 sources。
- `.cogos/memory.jsonl` 的既有内容（如存在）一次性迁入 `user/memory/episodic.jsonl` 后废弃。
- Dashboard 从此只读 Index 层，与 Canonical 之间只隔一次 `reindex`，**零硬编码**。

---

## 5. Kernel 修复设计（P0-2 / P0-3 的对策）

### 5.1 入口

```
cogos run "<用户输入>"            # 全自动闭环
cogos run --list                  # 最近 N 次执行（读投影表）
cogos reindex                     # 从 user/ 重建 cognitive.db（幂等）
```

CLI 新增 `run` 命令组（`cli.py` 加 `p_run = sub.add_parser("run")`），`run_run(args)` 调用 `Kernel.run(user_input)`。

### 5.2 Kernel 接口调整（保持协议，扩展 Context）

```python
@dataclass
class Context:                    # 现有 Context 扩展
    task: Task
    memory_entries: list
    context_block: str = ""       # 新增：④ 组装好的分节文本
    refs: list = field(default_factory=list)  # 新增：引用清单（喂给 trace）

class Kernel:
    def run(self, user_input: str) -> Result: ...
    # 内部：classify → remember? → retrieve → build context → route
    #       → execute → verify → learn → trace(全程)
```

**不变的**：MemoryProvider / Router / AgentAdapter 三个协议继续存在（subsystem 可插拔是 DEC 的核心价值）。**变的**：Kernel 由「接受预构造 Task」改为「接受用户原文」；Context 携带真正可注入的 `context_block`。

### 5.3 HermesAdapter 修复（P0-2 核心）

当前 bug：`execute()` 只用 `task.intent/domain/required_memory` 拼 prompt，**从不使用 `context.memory_entries`**（`adapter.py:107-113`）。

修复：`execute(task, context)` 改为消费 `context.context_block`：

```python
prompt = (
    f"[COGNITIVEOS SYSTEM CONTEXT]\n{context.context_block}\n[/SYSTEM CONTEXT]\n\n"
    f"[TASK]\n{task.intent}\n\n"
    f"基于以上上下文完成任务。若上下文为空，按常识执行。"
)
```

明确拒绝的反模式：`prompt += str(all_memory)`。预算与截断在 ④ 完成，adapter 只做「注入」。

---

## 6. Golden Path（2B 的验收场景，也是 §十七 的 Test 1–7）

```
# Test 1-2 学习 + 检索
$ cogos run "以后我的 SQL 全部不要使用 SELECT *"
  → classify: rule (关键词命中"以后...不要")
  → remember: user/rules/R-SQL-001.json {rule_zh:"SQL 不使用 SELECT *", forbidden:["SELECT *"]}
  → trace: ex-...-000001 (step=classify/remember)
  → 输出: 已记住规则 R-SQL-001

# Test 3-4-5 注入 + 验证 + 展示
$ cogos run "帮我写一个查询最近订单的 SQL"
  → classify: task (domain≈sql)
  → retrieve: R-SQL-001 命中 (FTS5 匹配"SQL")  ← Test 2
  → context: SYSTEM CONTEXT 含 R-SQL-001 原文  ← Test 3
  → execute: hermes 生成 SQL
  → verify: judge(forbidden=["SELECT *"]) → PASS/FAIL
  → trace: refs=[{rule, R-SQL-001}]            ← Test 4
  → dashboard: "本次任务应用了 1 条规则 (R-SQL-001)"  ← Test 5

# Test 6 学习
  → learn: user/memory/episodic.jsonl 追加 1 条  ← Test 6

# Test 7 持久化
$ 重启/新开终端 → cogos reindex → 数据仍在         ← Test 7
```

**这个闭环全部由真实文件与真实 trace 支撑，没有任何一处 UI 常量。**

---

## 7. 与现有代码的映射（Phase 2B 施工清单）

| 现有文件 | 处置 |
|---|---|
| `kernel.py` | 改造：`run(user_input)`、classify/retrieve/context/trace 步骤；保留协议 |
| `verify.py` | **复用** judge/semantic_judge/load_rules（⑥ 直接调）；新增 rule 结构化提取辅助 |
| `cli.py` | 新增 `run`/`reindex` 命令组 |
| `adapters/hermes/adapter.py` | 修复 execute 消费 context_block |
| 新增 `src/cogos/classify.py` | 三阶段意图分类 |
| 新增 `src/cogos/retrieve.py` | FTS5 检索 + cap + 时效加成 |
| 新增 `src/cogos/store.py` | cognitive.db 管理（schema/reindex/写穿/查询） |
| 新增 `src/cogos/trace.py` | Execution/TraceEvent 落盘（JSONL 写穿 + db 投影） |
| `dashboard.py` | 2C：REGIONS 降级为「脑区图例」，记忆/规则/执行数据改读 store |
| `.cogos/memory.jsonl` | 一次性迁移后废弃（FileMemory 保留为协议测试桩） |
| `user.py` | 扩展 memory/traces 子目录 |

---

## 8. Phase 2B/2C/2D 范围与明确非目标

**2B（本轮之后进入）**：上述映射表全部落地 + Golden Path 跑通 + `cogos reindex`。
**2C**：Dashboard 改读真实数据（当前任务/Agent/Status、检索统计、技能、Execution ID、verdict、新增 memory 数）；脑区图保留为图例。
**2D**：六个测试——memory retrieval / memory injection / kernel run / execution trace / dashboard real-data / golden path 集成。

**明确不做（防过度工程）**：

- ❌ 不做 embedding / 向量库（接口留好，Phase 3 再说）
- ❌ 不做语义自动合并（semantic memory 只留字段）
- ❌ 不做多用户 / 多租户
- ❌ 不做 Agent 并发执行（单进程，DEC-007）
- ❌ 不做视觉重设计（§十三：数据真实 > 好看）
- ❌ 不记录模型内部推理（只记录可观察系统事件）

---

*蓝图完。实现 2B 时本文件与 `cognitive-graph.md` 是唯一权威；任何实现与本设计冲突，先回来改设计。*
