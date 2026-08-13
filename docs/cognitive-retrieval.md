# CognitiveOS Retrieval Contract（Phase 3C Implementation Freeze）

> 本文件是 Phase 3C 的**实现契约**，冻结于 2026-08-13。实现以本文件为准；
> 若发现本契约与实现矛盾，先回来改本文件，不静默偏离。
> 设计讨论见 `cognitive-growth.md` §6（3C 章节，作为历史参考）。

---

## 0. 目标（一句话）

> 让 CognitiveOS 在当前 Task 上下文中，找到「相关、有效、有资格影响当前 Agent 行为」的认知。

**铁律：Semantic Similarity ≠ Cognitive Relevance。** 语义相似只是相关性的一路信号；
资格（eligibility）永远先行，优先级（priority）永远独立于相关性。

---

## 1. 输入（RetrievalRequest）

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_text` | str | 任务原文（必须） |
| `domain` | str | 任务域（"general" 表示未定） |
| `scope` | str | 任务所在 scope：global/project/task（默认 global） |
| `scope_id` | str | project id 或 execution id（可空） |
| `execution_id` | str | 当前执行 id（决定 temporary 资格） |
| `agent_id` | str | 路由目标 agent（可空，仅供记录） |

复用现有字段，不新增存储。

## 2. 输出（RetrievedItem）

| 字段 | 说明 |
|---|---|
| `memory_id` | 认知 id |
| `retrieval_method` | `keyword` / `semantic` / `hybrid` |
| `keyword_rank` | FTS5 通道内排名（无命中 = None） |
| `semantic_rank` | embedding 通道内排名（无 = None） |
| `similarity` | cosine（仅 semantic 通道有） |
| `rrf_score` | 融合分（hybrid） |
| `confidence` | 认知置信度（Priority 用，非 Relevance） |
| `scope` / `scope_match` | 认知 scope / 是否匹配任务 scope |
| `status` / `version` | 有效性快照 |
| `why_retrieved` | 人类可读的一句话理由（由各层组装） |

**每一条被注入的认知都必须能回答：「为什么它被找到？为什么它最终被注入？」**

## 3. 三层模型（顺序不可颠倒）

```
Task ──► ① Eligibility Filter ──► Candidate Set
              │
              ▼
         ② Relevance Ranking（keyword + semantic，RRF 融合）
              │
              ▼
         ③ Priority Ordering（scope + confidence + recency + confirmation）
              │
              ▼
         Final Top-K（喂给既有 build_context 预算分节）
```

### ① Eligibility（能不能进候选集——硬过滤，不是扣分）

| 状态/类型 | 处置 |
|---|---|
| candidate | **永远排除** |
| temporary | 仅当 `scope_id == execution_id` 或绑定当前任务才进（否则排除） |
| superseded / suppressed / rejected / expired | 排除 |
| conflicted | 不作为普通认知注入（单独作为 ⚠ 冲突段呈现，见 §6） |
| scope 不匹配 | 只影响 Priority（见 ③），不排除——global 认知对 project 任务仍然 eligible |

**Eligibility 在检索前执行**（先过滤，再打分）——绝不允许"全量 Top-K 后过滤"。

### ② Relevance（和任务相不相关）

- Keyword 通道：FTS5 trigram + OR-of-terms（现有行为不变），输出 `keyword_rank`。
- Semantic 通道：EmbeddingProvider 余弦相似度（本地优先），输出 `semantic_rank` + `similarity`。
- Hybrid 融合：**RRF**，`score = Σ 1/(k + rank)`，`k=60`。
  - 仅 keyword 命中：rrf = 1/(60+kw_rank)
  - 仅 semantic 命中：rrf = 1/(60+sem_rank)
  - 双通道命中：两者之和
- **confidence 不进入 Relevance**（它是 Priority 的调节项，不是相关性替代品）。

### ③ Priority（多个相关认知中谁优先）

按序比较（同一层级平局 → 下一层）：
1. `scope` 匹配度：任务 scope 精确匹配 > project > global（复用 3B SCOPE_RANK，不重定义）
2. `confidence`（只作为同 scope 内的次级排序）
3. `recency`（last_observed / created_at）
4. `user_confirmed`

## 4. 三个检索模式

```
A = keyword（FTS5 only）   —— provider 缺失时的保底模式
B = semantic（embedding only）
C = hybrid（FTS5 + embedding + RRF）—— provider 可用时的默认
```

`cogos run` / kernel 默认 **auto**：provider 可用 → hybrid；不可用 → keyword（行为与 Phase 2/3A/3B 一致）。

## 5. EmbeddingProvider 接口（冻结）

```python
class EmbeddingProvider(Protocol):
    name: str          # 模型标识（含维度隐含）
    dimension: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- **Local 优先**：默认 `fastembed` + `BAAI/bge-small-zh-v1.5`（CPU 可跑，离线，不上传任何用户数据）。GPU 后续可选。
- **Remote 可选**：仅显式配置（环境变量）才启用；默认禁止上传 user/ 数据；日志禁止输出 Memory 正文。
- **Fallback 链**（任何一步失败都降级，系统必须仍然可用）：
  ```
  remote timeout  → local
  local 模型加载失败 → FTS5 only（keyword 模式，且报告降级原因）
  无任何 provider → FTS5 only
  ```

## 6. Conflict / Temporary 在检索中的行为

- 冲突认知（status=conflicted）：**不作为普通条目注入**。若冲突双方都属于当前任务 relevant 集，Context 追加：
  ```
  ⚠ Cognitive conflict detected
  A: ...（scope/confidence/理由）
  B: ...
  ```
- Temporary：绑定当前 execution 的例外正常参与（scope 最高）；任务结束由 3B 逻辑过期。

## 7. Vector Storage（mem_vectors，Derived Data）

| 列 | 说明 |
|---|---|
| `entity_id` | 认知 id |
| `content_hash` | 内容 SHA256（变化即重算） |
| `embedding_model` | 模型标识 + 维度 |
| `vector` | BLOB（float32 小端） |
| `created_at` | 生成时间 |

- Embedding 是 **derived data**：`delete cognitive.db → cogos reindex → 检索功能与原先一致`（reindex 重算向量）。
- **model mismatch 检测**：现有向量模型与当前 provider 不一致 → 明确报告"需要 cogos reindex"，绝不静默混用不同模型的向量。
- 规模 ≤ 几千条：**SQLite 内存扫描 + 暴力余弦**，禁止引入 FAISS/Milvus/Qdrant/Weaviate/Neo4j。

## 8. Reindex 扩展顺序

```
canonical → entities → FTS5 → embeddings（若 provider 可用；不可用则跳过并记录）
```

## 9. Benchmark（评估标准，冻结）

测试集：`tests/fixtures/cognitive_cases.json`，8 类 case：
SQL preference / Report preference / Formatting preference / Temporary
exception / Conflicting preference / Repeated behavior / Unrelated memory /
Project-specific memory。

每 case：`{query, expected_memory[], forbidden_memory[], expected_context_contains[]}`。

指标：**Recall@5、Precision@5、MRR**——按模式分别报告（keyword / semantic / hybrid），逐 case 明细 + 均值。**Hybrid 没有提升必须如实报告，不得修改 benchmark。**

中文同义表达必须覆盖（写销售 SQL / 生成销售查询 / 查询销售明细…）；负样本必须不被检索（语义相似 > 0 不构成注入资格）。

## 10. 冻结边界（3C 禁止事项）

不实现：新 Memory Growth、新 Promotion/Conflict Policy、Dashboard 大改、Agent 自动进化、图数据库、云端强制依赖、CoT 记录、无限 Context。
可修 3A/3B 真实 bug，但不得重设计已冻结部分。
