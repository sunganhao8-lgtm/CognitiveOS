# CognitiveOS 开发文档

面向开发者：Runtime / Store / Memory / Trace / Retrieval / Testing /
Migration / Dashboard / Privacy 各部分的工作方式。

## Runtime（src/cogos/kernel.py）

`Kernel.run_input(user_input)` 是唯一入口，完整认知闭环：

```
classify → (rule: 记住并结构化) | (task: retrieve → context → route →
execute → verify → learn) → trace
```

- `classify.py`：三阶段意图分类（关键词 → AMBIGUOUS → LLM 语义），规则结构化提取。
- 所有 hermes 子进程调用隔离在 `cogos-test` profile（`--profile` 顶层参数，
  `--reasoning none` 禁 CoT 输出）。

## Store（src/cogos/store.py）

SQLite + FTS5(trigram) + JSONL 投影。**db 是派生索引，`cogos reindex`
从 canonical 全量重建**（含 embeddings）。Schema 版本化迁移：
`SCHEMA_VERSION` 常量 + `_migrate()`（ALTER TABLE 增量，幂等）。
`mem_vectors` 存 embedding（派生数据，可重建，model mismatch 检测）。

## Memory（src/cogos/growth.py + memory_service.py）

- canonical 文件：`user/rules/*.json`、`user/memory/{episodic,candidates,
  preferences,temporary,rejections}.jsonl`。
- Growth：sleep 周期内 PatternDetector（确定性签名聚合）→ candidate →
  PromotionPolicy（集中、可测试）→ preference/rule。LLM 只提炼文本，不判升级。
- 用户控制面 = MemoryService（confirm/reject/forget/modify/why/card），
  CLI 与 Dashboard 都只走它。

## Trace（src/cogos/trace.py）

append-only JSONL（`user/traces/<date>.jsonl`）+ db 投影。每个执行有
`ex-YYYYMMDD-NNNNNN`，睡眠有 `slp-`，用户操作有 `usr-`。
事件：execution_started / task_classified / memory_retrieved / context_built /
agent_selected / agent_executed / verification_completed / memory_written /
user_corrected / execution_completed。

## Retrieval（src/cogos/retrieve.py）

三层：Eligibility（硬过滤）→ Relevance（keyword FTS5 + semantic cosine 独立
通道，RRF k=60 融合）→ Priority（scope > confidence > confirmation）。
每个 RetrievedItem 带 why_retrieved。EmbeddingProvider 协议见
`embedding.py`（本地 fastembed bge-small-zh-v1.5，无 provider 自动降级 keyword）。

## Testing

- 分层：unit（test_*.py）/ integration / golden path（test_golden_path.py）/
  migration（test_backup.py v1→current）/ benchmark（test_retrieval_benchmark.py
  50 queries）/ stress（test_stress.py 1k；scripts/stress_test.py 5k/10k）/
  security & privacy / UI（test_dashboard_cognitive.py）。
- 恒等约束：`applied ≤ retrieved`、`verified ≤ applied`、`avoided ≤ verified`
  （test_impact_integrity.py）。
- fixture 全合成（tests/fixtures/），与真实 user/ 严格隔离。

## Migration

- db schema v1→v4 全自动（_migrate 幂等）；旧数据零丢失（有测试）。
- 认知迁移：user/ 是 canonical，跨机器用 `cogos export/import`（可读格式）。

## Dashboard

- `dashboard_query.py` 单次构建完整 ViewModel；模板只渲染。
- 两种模式：file://（按钮复制 CLI）与 `cogos dashboard serve`（127.0.0.1，
  按钮经 MemoryService 真执行）。
- 指标定义冻结在 `docs/impact-integrity.md`——数字必须可追溯，禁止虚构。

## Privacy

- 真实敏感词只存本机 `.cogos/sensitive_patterns.json` 与 GitHub Secret
  `COGOS_PRIVACY_PATTERNS`；公开仓库仅结构性 canary。
- `user/` 永不提交；demo 全合成；日志禁 CoT/凭据。
- 远程 embedding 需三环境变量显式开启（见 embedding.py）。
