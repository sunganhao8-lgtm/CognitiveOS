# CognitiveOS

面向 AI Agent 的**认知运行时层**（Cognitive Runtime Layer）。

[中文](README.md) | [English](README.en.md)

> **差异化只有三个字**：**跨 Agent、跨设备、文本可读**。Claude Code / Workbuddy / Qoder 这一层都长得一样（LLM + 上下文 + 工具调用），CognitiveOS 不在那层做差异化。它把"你的偏好、你的项目、你的禁忌"从 Agent 抽出来，放到你自己手里——`git diff`、换电脑、换 Cursor，都不丢。

## 这些痛点，你经历过吗？

### 痛点 1：想换个 AI Agent，却不敢换 😰

你已经在某个 Agent 里积累了大量记忆：你的习惯、你的偏好、你踩过的坑、几百个项目的来龙去脉。

换一个新的 Agent = **全部重来**。要重新教会它"你是谁、你在乎什么、什么不能碰"。

一想到迁移成本，你放弃了尝试新产品。**你被"记忆锁定"在旧 Agent 上了。**

### 痛点 2：换台电脑，等于失忆 🧠

新电脑装好 Agent，它不认识你。

它不记得你的项目、你的决策、你花几个月踩坑踩出来的经验。

你的"认知"留在了旧机器上。**换电脑 = 失忆，从头再来。**

### 痛点 3：Agent 的记忆是"它的"，不是"你的" 🔒

你在这台机器、这个 Agent 里积累的一切，都跟着 Agent 走。

哪天不用它了，**这些积累就没了**——就像换了管家，管家记得的事，不是主人的事。

---

**CognitiveOS 的答案：把"你的认知"从 Agent 里拿出来，放到你自己手里。**

## 愿景

现在的 AI Agent 很强大，但彼此孤立：

- Claude Code 擅长写代码
- OpenClaw 擅长自动化
- Codex 擅长工程
- Hermes 擅长编排

但它们缺乏：**共享记忆、统一身份、经验积累、认知协调**。

CognitiveOS 的目标，是为 AI Agent 提供一层"认知层"——并且这层认知属于**用户**，不属于任何 Agent。

## 核心理念

> AI Agent 就像管家，用户是主人。以前换了管家或换了地方，就要重新交代一切。CognitiveOS 保存的是**主人最有价值的数据**——习惯、思维模式、经验、偏好——让主人换管家、换电脑、换产品时，认知无缝迁移。

CognitiveOS 不是另一个 AI Agent，而是让 Agent 能够 **记住（remember）、推理（reason）、协作（collaborate）、改进（improve）** 的基础设施。

## v0.1 能做什么

```bash
pip install -e .
cogos bootstrap        # 全流程：发现 Agent → 收割 → wiki → 仪表盘
cogos brief --agent X  # 给新管家一份"主人档案"
cogos persona fit      # 用过去真实问答训练管家对主人的拟合
cogos export-user      # 导出 user/ 层（跨设备迁移）
cogos import-user      # 导入 user/ 层
```

打开生成的 `index.html`，你会看到一张可点击的**认知地图**（大脑分区图），以及你的活跃项目、最近问答和可用命令。

## 架构

```
cogos/
  discovery.py      发现本机已安装的 AI Agent
  adapters/         统一 Agent 接口（Hermes 第一个实现）
  kernel.py         Kernel 编排循环（DESIGN.md 的实现）
  persona_fit.py    主人人格拟合训练（语义匹配打分）
  conversations.py  从 Hermes 会话库提取真实问答对
  portability.py    user/ 层导出/导入（跨设备迁移）
  dashboard.py      生成 index.html 认知地图
```

数据流永远是：

```
Raw Source → Normalized Document → Wiki Page
```

## user/ 层（核心资产）

```
user/
  manifest.md       主人档案（新管家入职第一份文件）
  preferences.md    沟通/输出/工具偏好
  style.md          决策风格
  projects/         每个项目的 tacit knowledge
  experience/       值得记住的具体经历
  conversations/    历史问答对（从 Agent 会话库提取）
  cognitive/        跨设备、跨 Agent 的认知状态
```

**这些文件属于你，不属于任何 Agent。** 换机器、换 Agent，`user/` 跟着你走。

## 设计原则

- **Local-first**：数据默认留在本地
- **Agent-agnostic**：CognitiveOS 不属于任何一个 Agent
- **Source-preserving**：每条知识都能追溯到原始文件
- **Human-readable**：知识库人可以直接阅读
- **Machine-readable**：同时方便 AI 读取
- **Modular**：发现、适配、仪表盘都可以独立替换
- **Progressive**：第一次初始化只做必要工作
- **Open ecosystem**：允许第三方 Agent / Adapter 接入

## 路线图

- **v0.1 Foundation**：项目架构、Agent 发现、user/ 层、认知地图 ✅
- **v0.2 Agent Integration**：接入更多 Agent（Codex / Claude Code / OpenClaw）
- **v0.3 Reflection**：自我改进循环（sleep cycle）
- **v1.0 Cognitive Runtime**：稳定的开源生态

## 状态

实验性 / 研究项目（Experimental / Research Project）

## 参与贡献

欢迎！请看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解如何加入。
