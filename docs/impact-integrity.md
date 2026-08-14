# Cognitive Impact Integrity 审计与定义（Phase 3G）

> 原则（§29）：**不要让 Dashboard 看起来比系统实际更聪明。**
> 知道什么就说什么：retrieved 就说 retrieved，applied 就说 applied，
> verified 就说 verified；只有完整证据链（known constraint → applied →
> verification PASS）才可以说 avoided a known error。

---

## 1. 审计：当前指标 → 当前实现 → 证据 → 判定 → 新定义

| 指标 | 当前实现 | 当前证据 | 是否支撑名称 | 判定 |
|---|---|---|---|---|
| **learned** | 窗口内创建的、subtype 非 candidate/temporary 的 memory 实体数 | entities.created_at | ❌ **不支撑**：episodic 每次执行都创建，被计入学**习** | 重定义 |
| **applied** | refs 含 preference/rule **且 verdict==PASS** 的 execution 数 | trace refs + executions.verdict | ⚠ 部分：注入证据真实（refs=注入列表），但 PASS 条件属于 verified 语义 | 重定义 |
| **avoided_errors** | verifications 表 PASS 总数 | verifications.verdict | ❌ **错误**：无规则应用的普通 SQL 也 PASS，被算成"避免错误" | 重定义 |
| **reused** | refs 非空 execution 数 | trace refs | ⚠ 与 applied 同源异名 | **删除**，换 verified |
| **corrected** | user_corrected 事件数 | trace_events | ✅ 支撑 | 保留 |
| **memory_impact** | HIGH(applied≥1 且 PASS)/MEDIUM(retrieved≥1)/LOW | refs + verdict | ⚠ 缺 RETRIEVED 级（系统未记录"检索到但未注入"） | 四级化 |
| verified | （无此指标） | — | — | 新增 |

## 2. 新定义（冻结）

### Learned
> 窗口内**真实形成**的长期认知：promotion/confirmation 事件或用户显式声明
> 创建的 preference/rule/semantic（subtype 白名单；**episodic 永不计入**）。

证据：`entities(subtype ∈ {preference, rule, semantic}, created_at ∈ 窗口,
source ∈ {sleep_promotion, user_statement, user_modification})`。
（sleep 晋升、用户确认、用户声明、用户修改都算"认知进入 Cognitive State"。）

### Retrieved
> 窗口内检索系统**命中**的认知执行次数（eligible 命中，无论是否注入）。

证据：`executions.payload.retrieved_total`（3G 新增字段，kernel 记录）。

### Applied
> 认知**真正进入 Agent Context** 并被 Agent 执行使用。

证据：`executions.payload.refs`（refs = 注入 context 的列表，非"检索到"）。
**与验证结果无关**——应用 ≠ 验证通过。

### Verified
> 被应用的认知**通过了对应验证**。

证据：`verifications(execution_id, rule_id, verdict=PASS)` 且该 rule_id
在 execution 的 refs 中（preference 无对应验证记录时不算 verified，如实
报 applied-only）。按 (execution, memory) 对计数。

### Known Errors Avoided
> 完整证据链：**已知约束（rule）+ 注入 + 对应验证 PASS**。

```
R-SQL-001(禁止 SELECT *) → retrieved → injected → Agent SQL → verify PASS
                                                                    ↓
                                              avoided_error += 1（该 execution 该 rule）
```
证据：execution.refs 含 rule R + verifications(execution, R, PASS)。
**Verify PASS 但无规则注入 → 不算。规则注入但 FAIL → 不算。**

### Corrected
> 用户纠正了 N 条 Cognitive State（不是"AI 犯了 N 次错误"）。

证据：`user_corrected` trace 事件。

## 3. Memory Impact 四级状态（per execution）

```
NONE      没有任何相关认知（refs 空 且 retrieved_total==0）
RETRIEVED 检索到认知但未注入 context（retrieved_total>0 且 refs 空）
APPLIED   认知进入 context 被使用（refs 非空）
VERIFIED  应用且对应验证 PASS（refs 含 rule/preference 且验证 PASS）
```
证据链：retrieval → context → agent → verification 逐级可查。

## 4. 新增字段（最小化，不建第二套日志）

- `executions.payload.retrieved_total`：本次检索 eligible 命中数（kernel 写入）
- `executions.payload.injected`：注入数（= len(refs)）
- 不新增事件类型；`cognitive_impact` 语义由 refs+verifications 组合表达。

## 5. Overview KPI（重定义后）

```
Learned            窗口内形成
Retrieved          窗口内检索命中次数
Applied            窗口内注入并使用次数
Verified           应用且验证通过次数
Known Errors Avoided  规则注入 + 验证 PASS 的 (execution, rule) 对数
Corrected          用户纠正次数
```
每个 KPI 附带**证据列表**（execution_id + memory + verdict），Dashboard
可展开"为什么是这个数"。

## 6. 数据真实性断言（自动测试锁死）

```
applied ≤ retrieved
verified ≤ applied
avoided_errors ≤ verified   （avoided 是 verified 的规则子集）
```
违反即测试失败。

## 7. Conversion Funnel（真实数据才展示）

Observations → Candidates → Confirmed → Applied → Verified。
样本过小（任一环节 <3）则不渲染，宁缺毋假。
