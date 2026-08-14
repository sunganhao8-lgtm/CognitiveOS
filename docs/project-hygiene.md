# Project Hygiene（Phase 10 治理约定）

## 目录职责（不可混用）

| 目录 | 职责 | 可重建 | 进 git |
|---|---|---|---|
| `src/` | Runtime 代码 | — | ✅ |
| `agents/` `skills/` | Agent 定义 / 收割技能 | — | ✅ |
| `docs/` | 架构与协议文档 | — | ✅ |
| `tests/` `tests/fixtures/` | 测试与合成数据 | — | ✅ |
| `scripts/` | 可重复运行的工具脚本 | — | ✅ |
| `user/` | **Canonical**：主人认知数据 | ❌ 不可重建 | ❌ 本地私有 |
| `.cogos/` | **Runtime**：cognitive.db、agent_workspace、last_report | ✅ reindex 重建 | ❌ |
| `artifacts/` | **Disposable**：benchmark 输出、截图、临时 dashboard | ✅ | ❌（可选择性提交样例） |
| `demo/` | 公开演示站（合成数据） | ✅ build_demo_site.py | ✅ |
| `tmp/` `cache/` | 不应出现（用 .cogos/agent_workspace/） | — | ❌ |

## 规则

1. **user/ 永不进 git**（.gitignore `user/`）；真实对话/偏好/trace 永不进公开仓库。
2. **生成物分类为 artifact**：HTML/PNG/benchmark 输出/截图 → `artifacts/`；
   不得伪装成 canonical，不得写入 user/。
3. **Agent 临时文件**（scratch/debug/intermediate）→ `.cogos/agent_workspace/`，
   不得散落项目根目录。
4. **项目根必须干净**：`git status` 除 user/ 未跟踪外无 tmp/debug/output/
   screenshot/scratch 字样。
5. **fixture 与真实数据严格隔离**：测试只用 tests/fixtures/ 合成数据。

## 清理命令

```bash
rm -rf .cogos/bench_ws .cogos/stress_ws   # benchmark/stress 工作区残留
```
