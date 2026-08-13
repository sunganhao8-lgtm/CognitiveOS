# 真实使用指南 — 本地 / Demo 边界

## 两个模式，二选一

CognitiveOS 项目**只有两种运行模式**：

| 模式 | 命令 | 输出 | 用途 |
|---|---|---|---|
| **本地模式**（你日常用） | `cogos bootstrap` | `index.html`（含你真实数据） | 你自己在本机查看 / 给本地 Agent 当 manifest |
| **演示模式**（给访客看） | `python scripts/build_demo_site.py` | `demo/index.html`（全虚构数据） | 部署到 GitHub Pages 给陌生人看 |

**两个文件互不污染**。`cogos bootstrap` 永远覆盖 `index.html`，`build_demo_site.py` 永远覆盖 `demo/index.html`。

## 隐私边界（数据真实性原则）

1. **`user/` 是本机私有层，绝不入仓**。`user/` 整个目录由 `.gitignore` 排除；真实主人档案、偏好、对话、规则、trace 都只存在于本机。换机用 `cogos export-user` / `import-user` 迁移，不走 git。
2. **敏感词清单不入仓**。真实的隐私关键词清单保存在本机 `.cogos/sensitive_patterns.json`（已被 .gitignore 排除）。canary 测试（`tests/test_verify.py`）在本地会读取它做实质性防泄漏断言；公开克隆的仓库只会做结构性断言，不会因此泄露任何真实词。
3. **CI pre-flight**：Pages workflow 在 publish 前检查 `demo/index.html`，命中敏感模式直接 abort（模式来自 GitHub Secret，不入仓库）。
4. **schema 隔离**：`scripts/build_demo_site.py` 用 `DEMO_PROJECTS` / `DEMO_QA_GROUPS` 硬编码虚构数据，**完全不读** `user/` 目录。
5. **Dashboard 零硬编码**：界面上的规则/记忆/执行数据一律来自 Cognitive Store（Phase 2C），源码里不写任何真实主人数据。

## 你要怎么开始真实使用

### 一次性设置

```bash
# 1. 把仓库 clone 到你想工作的地方
git clone https://github.com/sunganhao8-lgtm/CognitiveOS.git
cd CognitiveOS

# 2. 建立你自己的 user/ 层（本机私有，git 不会追踪）
mkdir -p user
#    然后手写 manifest.md / preferences.md / style.md，或从导出包导入：
cogos import-user --from my-master-archive.tar.gz
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

### 怎么导出/分享给自己（可选）

```bash
# 导出 user/ 层为 tar.gz（跨设备迁移用，不要发给别人）
cogos export-user --to D:/backup/my-master-archive.tar.gz

# 跨设备迁移
cogos import-user --from D:/backup/my-master-archive.tar.gz
```

## 你**永远不要做**的事

- ❌ **不要 push 任何 `user/` 内容**（.gitignore 阻止了，但你手动 `git add -f` 会绕过）
- ❌ **不要让 `build_demo_site.py` 读 `user/` 目录**（它不应该——但如果它开始读，privacy check 会拦截）
- ❌ **不要把真数据写进任何被 git 追踪的文件**（源码、docs、scripts、tests）
- ❌ **不要在公开仓库的代码/文档里写任何真实隐私词**（包括 CI 配置、测试夹具、注释）

## 故障排查

| 问题 | 检查 |
|---|---|
| `index.html` 还是显示 demo | 检查 `user/projects/INDEX.md` 是否被替换成你自己的项目 |
| 隐私 check 在 CI 失败 | 检查 `demo/index.html` 里有没有真实标记（模式在 GitHub Secret 里） |
| 本地 dashboard 是英文 | 检查 `cogos bootstrap` 是否生成成功（看 `python scripts/build_demo_site.py` 输出） |
| 怀疑隐私已泄漏 | 见 `docs/privacy-remediation.md` 的清单与清理方案 |

## 给未来你的笔记

> 2026-08-13：隐私模型升级。`user/` 从此是本机私有层（不入 git）；敏感词清单只在本机 `.cogos/sensitive_patterns.json`；Dashboard 逐步改为只读 Cognitive Store 的真实数据（零硬编码）。demo 永远是别人看的虚构版本。

> 每次别人问起，都告诉他们：访问 `https://sunganhao8-lgtm.github.io/CognitiveOS/` 看 demo（虚构），但你的真实 dashboard 永远在本机 `D:\GitHub_Project\CognitiveOS\index.html`。
