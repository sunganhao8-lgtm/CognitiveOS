# 隐私修复方案（P0-1）

> 状态：**方案文档 + 部分本地止血已执行**。涉及 git 历史重写的操作**均未执行**，等主人确认。
> 本文件属于公开仓库，因此**不包含任何真实敏感词**——敏感词清单只存在于本机 `.cogos/sensitive_patterns.json`（gitignored）。下文用「类别」描述。

---

## 1. 事实确认（2026-08-13 扫描）

公开仓库 `github.com/sunganhao8-lgtm/CognitiveOS` 的 origin/main 上，以下**被 git 跟踪**的文件含主人真实隐私（按类别描述，具体词见本机清单）：

| 文件 | 泄漏类别 |
|---|---|
| `user/manifest.md` | 公司名×2（简历红线明文）、品牌名、项目阶段 |
| `user/preferences.md` | 公司名×2、品牌名、沟通习惯 |
| `user/README.md` | 公司名×2（红线说明）、品牌名、项目阶段 |
| `user/style.md` | 沟通习惯口头禅 |
| `user/projects/zhaiyu-bp.md` | 公司名×2、品牌名 |
| `user/projects/INDEX.md` | 品牌名 |
| `user/cognitive/INDEX.md` | 品牌名、项目布局 |
| `user/experience/*.md`（2 个文件） | 品牌名、口头禅 |
| `src/cogos/dashboard.py` | 品牌名、红线摘要、口头禅、主人署名 |
| `tests/test_verify.py` | 公司名×2、品牌名（测试夹具 + canary 正则） |
| `scripts/test_butler_brief.py` | 品牌名（验证 prompt 硬编码） |
| `scripts/build_demo_site.py` | 品牌名（注释） |
| `docs/USAGE.md` | 公司名×2、品牌名、主人署名 |
| `.github/workflows/pages.yml` | 公司名×2、品牌名、主人署名（pre-flight 的 grep 模式） |

**git 历史**：`user/` 相关提交共 4 个（自 `2276163 feat(user): introduce user/ cognitive layer` 起），即这些内容在**每一个后续提交里都可见**。

---

## 2. 本轮已执行的止血（本地文件修改，未 commit）

| 文件 | 处置 | 说明 |
|---|---|---|
| `src/cogos/dashboard.py` | 主人署名→「主人」；5 条真实规则→空列表；REGIONS 中 5 条真实偏好→中性设计原则 | 对应「数据真实性原则」：真实数据 Phase 2C 从 Cognitive Store 读取 |
| `tests/test_verify.py` | 测试夹具换中性示例；canary 改为双层——结构性断言（随仓库发布）+ 本机清单实质性断言（gitignored） | 公开仓库不再含真实词，本地防泄漏强度不降 |
| `scripts/test_butler_brief.py` | 验证 prompt 改为通用措辞（运行时仍读本机 brief，功能不变） | — |
| `scripts/build_demo_site.py` | 注释去掉品牌名 | — |
| `docs/USAGE.md` | 全文重写：隐私边界改为「user/ 本机私有 + 清单本机化 + Secret 化 pre-flight」的目标状态 | — |
| 新增 `.cogos/sensitive_patterns.json` | 本机敏感词清单（.cogos/ 已 gitignored） | 供本地 canary 测试 + 后续扫描工具使用 |

---

## 3. 待执行方案（分两步，均需主人确认）

### 方案 A：停止继续泄漏（普通 commit，可逆）

```bash
# 1. user/ 整体排除出 git
echo "user/" >> .gitignore

# 2. 取消跟踪（本地文件保留，只是不再进 git）
git rm -r --cached user/

# 3. 提交并推送（正常 commit，非 force push）
git commit -m "privacy: untrack user/ layer entirely; move master data to local-only"
git push
```

**效果**：之后克隆仓库的人看不到任何 `user/` 内容。**局限**：git 历史里的旧版本仍然含隐私（方案 B 解决）。

### 方案 B：清理 git 历史（不可逆，必须确认后执行）

| 选项 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **B1（推荐）** | `git filter-repo --invert-paths --path user/ --path src/cogos/dashboard.py --path tests/test_verify.py --path scripts/test_butler_brief.py --path scripts/build_demo_site.py --path docs/USAGE.md --path .github/workflows/pages.yml` 后 force push | 历史彻底干净，仓库保留 | 所有协作者需重新 clone；commit hash 全变 |
| B2 | 删库重建（GitHub 上删除，本地重新 init，只推清理后的版本） | 最彻底（连 star/fork 都清零，当前无 fork 损失为零） | 丢失 issue/commit 记录；PR 引用失效 |
| B3 | 只做方案 A，接受历史可见 | 零风险 | 隐私仍在历史里，任何看过的人可追溯 |

**B1 具体步骤**（届时执行）：

```bash
pip install git-filter-repo
git clone --mirror https://github.com/sunganhao8-lgtm/CognitiveOS.git cogos-mirror.git
cd cogos-mirror.git
git filter-repo --invert-paths \
  --path user/ \
  --path src/cogos/dashboard.py \
  --path tests/test_verify.py \
  --path scripts/test_butler_brief.py \
  --path scripts/build_demo_site.py \
  --path docs/USAGE.md \
  --path .github/workflows/pages.yml
git push --force --mirror
```

**B1 风险提示**（必须知情）：

- commit hash 全部改变，本地仓库需 `git fetch` + `git reset --hard origin/main`（或重新 clone）。
- GitHub 的 raw.githubusercontent 缓存可能短暂保留旧 commit 内容（一般数分钟到数小时）。
- 第三方 fork / 搜索引擎缓存不受控制——如果泄漏时间已久，按「已泄露」对待：简历措辞本就该按红线写（不说具体公司名），历史泄漏不影响红线的正确性，但品牌名与项目阶段信息视为公开。
- Pages 部署不受影响（demo 是虚构数据，从新历史重新构建即可）。

**建议顺序**：先执行方案 A（立即止血，今天就能做）→ 同日或次日执行 B1（彻底清理）→ 清理后重建本地仓库。

---

## 4. 长期防线（与方案 A/B 配套）

1. **`user/` 永入 .gitignore**（方案 A 完成）。
2. **敏感词清单本机化**：`.cogos/sensitive_patterns.json`（已完成）+ 本地 canary 测试（已完成）。
3. **CI pre-flight 模式 Secret 化**：`pages.yml` 里的 grep 模式改为从 GitHub Secret `COGOS_PRIVACY_PATTERNS` 读取——仓库里不再出现真实词（需主人在 GitHub 设置里建 Secret，然后我改 workflow）。
4. **新增敏感词时的流程**：更新本机 `.cogos/sensitive_patterns.json` + 更新 GitHub Secret——**两处同步**，漏一个就是泄漏一次（与 pages.yml 现有机制同构）。
5. **提交前扫描**：未来可加 pre-commit hook（`git grep` 本机清单，命中即拒）。Phase 2B 落地后顺手做。

---

## 5. 需要主人确认的事项

| # | 事项 | 我的建议 |
|---|---|---|
| 1 | 方案 A（untrack user/ + 推送）是否可以现在执行？ | 是，立即做 |
| 2 | 方案 B 选哪个？（B1 filter-repo / B2 删库重建 / B3 接受历史） | B1 |
| 3 | B1 之后，本地仓库要我重建吗？ | 是，我来做 |
| 4 | 是否在 GitHub 创建 Secret `COGOS_PRIVACY_PATTERNS`（值=本机清单内容）？ | 是，创建后告诉我 |
