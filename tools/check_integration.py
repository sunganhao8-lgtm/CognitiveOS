"""检测 CognitiveOS 接入状态。

回答"这个系统已经被接入了吗？"这个问题。

判定标准（按重要性排序）：
1. 用户档案是否能被加载（user/ 目录 + 关键文件）
2. Agent 能否被发现（discovery）
3. 真实对话记忆是否被提取（user/conversations/）
4. 自我规则是否被定义（user/rules/）
5. Bootstrap 流水线是否跑通（.cogos/last_report.json）
6. 派发给 Agent 的 manifest 是否能生成（brief）

每个项目分三档：
  ✓ 已就绪
  ○ 部分就绪（如有内容但数量 < 阈值）
  ✗ 未就绪

用法：
    python tools/check_integration.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保 src/ 在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.paths import Paths
from cogos.discovery import discover
from cogos.user import UserLayer
from cogos.brief import render_brief


def check_user_layer(paths: Paths) -> dict:
    """用户档案是否能被加载。"""
    user = UserLayer(root=paths.root / "user")
    required = ["manifest.md", "preferences.md", "style.md"]
    present = []
    missing = []
    for f in required:
        if (user.root / f).exists():
            present.append(f)
        else:
            missing.append(f)
    return {
        "label": "用户档案",
        "status": "✓" if not missing else "✗",
        "detail": f"已就绪 {len(present)}/{len(required)} 关键文件"
        + (f"（缺失 {missing}）" if missing else ""),
        "required": len(required),
        "present": len(present),
    }


def check_agents(paths: Paths) -> dict:
    """Agent 能否被自动发现。"""
    handles = discover(paths)
    return {
        "label": "Agent 自动发现",
        "status": "✓" if handles else "✗",
        "detail": f"已发现 {len(handles)} 个 Agent："
        + ", ".join(h.display_name for h in handles)
        if handles
        else "未发现任何 Agent（cogos 不知道你机器上有哪些 Agent）",
        "count": len(handles),
    }


def check_conversations(paths: Paths) -> dict:
    """真实对话记忆是否被提取（不是 demo / 虚构数据）。"""
    conv_dir = paths.root / "user" / "conversations"
    if not conv_dir.exists():
        return {
            "label": "对话记忆",
            "status": "✗",
            "detail": "user/conversations/ 不存在（跑 cogos ingest 提取）",
            "count": 0,
        }
    files = [f for f in conv_dir.glob("*.jsonl") if "hermes" in f.name or "codex" in f.name or "claude" in f.name]
    total = sum(
        1 for f in files for line in f.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    sources = {f.name.split("-")[0] for f in files}
    return {
        "label": "对话记忆",
        "status": "✓" if total > 50 else ("○" if total > 0 else "✗"),
        "detail": f"{len(files)} 文件 / {total} QA 对 / 来源 {', '.join(sources) or '无'}",
        "count": total,
    }


def check_rules(paths: Paths) -> dict:
    """自我规则是否被定义（verify 探针）。"""
    rules_dir = paths.root / "user" / "rules"
    if not rules_dir.exists():
        return {
            "label": "铁律规则",
            "status": "✗",
            "detail": "user/rules/ 不存在（你在 user/rules/ 写 R001.json 等）",
            "count": 0,
        }
    rules = list(rules_dir.glob("*.json"))
    return {
        "label": "铁律规则",
        "status": "✓" if rules else "✗",
        "detail": f"{len(rules)} 条规则: " + ", ".join(r.stem for r in rules)
        if rules
        else "0 条规则",
        "count": len(rules),
    }


def check_bootstrap_report(paths: Paths) -> dict:
    """Bootstrap 流水线是否跑过。"""
    last = paths.root / ".cogos" / "last_report.json"
    if not last.exists():
        return {
            "label": "Bootstrap 报告",
            "status": "✗",
            "detail": "没跑过 cogos bootstrap（先跑一次）",
        }
    rep = json.loads(last.read_text(encoding="utf-8"))
    harvested = rep.get("harvested_files", 0)
    wiki = rep.get("wiki_pages", 0)
    return {
        "label": "Bootstrap 报告",
        "status": "✓" if harvested > 0 else "○",
        "detail": f"上次 {rep.get('started_at', '?')[:19]} — harvested {harvested} 文件, {wiki} wiki 页",
        "harvested": harvested,
        "wiki": wiki,
    }


def check_brief() -> dict:
    """派发给 Agent 的 manifest 是否能生成。"""
    from cogos.user import UserLayer

    user = UserLayer(root=Paths.default().root / "user")
    try:
        brief = render_brief(user, "raw")
        lines = len(brief.split("\n"))
        return {
            "label": "Agent 入门 manifest",
            "status": "✓" if lines > 20 else "○",
            "detail": f"可生成，{lines} 行 / {len(brief)} 字符",
            "lines": lines,
        }
    except Exception as e:
        return {
            "label": "Agent 入门 manifest",
            "status": "✗",
            "detail": f"生成失败：{e}",
        }


def check_share_workspace() -> dict:
    """共享工作区（任务/收件箱/锁）初始化。"""
    import os
    from pathlib import Path

    ws_root = Path(os.environ.get("COGOS_WORKSPACE", "D:/GitHub_Project/SharedWorkspace"))
    if not ws_root.exists():
        return {
            "label": "共享工作区",
            "status": "○",
            "detail": f"未初始化（cogos workspace init --root {ws_root}）",
        }
    cogos_dir = ws_root / ".cogos"
    if not cogos_dir.exists():
        return {
            "label": "共享工作区",
            "status": "✗",
            "detail": f"{ws_root} 存在但 .cogos/ 不在",
        }
    subdirs = ["tasks", "locks", "messages"]
    present = [d for d in subdirs if (cogos_dir / d).exists()]
    return {
        "label": "共享工作区",
        "status": "✓" if len(present) == 3 else "○",
        "detail": f"{ws_root} 初始化 {len(present)}/3 ({present})"
        if present
        else f"{ws_root} 存在但 .cogos/ 子目录不全",
    }


def main():
    paths = Paths.default()

    print("\n=== CognitiveOS 接入状态检测 ===\n")
    print(f"项目根: {paths.root}")
    print(f"Python: {sys.version.split()[0]}\n")

    checks = [
        check_user_layer(paths),
        check_agents(paths),
        check_conversations(paths),
        check_rules(paths),
        check_bootstrap_report(paths),
        check_brief(),
        check_share_workspace(),
    ]

    # 打印表格
    for c in checks:
        print(f"  [{c['status']}] {c['label']:14}  {c['detail']}")

    # 总结
    ok = sum(1 for c in checks if c["status"] == "✓")
    partial = sum(1 for c in checks if c["status"] == "○")
    fail = sum(1 for c in checks if c["status"] == "✗")

    print(f"\n=== 总结 ===")
    print(f"  ✓ 已就绪: {ok}")
    print(f"  ○ 部分:   {partial}")
    print(f"  ✗ 未就绪: {fail}")

    # 严重程度评估
    critical = ["用户档案", "Agent 自动发现", "对话记忆", "Bootstrap 报告"]
    critical_ok = sum(1 for c in checks if c["label"] in critical and c["status"] == "✓")
    print(f"\n核心能力: {critical_ok}/{len(critical)} 个 ✓")

    if fail == 0 and partial == 0:
        print("\n→ CognitiveOS 已完整接入。")
    elif fail == 0:
        print("\n→ 核心功能已接入，少数功能可选扩展。")
    elif critical_ok >= 3:
        print("\n→ 核心已接入，部分功能待完成。")
    else:
        print("\n→ 接入不完整，按上面 ✗ 项逐个解决。")


if __name__ == "__main__":
    main()
