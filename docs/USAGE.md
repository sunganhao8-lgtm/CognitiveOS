# 真实使用指南 — 本地 / Demo 边界

## 两个模式，二选一

CognitiveOS 项目**只有两种运行模式**：

| 模式 | 命令 | 输出 | 用途 |
|---|---|---|---|
| **本地模式**（你日常用） | `cogos bootstrap` | `index.html`（152 KB 左右，含你真实数据） | 你自己在本机查看 / 给本地 Agent 当 manifest |
| **演示模式**（给访客看） | `python scripts/build_demo_site.py` | `demo/index.html`（80 KB 左右，全虚构数据） | 部署到 GitHub Pages 给陌生人看 |

**两个文件互不污染**。`cogos bootstrap` 永远覆盖 `index.html`，`build_demo_site.py` 永远覆盖 `demo/index.html`。

## 隐私防泄漏（4 层保护）

1. **`.gitignore`**：`index.html` 在 gitignore 里——本地 dashboard **永远不会被 git 追踪**。
2. **CI workflow 隔离**：`.github/workflows/pages.yml` 只跑 `build_demo_site.py` → 只 publish `demo/` 目录。`index.html` **永远不会**被推到 GitHub。
3. **privacy pre-flight check**（新加）：Pages workflow 在 publish 之前 grep 检查 `demo/index.html`，包含 `[REDACTED]` / `[REDACTED]` / `上海[REDACTED]|[REDACTED]` 等隐私关键词**直接 abort**。
4. **schema 隔离**：`scripts/build_demo_site.py` 用 `DEMO_PROJECTS` / `DEMO_QA_GROUPS` 硬编码虚构数据，**完全不读** `user/` 目录。

## 你要怎么开始真实使用

### 一次性设置

```bash
# 1. 把仓库 clone 到你想工作的地方
git clone https://github.com/sunganhao8-lgtm/CognitiveOS.git
cd CognitiveOS

# 2. 确认 user/ 已经准备好（这是 git 追踪的、共享的初始化内容）
ls user/
# 应该看到: README.md  manifest.md  preferences.md  style.md  ...
```

### 每次开始一天的工作

```bash
# 1. 让 cogos 扫描你本地的 Agent + 提取对话
python -m cogos.cli bootstrap

# 这会:
#   - 发现本机所有 Agent (Hermes / Claude Code / Codex)
#   - 从各 Agent 历史提取 QA 对到 user/conversations/
#   - 生成首页 index.html
#   - 打开浏览器

# 2. 在浏览器里看 (file:///D:/GitHub_Project/CognitiveOS/index.html)
# 主页 dashboard: 大脑图 + 工作记忆 + 真实问答 + 真实项目
```

### 日常更新

| 场景 | 命令 |
|---|---|
| 你和 Hermes 聊完一段对话 | `cogos ingest` 重新提取（不重生成 dashboard） |
| 加了新的项目 / 改了 user/projects/*.md | `cogos bootstrap --no-browser` 重新扫描 |
| 修改了 preferences/style | `cogos bootstrap --no-browser` |
| 想给别人看 | `python scripts/build_demo_site.py`（永远基于**虚构**数据） |
| 给新 Agent 注入你的档案 | `cogos brief --agent hermes`（生成 manifest） |

### 怎么导出/分享给别人（可选）

```bash
# 导出 user/ + knowledge/ 为 tar.gz
cogos export-user --to /tmp/my-master-archive.tar.gz

# 跨设备迁移
cogos import-user --from /tmp/my-master-archive.tar.gz
```

## 你**永远不要做**的事

- ❌ **不要 push `index.html`**（.gitignore 阻止了，但你手动 `git add -f` 会绕过）
- ❌ **不要让 `build_demo_site.py` 读 `user/` 目录**（它不应该——但如果它开始读，privacy check 会拦截）
- ❌ **不要把真数据写到 `user/` 后跑 `build_demo_site.py`**——虽然 privacy check 会捕获，但**永远不要让真实数据进入 demo 的代码路径**

## 故障排查

| 问题 | 检查 |
|---|---|
| `index.html` 还是显示 demo | 检查 `user/projects/INDEX.md` 是否被替换成你自己的项目 |
| 隐私 check 在 CI 失败 | 检查 `demo/index.html` 里有没有主人的真实标记（grep "[REDACTED]" 等） |
| 我误把真数据 push 上去 | 立刻 `git rm --cached index.html && git commit` |
| 本地 dashboard 是英文 | 检查 `cogos bootstrap` 是否生成成功（看 `python scripts/build_demo_site.py` 输出） |

## 给未来你的笔记

> 2026-08-12：开始真实使用。`user/` 目录从今往后只放**真正的**主人档案和项目。`demo/index.html` 永远是给别人看的版本，所有真实对话和隐私只在 `index.html`（本地）+ `user/conversations/`（本地）。

> 每次别人问起，都告诉他们：访问 `https://sunganhao8-lgtm.github.io/CognitiveOS/` 看 demo（虚构），但你的真实 dashboard 永远在 `D:\GitHub_Project\CognitiveOS\index.html`。