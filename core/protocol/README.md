# Cognitive Protocol

Goal:

Allow 不同 AI Agents 到 communicate 使用 CognitiveOS.

示例:

Agent Request:

{
 任务: "coding",
 domain: "oracle",
 required_memory: [
   "sql_experience"
 ]
}

CognitiveOS 返回:

- Agent selection
- 记忆 context
- execution plan
