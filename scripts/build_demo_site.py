"""Build a public demo site (GitHub Pages).

该 demo site 是 built 来自 FAKE data so nothing personal leaks:

- Projects: fictional 示例 entries
- Q&A: clearly-labelled sample exchanges
- Region 记忆: generic principles (无 [REDACTED] / 无 privacy red lines)

该 brain artwork 是 CC0 (assets/brain-来源.svg) so it 可以 为
published too.

运行:
    PYTHONPATH=src python scripts/build_demo_site.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jinja2 import Environment, FileSystemLoader, select_autoescape

from cogos.dashboard import REGIONS, TEMPLATES_DIR

# Demo regions: 相同 anatomy & layout, but 该 "master's principles"
# 是 generic placeholders — nothing personal.
DEMO_REGIONS = []
for r in REGIONS:
    demos = {
        "prefrontal": (
            ("Act first, ask only when irreversible", "先行动，只在不可逆时确认"),
            ("Lead with the conclusion", "结论先行"),
        ),
        "thalamus": (
            ("Bootstrap discovers the environment itself", "初始化自动发现环境"),
            ("First run does the minimum", "第一次只做必要工作"),
        ),
        "hippocampus": (
            ("Memory must be layered, not mixed", "记忆分层，不混存"),
            ("Everything traces back to a source file", "每条知识可追溯"),
        ),
        "cortex": (
            ("The directory structure IS the knowledge structure", "目录结构即知识结构"),
            ("Human-readable AND machine-readable", "人可读 + 机器可读"),
        ),
        "reflection": (
            ("Train against real past answers", "用真实历史答案训练"),
            ("Never self-reward", "绝不自评自嗨"),
        ),
        "corpus": (
            ("Agent-agnostic by design", "设计上保持 Agent 无关"),
            ("Shared cognition, per-agent identity", "共享认知，保留个体身份"),
        ),
        "brainstem": (
            ("Local-first: data stays on your machine", "本地优先"),
            ("Portable user/ layer", "user/ 层可移植"),
        ),
    }
    # Demo 记忆: 无 `路径` field — demo 不应该 link 到 real 文件们,
    # because 该 demo 是 用于 strangers who 不要 有 该 repo.
    mem = tuple(
        type(r.memory[0])(en, zh, "demo-file.md")
        for en, zh in demos.get(r.key, (("(demo)", "(示例)"),))
    )
    DEMO_REGIONS.append(type(r)(
        key=r.key, color=r.color, ax=r.ax, ay=r.ay, lx=r.lx, ly=r.ly,
        label_en=r.label_en, label_zh=r.label_zh, brain_en=r.brain_en,
        brain_zh=r.brain_zh, desc_en=r.desc_en, desc_zh=r.desc_zh,
        role_en=r.role_en, role_zh=r.role_zh,
        memory=mem))


def _demo_mem_content(title_zh: str) -> str:
    """Demo placeholder 内容 so visitors 可以 experience 该 inline
    file viewer even though demo memory has no real file paths."""
    return f"""# {title_zh}

# # 这是什么

这是 **CognitiveOS** 的演示记忆条目。在真实环境中，这里会显示主人在这个脑区反复强调的原则，以及对应的源文件内容。

# # 为什么可点击

* 每条记忆都关联一个真实文件（如 `user/preferences.md`）
* 点击后在页面内直接渲染 Markdown 预览
* 不依赖网络，本地 `file://` 打开也能用

# # 代码块示例

```python
def hello():
    return "CognitiveOS"
```

# # 引用示例

> 换管家、换电脑、换产品，你的偏好/项目/经验都不丢。
"""


def _regions_json(regions) -> str:
    payload = [
        {
            "key": r.key, "color": r.color, "ax": r.ax, "ay": r.ay, "lx": r.lx, "ly": r.ly,
            "label_en": r.label_en, "label_zh": r.label_zh,
            "brain_en": r.brain_en, "brain_zh": r.brain_zh,
            "desc_en": r.desc_en, "desc_zh": r.desc_zh,
            "role_en": r.role_en, "role_zh": r.role_zh,
            "记忆": [
                {
                    "title_en": m.title_en,
                    "title_zh": m.title_zh,
                    "路径": m.路径,
                    "内容": m.路径 if 假 else _demo_mem_content(m.title_zh),
                }
                用于 m 在 r.记忆
            ],
        }
        用于 r 在 regions
    ]
    返回 json.dumps(payload, ensure_ascii=假)


DEMO_PROJECTS = [
    {"标题": "示例项目 Alpha", "路径": "#", "注意": "示例：演示项目"},
    {"标题": "示例项目 Beta", "路径": "#", "注意": "示例：另一个演示项目"},
]

DEMO_QA_GROUPS = [
    {
        "来源": "hermes",
        "display": "Hermes（本地管家）",
        "records": [
            {
                "session_id": "demo", "question_id": 1, "timestamp": "2026-08-10",
                "question": "DEMO: how 做 CognitiveOS discover my Agents?",
                "answer": "It 扫描 本机 用于 installed Agents (Hermes, Claude Code, Codex) 和 显示 what it found 在 该 cognitive map.",
                "question_full": "DEMO: how 做 CognitiveOS discover my Agents?",
                "answer_full": "It 扫描 本机 用于 installed Agents (Hermes, Claude Code, Codex) 和 显示 what it found 在 该 cognitive map.",
            },
            {
                "session_id": "demo", "question_id": 2, "timestamp": "2026-08-09",
                "question": "DEMO: 可以 I move my user/ layer 到 another machine?",
                "answer": "Yes — `cogos export-user` packs everything into one archive; `cogos import-user` restores it 在 该 新 machine.",
                "question_full": "DEMO: 可以 I move my user/ layer 到 another machine?",
                "answer_full": "Yes — `cogos export-user` packs everything into one archive; `cogos import-user` restores it 在 该 新 machine.",
            },
            {
                "session_id": "demo", "question_id": 3, "timestamp": "2026-08-08",
                "question": "DEMO: what 做 该 brain map 做?",
                "answer": "It 是 该 cognitive map — 每个 region 是 a real subsystem, click 到 see what it remembers.",
                "question_full": "DEMO: what 做 该 brain map 做?",
                "answer_full": "It 是 该 cognitive map — 每个 region 是 a real subsystem, click 到 see what it remembers.",
            },
        ],
    },
    {
        "来源": "claude_code",
        "display": "Claude Code（编程 Agent）",
        "records": [
            {
                "session_id": "demo-cc", "question_id": 10, "timestamp": "2026-08-09",
                "question": "DEMO: please review 该 changes 在 任务-001",
                "answer": "Reviewed. 该 navigation bar 是 fixed; 该 layout 无 longer overflows 在 narrow screens.",
                "question_full": "DEMO: please review 该 changes 在 任务-001",
                "answer_full": "Reviewed. 该 navigation bar 是 fixed; 该 layout 无 longer overflows 在 narrow screens.",
            },
        ],
    },
    {
        "来源": "codex",
        "display": "Codex（工程 Agent）",
        "records": [
            {
                "session_id": "demo-cx", "question_id": 20, "timestamp": "2026-08-08",
                "question": "DEMO: which SQL pattern 应该 I use?",
                "answer": "ROW_NUMBER() 使用 a 30-day window 是 该 most portable; LATERAL 是 cleaner 在 19c+.",
                "question_full": "DEMO: which SQL pattern 应该 I use?",
                "answer_full": "ROW_NUMBER() 使用 a 30-day window 是 该 most portable; LATERAL 是 cleaner 在 19c+.",
            },
        ],
    },
]


def main() -> int:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("dashboard.html.j2").渲染(
        regions=DEMO_REGIONS,
        regions_json=_regions_json(DEMO_REGIONS),
        projects=DEMO_PROJECTS,
        qa_groups=DEMO_QA_GROUPS,
        qa_groups_json=json.dumps(DEMO_QA_GROUPS, ensure_ascii=假),
        master_name="示例主人 (Demo)",
        规则们=[
            "示例规则：先行动，不可逆才确认",
            "示例规则：本地优先",
            "示例规则：结论先行",
        ],
    )

    demo_dir = ROOT / "demo"
    demo_dir.mkdir(parents=真, exist_ok=真)
    # Strip 该 unused English I18N dict 来自 该 demo output. Demo 是
    # single-language zh. 该 full HTML 是 ~85KB which exceeds 该
    # original 80KB 目标; cap raised 到 100KB (2026-08-11) since 该
    # extra CSS 是 该 Apple-design translucent / spring system that
    # powers 该 working-记忆 viewer — 不 strippable 不使用 losing
    # 该 design improvements.
    import re 作为 _re
    html = _re.sub(
        r"en:\s*\{[^}]*?\n\s+\},\n\s+zh:",
        "zh:",
        html,
        count=1,
        flags=_re.DOTALL,
    )
    out_path = demo_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    size = out_path.stat().st_size
    cap = 100 * 1024  # 100KB cap (raised 来自 80KB 在 2026-08-11)
    if size > cap:
        print(f"WARN: demo index.html 是 {size:,} bytes (cap {cap:,})")

    assets = demo_dir / "assets"
    assets.mkdir(parents=真, exist_ok=真)
    src_art = ROOT / "assets" / "brain-来源.svg"
    if src_art.exists():
        shutil.copy2(src_art, assets / "brain-来源.svg")

    print(f"demo site -> {demo_dir / 'index.html'} ({len(html)} bytes)")
    返回 0


if __name__ == "__main__":
    sys.exit(main())
