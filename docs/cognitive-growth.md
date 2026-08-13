# CognitiveOS Cognitive Growth 设计（Phase 3A–3G）

> 本文件是 Phase 3 的唯一设计蓝图。原则：**Memory 增加 ≠ 认知成长**。
> 成长 = 从发生过的事情中提炼稳定规律，在未来任务中应用，并被验证、被用户感知、可被用户纠正。
> 配套：`cognitive-architecture.md`（运行闭环）、`cognitive-graph.md`（实体关系）。
> 状态：设计定稿前讨论稿。**未开始实现。**

---

## 0. 成功标准（先钉死）

```
User Behavior → Observation → Episodic Memory → Repeated Pattern
→ Candidate Knowledge/Preference/Rule → Verification → Semantic Memory
→ Future Retrieval → Agent Behavior 改变 → User 感知
```

Phase 2 证明了「CognitiveOS 能记住」。Phase 3 要证明 **CognitiveOS 会学习**：

- 系统能**提炼**（多条 episodic → 一条稳定认知，不是 N 条重复记忆）
- 系统能**验证**（认知被应用时真的改变 Agent 行为，且 verify 确认）
- 系统能**表达**（confidence + evidence，强规则和弱推测可区分）
- 系统能**接受纠正**（用户可确认/修改/忘记，纠正留痕）
- 用户能**感知**（时间线 + 影响指标，全部来自真实 trace）

---

## 1. Memory 分类学（Memory Taxonomy）

基于现有 schema 扩展。现有：`preference / rule / episodic / semantic / project_note`。新增：`candidate / temporary`。

| 类型 | 生命周期 | 权重 | 自动升级 | 自动删除 | 用户修改 | 进 Agent Context |
|---|---|---|---|---|---|---|
| **episodic** | 永久 append-only（可归档） | 证据源（自身低权重） | → candidate（聚合后） | 否 | 否 | 是（检索命中时） |
| **candidate** | 观察期（默认 30 天无新证据自动弃） | 中 | → semantic/preference/rule | 是（过期弃） | 是 | **否（默认不注入，只在 Dashboard 展示待确认）** |
| **preference** | 长期，可被 supersede | 高 | 已是顶端 | 否（只 supersede） | 是 | 是 |
| **rule** | 长期，可被 supersede | 最高（硬约束，带 forbidden/required，verify 执行） | 已是顶端 | 否（只 supersede） | 是 | 是 |
| **semantic** | 长期，可被 supersede | 高 | 已是顶端 | 否（只 supersede） | 是 | 是 |
| **project_note** | 随项目 | 中 | 否 | 随项目归档 | 是 | 按项目域 |
| **temporary** | **单次任务**（绑定 execution_id，任务结束自动失效） | 单次最高优先 | 否 | 是（自动失效） | 是 | 是（仅本次） |

**关键差异点**（回答"每个类型凭什么不同"）：

- `candidate` 是**系统形成的猜测**，默认不进 Context——它必须先被用户确认或通过验证，才升级为会注入 Agent 的认知。这防止"一次错误行为形成永久偏好"。
- `temporary` 是**任务级例外**——"这次可以用 SELECT *"不改变长期规则，任务结束即失效。
- `rule` 与 `preference` 的区别：rule 是**可执行约束**（forbidden/required 模式，verify 能判 PASS/FAIL）；preference 是**风格倾向**（无硬模式，靠语义判断）。

---

## 2. Confidence Model（认知置信度）

每个长期认知携带：

```json
{
  "status": "candidate | confirmed | superseded | suppressed",
  "confidence": 0.0-1.0,
  "evidence_count": 3,
  "last_observed": "2026-08-13T...",
  "source_executions": ["ex-...005", "ex-...007"],
  "user_confirmed": false,
  "version": 1
}
```

**置信度计算（确定性公式，不用 LLM 自评）**：

```
confidence = clamp( base + Σ evidence_weights + user_confirmed_bonus, 0, 0.99 )
base          = 0.30（candidate 起点）
evidence 权重：
  user 显式声明（source=user_statement）      +0.50 / 次
  执行中应用且 verify PASS（applied+verified） +0.15 / 次
  执行中应用但 verify AMBIGUOUS               +0.05 / 次
  普通观察（episodic 重复行为）               +0.10 / 次
user_confirmed_bonus = +0.70（人工确认后直接跃过阈值；置信度上限 0.99 留给"人确认且长期无冲突"）
```

**阈值**：

- `candidate`：confidence ∈ [0.30, 0.70)
- 自动升级为 `semantic/preference`：confidence ≥ 0.70 **且** evidence_count ≥ 3 **且** 有 ≥1 次 applied+verified
- 升级为 `rule`：额外要求 `user_confirmed=true` **或** ≥3 次 applied+verify PASS（硬约束必须更严）
- `temporary` 声明识别：语句含「今天/这次/暂时/临时/仅这次」→ classify 归 temporary（永不升级）

**诚实边界**：`confidence=0.42, evidence=2` 的弱推测和 `confidence=0.97, evidence=14, user_confirmed` 的强规则，在 Context 注入时以不同语气呈现——「用户偏好（强，7 次验证）」vs「系统推测（弱，仅供参考）」。Agent 必须能区分。

---

## 3. Promotion Model（升级生命周期）

```
Episodic (每次执行 append，永远)
   │  PatternDetector：按 (domain, 行为签名) 聚合
   ▼
Candidate (status=candidate, evidence=1, confidence=base)
   │  每次命中：evidence_count+1、confidence 按 §2 累加、last_observed 更新
   │  30 天无新证据 → 自动弃（status=superseded, reason=expired）
   ▼
Verified (status=confirmed)
   │  两种验证路径：
   │  a. 应用验证 — candidate 被注入后 agent 遵守且 verify PASS（自动）
   │  b. 用户确认 — Dashboard/CLI 的 [确认] 按钮（人工，最高信号）
   ▼
Semantic / Preference / Rule（类型由内容决定：含 forbidden/required → rule；
                           风格倾向 → preference；通用知识 → semantic）
```

**行为签名**（PatternDetector 的核心，确定性、无 LLM）：

- rule 型行为：episodic 关联的 rule 的 `forbidden` 集合相同时 = 同一候选（如 5 次任务都检出了 R-SQL-001 → 候选是"R-SQL-001 高频应用"→ 实为对已有规则的证据累积，不新建重复条目）
- preference 型行为：同 domain 内 episodic 的 `verdict` 与 refs 模式重复 N 次 → 提炼 candidate
- 提炼文本生成：**一次性 LLM 调用**把 N 条证据概括成一句话（`source_executions` 全量保留，可溯源）；LLM 只写 text，不判"是否该升级"——**是否升级由确定性阈值决定**。

**谁负责判断升级**：PatternDetector（确定性引擎）+ 阈值规则。LLM 不参与升级决策（防止"模型自己说我学到了"）。

**防误升级的护栏**：

1. 最小 evidence ≥ 3 次**独立执行**（同一次任务内的重复不算）
2. temporary 声明永不升级（§2）
3. verify FAIL 不计正证据（甚至 -0.05 削弱）
4. candidate 默认不进 Context——即使升级出错，也不会立刻影响 Agent 行为
5. 冷却期：candidate 创建后 ≥24h 才允许自动升级（防同一天刷 5 次同任务）

---

## 4. Conflict Model（冲突模型）

**冲突检测**（确定性）：同 domain 内，新认知与已确认认知矛盾——
- forbidden 交集：A 禁止 X、B 要求 X → 冲突
- 新用户声明与旧 confirmed 文本语义矛盾 → 标记冲突（语义判断允许一次 LLM 调用，结果只做标记）

**冲突表达**（不删除、不静默覆盖）：

| 场景 | 表达 |
|---|---|
| 永久偏好 vs 任务级例外 | `temporary` 条目绑定 execution_id，优先级高于 confirmed，任务结束自动失效 |
| 新偏好取代旧偏好 | `supersede` 链：旧条目 status=superseded（保留 + 溯源），新条目 version+1 |
| 冲突无法仲裁 | **不静默选择**——Context 同时呈现两条并标注「⚠ 认知冲突」，Dashboard 标红让用户裁决；默认取 confidence 高者但明确标注 |

**优先级（注入 Context 时）**：`temporary(本次) > confirmed(新版本) > confirmed(旧版本) > candidate(不进)`

---

## 5. Versioning（认知版本）

- 每条长期认知有 `version`（初始 1）。
- 修改 = 写新条目（version+1）+ `supersedes` edge 指向旧条目 + 旧条目 status=superseded。**不覆盖、不删除。**
- Preference History 视图 = 沿 `supersedes` 链回溯（edges 表已支持，零迁移）。
- 例：`2026-08-01 偏好 CTE → 08-10 简单查询用子查询 → 08-13 复杂查询才用 CTE`——三条都在，当前取最新，历史可追溯。

---

## 6. Semantic Retrieval Architecture（3C）

**保留 FTS5 不删**。混合检索架构：

```
Query
  ├─► KeywordRetriever  (FTS5 trigram + OR-of-terms，现有)      → 候选集 A
  ├─► EmbeddingRetriever(本地 embedding → 余弦相似度)            → 候选集 B
  ├─► MetadataFilter    (domain / type / status≠suppressed / confidence)
  ▼
Ranker：RRF 融合（Reciprocal Rank Fusion：score = Σ 1/(k+rank_i)）
  + confidence 加成（高置信认知排前）
  + recency 加成（现有）
  ▼
现有 build_context（4000 字符预算、分节 cap 不变）
```

**EmbeddingProvider 接口**（不写死模型）：

```python
class EmbeddingProvider(Protocol):
    name: str
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- **Local（默认优先）**：sentence-transformers 小模型（bge-small-zh，CPU 可跑，纯本地离线）。用户机器有 RTX 4070 + llama-server，后续可换本地 GPU embedding。
- **Remote（可选）**：任何 OpenAI 兼容 embedding API（MiniMax/OpenAI），用户显式配置才启用。
- 无任何 provider 时：**自动降级为纯 FTS5**（当前行为），系统必须完整可用。

**向量存储（轻量，无重型基础设施）**：SQLite 新表 `mem_vectors(ent_id PK, dim INT, vec BLOB)`——几千条数据暴力余弦扫描是毫秒级，不需要向量数据库。embedding 是**派生数据**：db 删除后 `cogos reindex` 重新计算（canonical 不含 embedding，永远可重建）。

---

## 7. Retrieval Ranking（排序融合）

最终分数 = `RRF(keyword_rank, semantic_rank) + 0.3×recency_boost + 0.2×confidence`

- 强确认规则（confidence 0.9+）在同类命中中天然靠前
- candidate 不进检索结果（§1）
- suppressed/rejected/superseded 默认过滤（metadata filter）

---

## 8. User Correction（3E，用户纠正系统）

**CLI**（新命令组 `cogos memory`）：

```
cogos memory list [--status candidate]     # 列出认知（默认只列 candidate + confirmed）
cogos memory show <id>                    # 含 evidence 链、置信度、版本历史
cogos memory confirm <id>                 # user_confirmed=true，confidence→0.97
cogos memory reject <id>                  # status=rejected，永不再注入（留痕）
cogos memory forget <id>                  # status=suppressed，同上（soft forget）
cogos memory modify <id> --content "..."  # supersede 链新增版本（不覆盖）
cogos memory why <id>                     # "为什么认为我喜欢这个？"——§9
```

**Dashboard**（静态 file:// 的诚实方案）：认知卡片带 `[确认] [修改] [忘记]` 按钮——点击**复制对应 CLI 命令到剪贴板**（静态页无法写文件，不假装能写；命令由用户执行或经未来本地服务执行）。每个动作都产生 trace 事件 `user_corrected`（审计留痕）。

**纠正后效果**：`rejected/suppressed` 状态被 MetadataFilter 排除 → 未来检索不再注入。

---

## 9. "Why did you think this?"（可解释证据链）

`cogos memory why <id>` 输出（全部来自真实 trace，不暴露模型内部推理）：

```
Inference:
你在过去 8 次 SQL 任务中，有 7 次应用了「不用 SELECT *」。

Evidence (source_executions):
ex-...002 应用 R-SQL-001，verify PASS
ex-...003 应用 R-SQL-001，verify PASS
...

Confidence: 87%（evidence 7 次 + 3 次 verify PASS）
```

实现：`source_executions` 引用 execution 表 + verifications 表 join——**全部是可验证的系统事件，无 CoT**。

---

## 10. Cognitive Impact（3G，最重要的指标）

**全部来自真实 Execution Trace 聚合，禁止硬编码**：

| 指标 | 定义（trace 事件） | 计算 |
|---|---|---|
| 自动应用用户偏好 | refs 含 preference/rule 的执行 | 计数 |
| 避免已知错误 | refs 含 rule 且 verdict=PASS | 计数 |
| 复用历史知识 | refs 含 episodic/semantic | 计数 |
| 形成新认知 | status 变更事件（candidate→confirmed） | 计数 |
| 用户纠正 | `user_corrected` 事件 | 计数 |

**单次执行的 Memory Impact**（不虚构百分比，只呈现可观察量）：

- retrieved N / applied N（被注入且 Agent 输出符合）/ verified PASS/FAIL
- 分级：High（applied≥1 且 verified PASS）· Medium（retrieved≥1）· Low（retrieved=0）

---

## 11. Evaluation Benchmark（3D）

`tests/fixtures/cognitive_cases.json`，每个 case：

```json
{
  "id": "case-sql-preference",
  "query": "写一个销售查询的 SQL",
  "expected_memory": ["R-SQL-001"],
  "forbidden_memory": [],
  "expected_behavior": "输出不含 SELECT *",
  "expected_context_contains": ["R-SQL-001"]
}
```

至少 8 类 case：SQL preference / Report preference / Formatting preference / Temporary exception / Conflicting preference / Repeated behavior / Unrelated memory / Project-specific memory。

**指标**（pytest 断言 + `cogos eval` 汇总）：
- **Recall@k**：expected_memory 是否在 top-k 结果中
- **Precision@k**：forbidden_memory 是否被排除、无关记忆占比
- **Ranking（MRR）**：expected 是否排第一

以后换 embedding/模型/检索策略，跑同一基准验证「CognitiveOS 有没有变差」。

---

## 12. Migration Strategy（迁移策略，保住 78 tests 与现有数据）

**原则：canonical 文件格式向后兼容；SQLite 是索引，可重建。**

1. **episodic.jsonl**：新字段（`status/confidence/evidence_count/last_observed/version`）仅对新写入的行生效；旧行读取时给默认值（status=episodic 原样，confidence=null）。**不迁移旧文件**。
2. **entities 表**：`ALTER TABLE entities ADD COLUMN status TEXT DEFAULT ''` 等 4 列（SQLite 加列安全，已存在的 db 自动迁移）。`cogos reindex` 重建一切。
3. **新表**：`mem_vectors`（向量）。旧 db 无此表 → reindex 时创建。
4. **edges**：`supersedes` 是新 rel 值，无需迁移。
5. **Golden Path 兼容性**：
   - `retrieve` 排序加 confidence 加成——现有测试断言 `rules=1`（summary 计数）不受影响；检索 cap 不变
   - `_learn` 写 episodic 加字段——现有断言读 `type/derived_from_execution` 字段，兼容
   - candidate 默认不进 Context——对现有注入路径零影响
   - classify 新增 temporary 分支（"今天/这次/暂时"）——现有 `以后...不允许` 测试不受影响
   - **78 tests 全部保持不动**；Phase 3 新增独立测试文件（test_growth.py / test_retrieval_eval.py / test_correction.py）

---

## 13. Phase 3A–3G 实现顺序与范围

| 阶段 | 内容 | 新增 | 复用 Phase 2 |
|---|---|---|---|
| **3A** Memory Lifecycle | status/confidence/evidence 字段、PatternDetector、promotion 阈值、candidate 类型 | `growth.py`（PatternDetector+阈值）、`cogos sleep`（离线提炼命令，类似 reflection 设计）、store 4 新列 | classify/extract_rule、kernel._learn 的 episodic 写入、edges |
| **3B** Conflict+Versioning | temporary 类型、supersedes 链、冲突检测+标记 | classify temporary 分支、`conflict.py` | edges 表、verify.judge |
| **3C** Semantic Retrieval | EmbeddingProvider 接口、Local bge-small-zh、mem_vectors 表、RRF ranker | `embedding.py`、retriever 混合层 | FTS5 检索、build_context 预算 |
| **3D** Evaluation | cognitive_cases.json、recall/precision/MRR 测试、`cogos eval` | fixtures + test_retrieval_eval.py | store.search 接口 |
| **3E** User Correction | `cogos memory` 命令组、status 过滤、user_corrected trace | `memory_cli.py` | store、trace、cli 注册模式 |
| **3F** Growth Dashboard | 认知卡片组 + Cognitive Timeline 区块 | dashboard 查询 + 模板区块 | 执行面板模式（真实数据投影） |
| **3G** Impact Metrics | trace 聚合指标 + 单次 Memory Impact | `impact.py` | executions/trace_events 表 |

**明确不做（防过度工程）**：多 Agent 自动进化、图数据库、云端强制依赖、"AI 成长评分"、无意义图表、全量历史塞 prompt。

---

*设计完。Phase 3 的目标一句话：让 CognitiveOS 从「记得住」走到「会学习、可纠正、可解释、可感知」。*
