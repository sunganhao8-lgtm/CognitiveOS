# CognitiveOS Cognitive Graph 设计（Phase 2A）

> 本文档定义 CognitiveOS 的实体、关系与存储。原则：**为了工作流而建模，不为了「Graph」而 Graph**。
> 每个实体必须能回答一个问题：它在实际 Agent 工作流中有什么作用？答不上来的实体不建。
> 配套：`cognitive-architecture.md`（运行闭环）。

---

## 0. 为什么需要这个图（用诊断报告的一句话回答）

当前系统「用户看到很多孤立功能」的根因是：**实体只以文件路径隐式存在，关系只存在于人脑里**。哪个 Agent 用了哪条 Memory、哪条 Rule 影响了哪次执行——机器答不上来。Cognitive Graph 的职责就是把「认知如何流动」变成**可查询的事实**。

---

## 1. 实体总表（每个实体 = 一个工作流作用）

| 实体 | 工作流作用 | 关键字段 | Canonical 位置 | 生命周期 |
|---|---|---|---|---|
| **User** | 认知系统的主人；所有认知的归属者 | id（固定 `u-master`）、name | `user/manifest.md` | 长期稳定 |
| **Preference** | 主人的长期稳定偏好——检索命中后**直接注入** Agent 上下文，约束 Agent 行为 | type=`preference`、domain、content、status | `user/memory/preferences.jsonl` + `user/preferences.md`（人工） | 冲突走 candidate/supersedes |
| **Memory**（含 Rule 子型） | 过去发生过什么（episodic）+ 提炼知识（semantic）+ 铁律（rule）——检索注入 + 铁律可被 verify 执行 | type、domain、content、source、refs、created_at | `user/memory/episodic.jsonl`、`user/rules/*.json` | episodic 只追加；rule 可被 supersede |
| **Knowledge** | 系统掌握的外部/环境知识（Agent 技能库白名单收割的沉淀） | agent_id、source_path、title、body | `knowledge/sources/`（raw 证据）+ db 索引 | 随 harvest 更新 |
| **Skill** | Agent 可以执行什么能力——注册后**可被检索、可被 trace 引用**（P1-2 修复：从「文件」升格为「一等公民」） | id（`<agent_id>:<skill_name>`）、name、description、provided_by | db 注册表（重建自 harvest） | 随 harvest 增删 |
| **Agent** | 谁执行任务 | agent_id、display_name、version、paths | db（discovery 结果） | 随 discovery 更新 |
| **Task** | 用户要求系统完成什么（**请求**，可被多次执行/重试） | id、intent、domain | db + trace 引用 | 创建后不变 |
| **Execution** | 一次实际执行（Task 的 1 次运行） | execution_id、task_id、agent_id、status、verdict、context_chars、时间 | `user/traces/<date>.jsonl`（canonical）+ db 投影 | append-only |
| **TraceEvent** | Execution 中实际发生了什么（每节点一步） | execution_id、step、detail、refs[]、ts | 同上 | append-only |
| **Result** | 最终产生什么 —— **Execution 的属性**（status/output/artifacts），不独立成实体 | — | 同 Execution | 随 Execution |
| **Verification** | 结果是否符合规则——**独立实体**（一条规则被多次验证，需要历史聚合） | execution_id、rule_id、verdict、detail | `user/verify/*.json` + db 投影 | append-only |

---

## 2. 关系模型

```
User ──owns──► Preference
User ──owns──► Memory
User ──owns──► Project
User ──triggers──► Task

Task ──triggers──► Execution          (1:N —— 同一任务可多次执行/重试)
Execution ──routed_to──► Agent
Execution ──retrieves──► Memory        (含 Preference / Rule 子型)
Execution ──retrieves──► Knowledge
Execution ──uses──► Skill
Execution ──has──► TraceEvent          (N 条，按 step 顺序)
Execution ──has──► Result              (属性，不建边)

Memory(episodic) ──derived_from──► Execution   (不是 Task！见修正 2)
Memory ──related_to──► Knowledge       (Phase 3 语义合并时建立；现在留接口)
Rule ──supersedes──► Rule              (规则冲突链)

Verification ──evaluates──► Execution
Verification ──checks──► Rule
Skill ──provided_by──► Agent
Knowledge ──sourced_from──► Agent
```

### 对用户原关系模型的三处修正（附理由）

| # | 原模型 | 修正 | 理由 |
|---|---|---|---|
| 1 | `Trace` 独立实体 | **Trace = TraceEvent 序列**，挂 Execution 下 | 「Trace」只是事件的聚合标签。独立节点零查询增益——你永远不会查「一个 trace」，你查「这次执行的第 3 步发生了什么」 |
| 2 | `Memory ──derived_from──► Task` | **Memory(episodic) ──derived_from──► Execution** | 记忆来自「实际发生的那次执行」（含失败重试、verdict），不是抽象的 Task。同一 Task 两次执行可能产生两条不同教训 |
| 3 | `Skill ──used_by──► Agent` | **Skill ──provided_by──► Agent**，另加 **Execution ──uses──► Skill** | 「谁拥有/注册这个技能」与「哪次执行用了它」是两个问题，一个边回答不了。前者回答「能力清单」，后者回答「可追溯性」 |
| 4 | Preference / Rule 独立实体 | **Memory 的 type 子型**（`preference`/`rule`/`episodic`/`semantic`） | 四者在检索、注入、溯源路径上同构——检索器对它们做同一套 FTS5 + cap + 打分。拆成独立表会让检索逻辑三倍复杂化。type 字段保留全部语义差异（rule 额外带 forbidden/required 供 verify 执行） |

---

## 3. 存储选型（为什么不用 Neo4j / 向量库）

**结论：SQLite（含 FTS5）+ JSON/JSONL + 文件系统。不引入任何外部基础设施。**

理由逐条对照本项目约束：

| 约束 | Neo4j / 向量库 | SQLite + FTS5 + 文件 | 判定 |
|---|---|---|---|
| 本地个人使用 | 需常驻服务/守护进程 | 单文件，进程内打开 | ✅ SQLite |
| 可移植（export/import） | 服务数据目录 + 版本 | 一个 `.db` 文件 + `user/` 目录 | ✅ SQLite |
| 可备份 | 需停机 dump | 直接复制文件 | ✅ SQLite |
| 可调试 | Cypher 学习成本 | `sqlite3` CLI / 直接读 JSONL | ✅ SQLite |
| 检索能力 | 向量语义检索强 | FTS5 BM25（关键词/短语）够 v0；语义检索 Phase 3 可选叠加，接口已留 | ✅ 够用 |
| 图查询需求 | 真图遍历 | 本项目图很小（<10⁵ 节点），关系表 join 完全够 | ✅ 够用 |
| 数据量 | — | 个人认知数据 < 几十 MB | ✅ 无压力 |

**图是「关系表」不是「图数据库」**——`edges` 表存 (from, rel, to)，dashboard 的知识图谱可视化直接 SELECT 即可，需要遍历时 Python 层 BFS（数据量下毫无性能问题）。

### 3.1 Schema 草案（`cognitive.db`）

```sql
-- 实体：id 全局唯一；payload 存类型特有字段（灵活、免迁移）
CREATE TABLE entities (
  id         TEXT PRIMARY KEY,          -- mem-<nanoid> | rule-R-SQL-001 | skill-hermes:xxx | ex-...
  type       TEXT NOT NULL,             -- user|project|memory|knowledge|skill|agent|task|execution|verification
  created_at TEXT, updated_at TEXT,
  payload    TEXT                       -- JSON
);

-- 关系：三元组 + 权重
CREATE TABLE edges (
  from_id TEXT NOT NULL,
  rel     TEXT NOT NULL,                -- owns|triggers|routed_to|retrieves|uses|has|derived_from|evaluates|checks|provided_by|sourced_from|supersedes|related_to
  to_id   TEXT NOT NULL,
  score   REAL, meta TEXT,
  PRIMARY KEY (from_id, rel, to_id)
);

-- 检索索引：内容全文 + 类型/域过滤
CREATE VIRTUAL TABLE mem_fts USING fts5(
  ent_id UNINDEXED, type, domain, text
);

-- 执行投影（写穿，供 Dashboard 秒查）
CREATE TABLE executions (
  execution_id TEXT PRIMARY KEY, task_id TEXT, agent_id TEXT,
  status TEXT, verdict TEXT, context_chars INTEGER,
  started_at TEXT, finished_at TEXT, payload TEXT
);
CREATE TABLE trace_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT, step TEXT, detail TEXT, refs_json TEXT, ts TEXT
);
CREATE TABLE verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT, rule_id TEXT, verdict TEXT, detail TEXT, ts TEXT
);
CREATE INDEX idx_exec_ts   ON executions(started_at DESC);
CREATE INDEX idx_event_ex  ON trace_events(execution_id);
CREATE INDEX idx_ver_rule  ON verifications(rule_id);
```

### 3.2 重建与一致性（核心不变量）

- **Canonical 永远是 `user/` + `knowledge/sources/`；db 是纯索引/投影。**
- `cogos reindex` 幂等重建：清空 entities/edges/mem_fts → 扫 `user/**`（md/jsonl/rules/traces/verify）→ 重建。
- Kernel 运行时的双写：canonical JSONL **先写、写完再写穿** db 投影——db 损坏只丢查询便利，不丢认知。
- 一致性验证命令：`cogos reindex --check`（对比 db 行数与 canonical 行数，不一致报警）。

---

## 4. 实体在 Golden Path 中的具体形态（落地即这个形状）

```
# 学习运行
cogos run "以后我的 SQL 全部不要使用 SELECT *"
  → entities:  +memory mem-sql-pref-001 {type:preference, domain:sql, content:"…"}
               +memory rule-R-SQL-001   {type:rule, domain:sql, payload:{forbidden:["SELECT *"]}}
  → edges:     User -owns→ both
  → trace:     ex-...-000001 (step=classify,remember)

# 执行运行
cogos run "帮我写一个查询最近订单的 SQL"
  → entities:  +task tk-..., +execution ex-...-000002
  → edges:     Task -triggers→ Execution
               Execution -routed_to→ Agent(hermes)
               Execution -retrieves→ rule-R-SQL-001   (score 2.1)
               Execution -has→ 8×TraceEvent
               Execution -has→ Result(attr)
               Verification -evaluates→ Execution
               Verification -checks→ rule-R-SQL-001
               Memory(episodic) -derived_from→ Execution
```

Dashboard 的「知识图谱」视图 = `SELECT edges WHERE from_id=<user> OR execution_id=<recent>` 的渲染。**零硬编码。**

---

## 5. 演进空间（现在不做，但 schema 不挡路）

- **语义检索**：`Retriever` 协议已抽象；Phase 3 可在 mem_fts 旁加 embedding 列 + 混合打分，不动 canonical。
- **语义合并**：episodic → semantic 的提炼（`related_to` Knowledge 的边已预留）。
- **多用户**：`User.id` 已是主键；payload 加 scope 即可，不动结构。
- **跨机同步**：`export-user` 打包 `user/`（含 traces/verify/memory），`import-user` 后 `reindex` 即可全量恢复认知与仪表盘。

---

*图设计完。所有实体都能回答「工作流作用」，所有关系都能回答「谁影响谁」。2B 按此建表。*
