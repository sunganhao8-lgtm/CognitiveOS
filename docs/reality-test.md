# CognitiveOS Reality Test 协议（Phase 4）

> 目标：验证 CognitiveOS **是否真的让 Agent 越来越懂用户**，而不是功能堆叠。
> 原则（任务书 §57）：不污染数据、不改变指标定义去制造优势；没有差异就诚实报告。

---

## 1. 核心假设

```
H1: 长期使用后，用户重复说明同一偏好的次数下降
H2: 用户纠正次数下降
H3: Agent 自动应用用户认知（无需重新解释）
H4: 应用后验证通过率保持稳定
H5: CognitiveOS 不是 SQL-specific Memory（跨域有效）
```

## 2. 时间线

| 检查点 | 内容 |
|---|---|
| **Day 0** | 基线：现有 182 测试全绿；3 场景任务集定义；`reality-test-log.md` 初始化；指标快照 |
| **Day 3** | 观察：repeated instructions / corrections / retrieved / applied 计数 |
| **Day 7** | 中期评估：H1-H5 初步判断；必要修正（不改指标定义） |
| **Day 14** | 终期评估：全部指标汇总 + Product Hypothesis 初判 |

## 3. 真实使用指标（全部从 Cognitive Store / Trace 聚合，禁止手工编造）

| 指标 | 定义 | 数据源 |
|---|---|---|
| Repeated Instructions | 同义/同偏好任务在未重述情况下被正确应用（倒指标：应下降） | executions.task + refs |
| Corrections | user_corrected 事件数（倒指标：应下降） | trace_events |
| Retrieved | 检索命中次数 | executions.payload.retrieved_total |
| Applied | 认知注入 context 次数 | executions.payload.refs |
| Verified | 应用且验证 PASS 对数 | verifications |
| Avoided Errors | 规则注入 + 验证 PASS 全链对数 | refs × verifications |
| Confirmed Cognitions | 已确认认知数 | entities |
| Candidate Conversion | candidate → confirmed 转化率 | candidates.jsonl |
| Correction Rate | 纠正数 / 应用数 | user_corrected ÷ applied |
| Retrieval Waste | 注入但未验证/未用的认知占比 | (applied − verified) ÷ applied |

## 4. 三场景任务集（证明非 SQL-specific）

### 场景 A：SQL
- 声明：SQL 禁止 SELECT *（已有）
- 任务：写查询/生成报表 SQL × N
- 观察：是否自动应用、verify 结果

### 场景 B：Report
- 声明：报表偏好（如"报表要横向宽表、表头带汇总行"）
- 任务：生成报表 × N
- 观察：偏好是否被检索/注入/遵守

### 场景 C：General Work
- 声明：沟通风格（如"汇报先结论后细节"）
- 任务：写文档/回复 × N
- 观察：风格偏好是否被应用

## 5. Control Group（可重复任务集，无 A/B 平台）

| 组 | 设置 |
|---|---|
| Normal Agent | 同一任务集，无 CognitiveOS context 注入 |
| Agent + CognitiveOS | 同一任务集，完整认知链路 |

比较：Repeated Instructions / Corrections / Successful Outputs /
Preference Applications / Verification / Interaction Count。
**两组无差异 → 诚实报告，不修改指标。**

## 6. 成功 / 失败标准

### 成功（H1-H5 全部或多数成立）
- Day 14 时：同偏好任务在**无重述**情况下的应用率 ≥ 70%
- Corrections 不随使用量线性增长（趋势平稳或下降）
- 三场景中至少 2 个域有 Applied > 0

### 失败
- 应用率 < 30%，或纠正率持续上升，或三场景仅 SQL 有效
- 结论：Product Hypothesis PARTIALLY / NOT SUPPORTED → 提出最小改变方向

## 7. 用户反馈（每检查点记录）

```
日期 | 场景 | 是否觉得 AI 更懂你了？ | 最明显的差异 | 最烦的地方
```

## 8. 隐私规则（写死）

日志只记录：日期 / 任务类型 / 是否记住 / 是否应用 / 是否验证 / 是否纠正 / 结果。
**禁止记录**：API keys / tokens / CoT / 私密原文 / 完整对话。
日志文件本身是本地私有文件（user/ 之外，不进 git）。
