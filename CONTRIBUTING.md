# 贡献指南

感谢你对 CognitiveOS 感兴趣！CognitiveOS 是一个实验性研究项目，目标是构建 AI Agent 的认知运行时层。欢迎任何人参与。

## 如何开始

1. **Fork 本仓库**，然后 clone 到本地。
2. 阅读 [`README.md`](README.md) 和 [`docs/vision.md`](docs/vision.md) 了解项目定位。
3. 阅读 [`docs/architecture.md`](docs/architecture.md) 和 [`docs/design-decisions.md`](docs/design-decisions.md) 了解架构与决策记录。
4. 查看 [ROADMAP.md](ROADMAP.md) 了解当前阶段目标。

## 贡献什么

- **代码**：新 Agent Adapter、Kernel 功能、CLI 命令、Dashboard 改进
- **文档**：修正错漏、补充双语（中文/英文）文档
- **测试**：为现有模块补测试
- **想法**：在 [Issues](https://github.com/sunganhao8-lgtm/CognitiveOS/issues) 里提出设计讨论

## 开发流程

1. 从 `main` 分支新建功能分支：`git checkout -b feat/your-feature`
2. 做改动，保持改动**小而聚焦**
3. 本地验证：
   ```bash
   pip install -e .
   cogos bootstrap --no-browser
   cogos persona list
   ```
4. 提交并推送：`git push origin feat/your-feature`
5. 开 Pull Request，描述改动内容与验证方式

## 代码规范

- 遵循现有代码风格（Python 3.10+，类型标注，docstring）
- 新增目录/文件时保持 `src/cogos/` 的模块结构
- 不把用户数据（`user/conversations/`、`user/persona/samples/` 等）提交进仓库——见 `.gitignore`

## 提交信息规范

```
type: 简明的主题行

类型：feat / fix / docs / refactor / chore / test
```

## 审核

Pull Request 需要至少 1 位维护者审核通过后合并。请在 PR 描述中说明：

- 改了什么
- 为什么改
- 如何验证的

## 行为准则

- 友好、尊重、就事论事
- 讨论设计问题时给出理由，而不是只给结论
- 中文或英文交流均可