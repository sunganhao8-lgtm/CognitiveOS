# CognitiveOS Technical Debt（2026-08-14）

## P0（必须修）

无。

## P1（建议修）

| # | 债务 | 影响 | 建议 |
|---|---|---|---|
| 1 | bge-small-zh-v1.5 短句语义区分度弱 | "帮我查销售数据" 类查询 recall 受限；短句 cosine 全挤在 0.4 附近 | 评估 bge-m3 / 重排模型（Phase 5 框架已就绪，数据集 50 queries 可复跑） |
| 2 | 检索误注入干扰项（FCR=0.005） | sql-007 场景"数据"命中"数据库备份"规则 | 阈值调优 + domain 加权；benchmark 已可量化每次改动 |
| 3 | 单发 CLI 无会话上下文 | temporary"下一次任务消费"语义依赖用户顺序 | 引入 session 概念（可选），或文档化使用模式 |

## P2（未来可修）

| # | 债务 | 说明 |
|---|---|---|
| 4 | 项目级 scope 自动检测仅关键词 | "这个项目…"关键词；真实项目绑定需更多信号 |
| 5 | dashboard serve 无鉴权 | 仅 127.0.0.1 绑定，无认证；本地单用户可接受，多用户需加 |
| 6 | stress 10k 全量 reindex 慢（预计 >2min） | 可增量索引；当前单用户规模（<100 认知）无影响 |
| 7 | `cogos run` 的 LLM 分类依赖 cogos-test profile 可用 | profile 缺失时回退关键词分类（已实现），但 LLM 语义分类不可用 |

## P3（暂不处理）

| # | 债务 | 理由 |
|---|---|---|
| 8 | 向量检索为暴力余弦 | 数据规模 <1 万条时毫秒级；达到瓶颈前不引入 FAISS |
| 9 | Dashboard Diagnostic 模式未拆分独立视图 | Human 首页已含详情区；等真实使用反馈 |
| 10 | 多 Agent 并行协作 | 任务书明确 Phase 4 之后再说 |
| 11 | Real-time sleep 调度 | cron 已覆盖（quota-watcher 模式），无需进程常驻 |
