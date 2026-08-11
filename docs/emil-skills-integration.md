# 在 CognitiveOS 项目中使用 emilkowalski/skills

## 背景

`D:\VibeCoding\.agents\skills\` 目录安装了 emilkowalski/skills 的 10 个 UI/UX skill：
`animate`、`animation-vocabulary`、`apple-design`、`ask-sonner`、`emil-design-eng`、
`find-animation-opportunities`、`improve-animations`、`pick-ui-library`、`prototype`、`review-animations`

CognitiveOS 是一个**跨 Agent 认知运行时层**——它的 skill_view API 设计上就是用来加载任意 SKILL.md。
所以把 emil 的 skills 集成进 CognitiveOS 只需要一个符号链接 + 一次 reload。

## 集成方法

### 方式 A：符号链接（推荐）

把 emil 的 skills 软链到 CognitiveOS 的 skills 目录（如果项目有的话），
或直接软链到 Hermes 的 skills 目录，让本地所有 Agent 都能自动发现。

```bash
# 在 D:\GitHub_Project\CognitiveOS\ 下
mkdir -p .skills
for s in animate animation-vocabulary apple-design ask-sonner emil-design-eng \
         find-animation-opportunities improve-animations pick-ui-library \
         prototype review-animations; do
  ln -sf "D:/VibeCoding/.agents/skills/$s" ".skills/$s"
done
```

然后下次任何 Agent 启动时，Agent Loader 扫描 `.skills/` 目录即可发现这些 skill。

### 方式 B：直接放进 Hermes

Hermes 的 skills 目录是 `C:\Users\11390\AppData\Local\hermes\skills\`，把它复制过去：

```bash
xcopy "D:\VibeCoding\.agents\skills" "C:\Users\11390\AppData\Local\hermes\skills\emilkowalski" /E /I
```

下次 hermes chat 自动加载。**注意**：Hermes 是版本敏感，更新会覆盖 skills/，所以方式 A（项目内符号链接）更安全。

## 在 dashboard 里显示

CognitiveOS 的 dashboard 已经在 `src/cogos/templates/dashboard.html.j2` 中绘制了
`assets/brain-source.svg`（Wikimedia CC0），右上角可以加一个"设计参考"链接面板，
列出 emil 的 10 个 skill 作为可视资源。

待实现（v0.2）：
- `cogos skills` 命令列出已发现的 skill
- `cogos skills add <owner/repo>` 调用 `npx skills@latest add ...` 安装
- dashboard 在"可用命令"区域增加"设计参考" → emil skills

## 实际可用场景

当你让 Hermes / Claude / Codex 帮你改 dashboard 时，可以手动触发这些 skill：

- "给 dashboard 加过渡动画" → `cogos skills use animation-vocabulary`
- "用 Apple 设计风格改工作记忆面板" → `cogos skills use apple-design`
- "选个 toast UI 库" → `cogos skills use pick-ui-library`

CognitiveOS 的 `cogos brief --agent X` 在生成 Agent manifest 时，
可以自动把 `skills/` 目录的内容列入可加载资源。

## 当前状态

- 仓库：`D:\VibeCoding\.agents\skills\` 10 个 skill 全部就位
- skills-lock.json 已生成，可重装
- 与 CognitiveOS 项目代码无冲突（两个项目独立）