# CognitiveOS 当前架构理解报告

> 生成方式：逐文件通读全部运行时代码（`src/cogos/` 3967 行、6 个测试文件、9 篇 docs、模板、脚本），并实跑测试与 grep 验证每条结论。
> 状态：只读诊断，未修改任何代码。
> 日期：2026-08-13

---

## 0. 结论速览（先说最重要的）

**一句话诊断：CognitiveOS 目前是一台「仪表盘好看、引擎空转」的机器。产品叙事（README/愿景/大脑图）是完整的，但三个核心机制——Agent 访问记忆、知识影响决策、系统状态可视化——每一个在运行时都是断的。**

三个致命事实（全部有代码证据，见 §5）：

1. **🔴 隐私安全事故（P0，立即处理）**：公开仓库 `github.com/sunganhao8-lgtm/CognitiveOS` 的 origin/main 上已推送了主人的真实隐私数据——`user/manifest.md`、`user/preferences.md`、`user/README.md`、`user/projects/zhaiyu-bp.md` 明文含「上海[REDACTED] / 绍兴[REDACTED]」（用户简历隐私红线）、「品牌叫[REDACTED]」、店铺筹备状态；`src/cogos/dashboard.py` 源码里还硬编码了主人的真实沟通规则。Pages 的隐私 pre-flight 只防了 demo 站，没防主仓库本身。
2. **Kernel（认知编排循环）是孤儿**：`kernel.py` 实现了「组装上下文 → 路由 → 执行 → 反思 → 记忆写入」的完整循环，但 CLI 没有 `run` 命令、bootstrap 流水线不经过它，全项目只有 `scripts/run_router_demo.py` 一个 demo 脚本调用它。而且它组装的 `memory_entries` **从不注入 Agent 的 prompt**（HermesAdapter.execute 只读 `task.intent/domain`）。
3. **「认知」是装饰不是状态**：Dashboard 大脑图上的 22 条「工作记忆」和 5 条「主人规则」全部硬编码在 `dashboard.py` 源码里，与真实的 `user/` 文件、`verify` 校验结果、`persona` 训练结果、`knowledge/wiki` 收割结果**零连接**。系统真实学到的东西（校验 PASS/FAIL、人格拟合分、收割的 1600 个技能文件），用户在大脑图上一条都看不到。

**积极的一面**（说清楚什么是对的，重构时保留）：`verify` 的三阶段判断（关键词 → AMBIGUOUS → LLM 语义）是对「诚实答案」的正确工程化；`persona fit` 用主人真实原话做语义匹配而非 LLM 自评，方向正确；共享工作区（task/inbox/workspace/lock）是干净利落的文件协议；测试 53 个全绿。

---

## 1. 项目快照（真实数字）

| 项 | 值 |
|---|---|
| 位置 | `D:\GitHub_Project\CognitiveOS`，git main |
| 远端 | `github.com/sunganhao8-lgtm/CognitiveOS`（**公开**，origin/main 已推送） |
| 规模 | 48 commits；97 个被跟踪文件；Python 39 个 + Markdown 50 个 |
| 核心代码 | `src/cogos/` 共 3967 行（26 个模块） |
| 测试 | 6 个测试文件，**53 passed（0.86s）** |
| 数据体量 | 收割的 Hermes skills ≈ 1600 文件；`user/conversations/` 数十条真实问答；24 个 QA detail 页 |
| 未跟踪残留 | `cognitiveos-redesign/`（一次 solo-design 运行的失败产物，validation-report.json 显示 `terminal_stop`，含 3 轮验证预算耗尽） |

---

## 2. 真实架构图（代码级，不是 README 的）

```
                          ┌───────────────────────────┐
                          │        cogos CLI          │  (cli.py, 277 行)
                          └────────────┬──────────────┘
                                       │ 12 个命令组：bootstrap / status / brief / persona /
                                       │ verify / ingest / export-user / import-user /
                                       │ task / inbox / workspace / lock
            ┌──────────────┬───────────┼───────────────┬──────────────────┐
            ▼              ▼           ▼               ▼                  ▼
   ┌──────────────┐  ┌──────────┐ ┌───────────┐  ┌───────────────┐  ┌────────────────┐
   │  bootstrap   │  │  brief   │ │  persona  │  │  verify /     │  │ task / inbox / │
   │  流水线      │  │  简报    │ │  fit 训练 │  │  ingest       │  │ workspace/lock │
   └──────┬───────┘  └────┬─────┘ └─────┬─────┘  └──────┬────────┘  └───────┬────────┘
          │               │             │               │                   │
          ▼               ▼             ▼               ▼                   ▼
   discovery(probes)  拼文本给用户   hermes chat  -q  hermes chat -q    D:\GitHub_Project\
   ├ probe_hermes     手动粘贴        (默认 profile,  (cogos-test 隔离)   SharedWorkspace\.cogos\
   ├ probe_claude_code                无隔离！)       user/conversations/ tasks/ locks/ messages/
   └ probe_codex                                      user/verify/
          │
          ▼
   adapters.harvest ──► knowledge/sources/<agent>/   ← 收割快照（gitignored）
          │                        │
          ▼                        ▼
   normalizer ──► knowledge/normalized/index.json（只列文件名，不解析内容）
          │                        │
          ▼                        ▼
   wiki ──► knowledge/wiki/*.md（每 Agent 一页，只列文件清单）
          │
          ▼
   dashboard.render ──► 根目录 index.html（157KB，gitignored）
                        │
                        ├── 读：user/projects/INDEX.md、user/conversations/*.jsonl（每 Agent 最新 3 条）
                        ├── 硬编码：REGIONS 7 脑区 + 22 条记忆 + 5 条规则 + master_name
                        └── 不读：knowledge/wiki、.cogos/memory.jsonl、user/rules、user/verify、user/persona

   ════════════ 断开的 ════════════

   kernel.py（Kernel.run：组装上下文→路由→执行→反思→写记忆）
        │  只被 scripts/run_router_demo.py 调用（demo，不进 CLI）
        ▼
   .cogos/memory.jsonl（FileMemory，episodic JSONL）
        │  write 方：Kernel.run
        └  read 方：无。CLI 无 run 命令，Agent 永远读不到。
```

**一眼可见的三个断裂**：

1. `kernel.py` 这条竖线（右下的虚线区）与整张图**没有连接**——它是一段死代码旁边的活 demo。
2. `knowledge/`（收割的知识）**流入 dashboard 的箭头不存在**——收割了 1600 个文件，大脑图上一行都不显示。
3. `user/`（主人认知）到 Agent 的箭头只有 `brief` 一条**人工粘贴**通道——运行时没有任何 Agent 程序化地读到它。

---

## 3. 四个核心问题的真实答案

### 3.1 Agent 如何访问 Memory？——运行时零访问。唯一通道是「人工粘贴」。

| 名义上的通道 | 真实状态 | 证据 |
|---|---|---|
| Kernel 组装上下文 | Kernel 只在 demo 脚本里跑；CLI 无 `run` 命令 | `cli.py` 无 run 子命令；`grep -rn "kernel" cli.py bootstrap.py` 零命中 |
| `memory_entries` 注入 prompt | **组装了但从不使用**——adapter 只读 `task.intent/domain/required_memory` 键名，不读条目内容 | `adapters/hermes/adapter.py:107-113` |
| `cogos brief` | 生成文本，**用户手动粘贴**进 Agent（Hermes 是一行命令，Claude/Codex 是追加到 AGENTS.md/CLAUDE.md 的 heredoc） | `brief.py:34-74` |
| persona fit / verify | 只把 prompt 单向扔给 `hermes chat -q`，Agent 回答后不回写任何「Agent 可读」状态 | `cli.py:168-201`、`verify.py:242-252` |

**结论**：README 宣称「Agent 拥有长期记忆、技能成长、用户理解」，但当前 Agent 在运行时能拿到的「记忆」只有两样——它自己的原生记忆，和用户手动粘贴的 brief。CognitiveOS 的任何存储对 Agent 都是**不可见的**。

### 3.2 Skill 如何注册？——没有注册机制。Skill 只是收割快照里的文件。

- 全项目没有 skill registry、没有 skill schema、没有调用记录、没有「哪个 skill 影响了哪次执行」的溯源。
- `knowledge/sources/hermes/skills/` 里的 1600 个文件是原样拷贝，`normalizer` 只做文件名清单（`normalizer.py` 全文 50 行，明确写了「不解析 Markdown、不提取内容」）。
- Dashboard 大脑图 7 个脑区里**没有 Skill 节点**。
- 唯一与「技能」沾边的是 `verify` 里的规则探针（`user/rules/*.json`），但那是「铁律」，与收割的 skills 目录没有关系。

### 3.3 数据在哪里保存？——三套互相看不见的存储，加一个项目外工作区。

| 存储 | 位置 | 内容 | 谁写 | 谁读 |
|---|---|---|---|---|
| 收割快照 | `knowledge/sources/normalized/wiki` | Agent 文件白名单拷贝 + 清单 | bootstrap | wiki 生成、人读 |
| 主人认知层 | `user/`（preferences/style/manifest/projects/experience/conversations/persona/rules/verify） | 主人的偏好、项目、问答、铁律、训练样本 | 用户手写 + 各 CLI 命令 | brief/persona/verify/dashboard（部分） |
| Kernel 记忆 | `.cogos/memory.jsonl` | episodic JSONL | Kernel.run | **无人** |
| 共享工作区 | `D:\GitHub_Project\SharedWorkspace\.cogos\` | tasks/locks/messages JSON | task/inbox/workspace/lock 命令 | 各 Agent（人工约定） |

三套存储**互不引用**：`knowledge/` 不知道 `user/` 的存在，`memory.jsonl` 谁都不认识，共享工作区在项目目录之外靠硬编码默认路径（`workspace.py:28` 的 `DEFAULT_WORKSPACE_ROOT`）。

### 3.4 Dashboard 读取什么数据？——一半硬编码、一半真实数据，且真实的部分是最不重要的。

| Dashboard 板块 | 数据来源 | 真实性 |
|---|---|---|
| 大脑图 7 脑区 + 22 条「工作记忆」 | `dashboard.py:76-211` 的 `REGIONS` 常量 | **硬编码**，与 `user/` 文件、verify 结果零连接 |
| 主人规则 5 条 | `dashboard.py:298-304` 字面量 | **硬编码**（且是真隐私规则，见 P0-1） |
| master_name「[REDACTED]」 | `dashboard.py:297` 字面量 | 硬编码 |
| 活跃项目 | `user/projects/INDEX.md` 解析 | ✅ 真实 |
| 最近问答 | `user/conversations/*.jsonl` 每 Agent 最新 3 条 | ✅ 真实 |
| verify 校验结果 | 不读 | ❌ 不显示 |
| persona 拟合分 | 不读 | ❌ 不显示 |
| knowledge/wiki 收割结果 | 不读 | ❌ 不显示 |

**结论**：用户在大脑图上看到的「系统学会了什么」，是源码里写死的常量；系统真正学会的东西（校验 PASS/FAIL、人格拟合分、1600 个收割文件）一条都不渲染。「让用户看到 AI 为什么越来越懂自己」——当前实现完全做不到，因为它显示的「懂」不是状态，是文案。

---

## 4. 模块依赖关系汇总

```
discovery ──► probes ──► adapters ──► normalizer ──► wiki ──► dashboard
     │                          │
     │                     (harvest 只复制文件)
     │
cli ──► bootstrap ──► dashboard(硬编码数据 + user/ 部分数据)
cli ──► brief/persona/verify/ingest/portability ──► user/
cli ──► task/inbox/workspace/lock ──► SharedWorkspace/.cogos/
kernel ──► .cogos/memory.jsonl  （孤立；无 CLI 入口；无 reader）
```

依赖方向健康（没有循环 import），但**数据方向不健康**：每条竖线各自垂直到底，没有横向连接。这正是「用户看到很多孤立功能」的代码级原因。

---

## 5. 当前最大问题（P0–P3 分级）

### P0 —— 架构断裂 / 安全事故（不修，产品目标不可能达成）

| # | 问题 | 原因 | 位置 | 证据 |
|---|---|---|---|---|
| P0-1 | **公开仓库泄漏主人隐私** | user/ 层核心文件被 git 跟踪并推送；Pages 隐私 pre-flight 只守 demo 站不守主仓 | `user/manifest.md`、`user/preferences.md`、`user/README.md`、`user/projects/zhaiyu-bp.md`、`src/cogos/dashboard.py` | 公开 origin/main 上 grep 到「上海[REDACTED] / 绍兴[REDACTED]」「品牌叫[REDACTED]」明文；`git status -sb` 显示已同步 |
| P0-2 | **Agent 运行时零记忆访问** | Kernel 无 CLI 入口；memory_entries 组装后不注入 prompt | `kernel.py`、`cli.py`、`adapters/hermes/adapter.py:107-113` | `grep -rn kernel cli.py bootstrap.py` 零命中 |
| P0-3 | **三套存储互不连通** | knowledge / user / memory.jsonl 各自垂直到底，无横向引用 | `paths.py`、`workspace.py:28` | 见 §3.3 表 |
| P0-4 | **Dashboard 展示的认知是硬编码装饰** | REGIONS/rules/master_name 全部源码常量；真实学习产出不渲染 | `dashboard.py:76-211,297-304` | 见 §3.4 表 |
| P0-5 | **无 Execution Trace** | 任务执行不落痕；kernel 的 episodic 记录无人读、无 skill/memory 引用字段、不进 UI | `kernel.py:196-217` | 全项目 grep 无 trace 概念 |

### P1 —— 认知图缺失（产品核心价值的地基）

| # | 问题 | 说明 |
|---|---|---|
| P1-1 | **无 Cognitive Graph 数据模型** | User/Preference/Memory/Knowledge/Skill/Agent/Task 之间没有实体、没有关系、没有查询。唯一的关系载体是文件路径约定（如 `user/projects/INDEX.md` 的 markdown 链接解析） |
| P1-2 | **Skill 不是一等公民** | 无注册、无调用记录、无溯源（见 §3.2） |
| P1-3 | **学习产出不可见** | verify PASS/FAIL、persona 拟合分、ingest 提取数都不进 Dashboard——「越来越懂我」没有证据链 |
| P1-4 | **persona fit 无会话隔离** | `verify` 用 `--profile-name cogos-test` 隔离探针会话，但 `persona fit` 的两轮 `hermes chat -q` 打在默认 profile 上，训练过程污染主人的主会话列表 | `cli.py:169,185` vs `verify.py:222-229` |

### P2 —— 工程治理

| # | 问题 | 说明 |
|---|---|---|
| P2-1 | **双目录树并存** | `core/`、`agents/`、`memory/`、`reflection/` 是纯 README 的「契约占位」目录，真实实现全在 `src/cogos/`——新读者按 DESIGN.md 的目录映射找实现会扑空（DESIGN.md 自己都写着「No implementation code lives here yet」，但实现已经在别处存在了） |
| P2-2 | **未跟踪的半成品残留** | `cognitiveos-redesign/` 是一次失败 solo-design 运行的产物（validation `terminal_stop`），混在仓库根 |
| P2-3 | **数据与渲染耦合 + 平行副本** | `dashboard.py` 356 行里数据常量占 211 行；`scripts/build_demo_site.py` 有第二份 REGIONS 序列化——skill 记录过「加字段必须两处同步」的反复翻车 |
| P2-4 | **中文化执行不一致** | `conversations.py` docstring 已翻成中文，其余模块 docstring 保持英文——需要按「用户可见串中文、代码注释英文」定稿统一 |
| P2-5 | **测试覆盖与文档不符** | 53 测试只覆盖 kernel/paths/user/verify/workspace 五个模块；dashboard/normalizer/wiki/brief/discovery/adapters/agent_memories/conversations/persona_fit/portability/tasks/inbox 零测试；`tests/README.md` 只有一句「Tests for CognitiveOS will live here.」 |

### P3 —— 细节

| # | 问题 |
|---|---|
| P3-1 | `FileMemory.read` 线性全文件扫描、无去重无索引 |
| P3-2 | `brief --agent claude/codex` 输出的 heredoc 会直接追加用户项目的 AGENTS.md/CLAUDE.md，属高风险写操作但无警告 |
| P3-3 | `paths.ensure()` 不建 `user/`（靠 bootstrap 里 UserLayer.ensure 补），两份目录事实源 |
| P3-4 | `bootstrap` 对每个发现到的 agent 都 harvest，但「Bootstrap Agent」概念（README/DESIGN 里的「让一个 Agent 解读环境」）实际只取了第一个的 id，从未让它解读任何东西 |

---

## 6. 与产品目标的差距映射

产品目标（README 定稿）：「让 Agent 能复刻你的决策，并通过主动复现校验来证明它真的复刻了」。

| 目标组件 | 现状 | 差距 |
|---|---|---|
| 复刻主人的决策 | `persona fit` 训练存在，但产物（model.md、拟合分）与 Agent 运行时的 bridge 是断的——Agent 读不到训练结果 | 训练闭环 50%，投喂闭环 0% |
| 主动复现校验 | ✅ `verify` 已实现且设计正确（三阶段判断、会话隔离、非种子化规则） | 完成度最高的一块 |
| 让用户看到「越来越懂我」 | Dashboard 显示硬编码文案，真实学习产出零渲染 | 0% |
| 跨 Agent / 跨设备 | export/import + brief 可用 | 可用但无校验结果随迁、无增量同步 |
| 记忆分层、可追溯 | sources→normalized→wiki 三层在，但 normalizer 只是文件名清单，未做内容抽取 | 骨架 100%，内容 10% |

---

## 7. 下一阶段入口（对应重构 Phase 1 → 5）

本报告是 Phase 1（诊断）的交付物。后续阶段的切入点建议：

1. **先止血 P0-1**（隐私泄漏）——需要用户决策 git 历史处理方式（重写历史 vs 删库重建），属不可逆操作，另行确认。
2. **Phase 2：设计 Cognitive Graph 数据模型**——统一实体（User/Preference/Memory/Knowledge/Skill/Agent/Task/Trace/Result）与关系，落成 schema + 存储布局；这是打通三套存储的唯一途径。
3. **Phase 3：把 Kernel 接进 CLI 并让 memory 真正流入 Agent prompt**——一条 `cogos run` 命令打通「组装上下文 → 路由 → 执行 → 落 Trace」。
4. **Phase 4：Dashboard 改为渲染真实状态**（REGIONS 常量降级为「脑区图例」，记忆条目改为从 user/ + verify + persona + wiki 实时读取）。
5. **Phase 5：Execution Trace 落库 + 展示**——每次执行产生可解释 trace，「为什么这样回答」有了证据链。

---

*报告完。所有结论均有源码位置佐证；任何一条可当场复验。*
