# Contributing to CognitiveOS

## 开发指南（完整版见 docs/development.md）

### 结构速览

- `src/cogos/` — Runtime：kernel（认知闭环）、store（SQLite+FTS5 派生索引）、
  growth（睡眠/晋升）、conflict（冲突/版本）、retrieve（三层检索）、
  memory_service（用户控制面）、dashboard_query（ViewModel）、trace（执行链）
- `user/` — Canonical 主人层（本地私有，永不提交）
- `tests/` — 分层测试（unit / integration / golden path / migration /
  benchmark / stress / security / privacy / UI）

### 规则

1. **Canonical 是唯一事实源**：db 可删可重建（`cogos reindex`）；任何新存储
   都必须能从 canonical 重建。
2. **Trace 不记录 CoT**：只记录可验证系统事件。
3. **指标可证明**：Dashboard 的每个数字都要能追溯到 trace/verification
   （`docs/impact-integrity.md`）。
4. **禁止 Mock 冒充真实运行**；失败如实报告。
5. **隐私红线**：真实敏感词永不进 git/文档/测试；fixture 全合成。
6. **测试纪律**：完成改动必须跑 `python -m pytest tests/ -q`；Golden Path
   回归不可破坏。

### 提交流程

```bash
python -m pytest tests/ -q            # 全绿
PYTHONPATH=src python -m cogos.cli run "冒烟任务"   # Golden Path 冒烟
git add -A && git commit -m "..." && git push origin main
```
