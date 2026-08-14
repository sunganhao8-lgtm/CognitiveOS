# CognitiveOS Final Architecture Audit（2026-08-14）

> Phase 2–3G + Phase 4–11 全部完成后的事实审计。一切以代码为准。

## Current Architecture

```
user/ (Canonical) ──► Cognitive Store (SQLite + FTS5 + mem_vectors, derived)
      │                       │
      │        cogos sleep ──► growth.py（PatternDetector → Candidate → Promotion）
      ▼                       │
Kernel.run_input ──► classify → retrieve(3层) → context(budget 4000)
      │                      │
      ▼                      ▼
AgentAdapter(Hermes…) ──► verify(3阶段) ──► learn(episodic) ──► trace(append-only)
      │
      ▼
MemoryService（用户控制面）◄── CLI / Dashboard(ViewModel)
```

## Data Flow

1. 用户输入 → `classify`（关键词/LLM 三阶段）→ rule 声明直接结构化入库；
   task 继续。
2. task → `retrieve_ranked`（Eligibility 硬过滤 → keyword+semantic 双通道 RRF
   → Priority 排序）→ context_block（4000 字符预算、分节 cap、why_retrieved）。
3. Agent 执行（adapter，profile 隔离）→ `verify`（forbidden/required 检查，
   冲突规则 SKIPPED 语义）→ `_learn`（episodic + features 确定性提取）。
4. 每次执行全量 trace（execution/events/verifications，canonical JSONL + db）。
5. 离线：`cogos sleep` 幂等聚合 → candidate →（policy 判定）→ preference/rule；
   规则证据累积。
6. 用户控制：MemoryService confirm/reject/forget/modify（canonical+db 双写，
   user_corrected trace），纠正即时影响后续检索。
7. Dashboard：DashboardQuery 单次构建 ViewModel → 模板渲染（file:// 复制命令 /
   serve 模式真执行）。

## Cognitive Graph（实现态）

- 实体：User / Preference / Rule / Episodic / Candidate / Temporary / Semantic /
  Project(note) / Skill / Agent / Execution / Verification。
- 关系：owns、derived_from、promoted_from、supersedes、provided_by、uses、
  influences（refs）。
- 冲突：确定性 rule_rule（forbidden∩required）+ LLM 仅判语义冲突（不选 winner）；
  无仲裁 → conflicted，Context ⚠ 呈现。

## Memory Lifecycle

```
Episodic → PatternDetector（确定性签名）→ Candidate（永世不检索）
        → PromotionPolicy（evidence≥3 + verify≥1 + cool-down；rule 需
          user_confirmed 或 3×verify PASS）→ Preference/Rule（confirmed）
        → supersede 链（版本化，历史永不删）
        → reject/forget（suppressed/rejected + 指纹防复活；新显式声明可复活）
```

## Retrieval

- 三层分离（Eligibility / Relevance / Priority），RRF k=60，相似度阈值 0.5。
- 安全：candidate/temporary/superseded/rejected/conflicted 永不注入
  （benchmark 锁死，FCR=0.005 keyword / 同 hybrid，目标趋近 0）。
- Benchmark：50 queries × 12 类别；bge-small-zh-v1.5 数据驱动胜出
  （R@5=0.88 vs keyword 0.84，NDCG 0.686 vs 0.675）——保持现状，不因升级而升级。

## Agent Runtime

- AgentRegistry（harvested sources）+ AgentAdapter 协议 + Run Contract
  （execution_id/agent_id/task/context/result/verification/trace 全强制）。
- `cogos agent list/show/skills`、`cogos execution list/show`。

## Trace / Dashboard / Impact

- trace 事件 12 类；影响指标全部可追溯（learned 白名单 / retrieved / applied /
  verified / avoided 全链 / corrected），不变式测试锁死。
- Dashboard：Overview/Learning/Candidates/Conflicts/Corrections/Timeline/Brain/
  Health/Executions；Human 首页 + 数据详情。

## Security / Privacy

- 敏感扫描 CLEAN（sk-/token/private key/env/auth.json 零命中 tracked+demo）。
- `user/` 永不进 git；filter-repo 已清历史；canary 双层化；远程 embedding
  显式 opt-in。
- 本地优先：fastembed bge-small-zh-v1.5 CPU 离线，无 provider 自动降级。

## Testing / Migration / Performance

- 196 tests：unit/integration/golden path/migration/benchmark/stress(1k)/
  security/privacy/UI。
- Migration v1→v4 自动幂等，零丢失（测试）。
- Performance（本机 RTX 4070 Laptop）：
  - retrieval p50≈16ms(1k)/58ms(5k)/pending(10k)，p99≈34ms/87ms/pending
  - reindex 1000 条 ≈15s / 5000 条 ≈72s
  - sleep 1k ≈3.8s / 5k ≈0.03s（无新 pattern 时）

## Known Limitations（详见 technical-debt.md）

1. bge-small 短句语义区分度弱（"帮我查销售数据" cosine 0.43 < 阈值）。
2. Retrieval Waste 存在（keyword 误命中干扰项，FCR=0.005）。
3. 单发 CLI 无会话内多轮；temporary 语义靠"下一次任务消费"。
4. 项目级 scope 的自动检测仅关键词级。
5. 真实 14 天 Reality Test 尚未完成（协议已就绪，待真实使用数据）。
