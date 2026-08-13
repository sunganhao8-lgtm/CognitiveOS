"""Build a public demo site (GitHub Pages).

The demo site is built from FAKE data so nothing personal leaks:

- Projects: fictional example entries
- Q&A: clearly-labelled sample exchanges
- Region memory: generic principles only (no real user preferences / no privacy red lines)

The brain artwork is CC0 (assets/brain-source.svg) so it can be
published too.

Run:
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

# Demo regions: same anatomy & layout, but the "master's principles"
# are generic placeholders — nothing personal.
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
    # Demo memory: no `path` field — demo should NOT link to real files,
    # because the demo is for strangers who do not have the repo.
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
    """Demo placeholder content so visitors can experience the inline
    file viewer even though demo memory has no real file paths."""
    return f"""# {title_zh}

## 这是什么

这是 **CognitiveOS** 的演示记忆条目。在真实环境中，这里会显示主人在这个脑区反复强调的原则，以及对应的源文件内容。

## 为什么可点击

* 每条记忆都关联一个真实文件（如 `user/preferences.md`）
* 点击后在页面内直接渲染 Markdown 预览
* 不依赖网络，本地 `file://` 打开也能用

## 代码块示例

```python
def hello():
    return "CognitiveOS"
```

## 引用示例

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
            "memory": [
                {
                    "title_en": m.title_en,
                    "title_zh": m.title_zh,
                    "path": m.path,
                    "content": m.path if False else _demo_mem_content(m.title_zh),
                }
                for m in r.memory
            ],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


DEMO_PROJECTS = [
    {"title": "示例项目 Alpha", "path": "#", "note": "示例：演示项目"},
    {"title": "示例项目 Beta", "path": "#", "note": "示例：另一个演示项目"},
]

DEMO_QA_GROUPS = [
    {
        "source": "hermes",
        "display": "Hermes（本地管家）",
        "records": [
            {
                "session_id": "demo", "question_id": 1, "timestamp": "2026-08-10",
                "question": "DEMO: how does CognitiveOS discover my agents?",
                "answer": "It scans this machine for installed agents (Hermes, Claude Code, Codex) and shows what it found on the cognitive map.",
                "question_full": "DEMO: how does CognitiveOS discover my agents?",
                "answer_full": "It scans this machine for installed agents (Hermes, Claude Code, Codex) and shows what it found on the cognitive map.",
            },
            {
                "session_id": "demo", "question_id": 2, "timestamp": "2026-08-09",
                "question": "DEMO: can I move my user/ layer to another machine?",
                "answer": "Yes — `cogos export-user` packs everything into one archive; `cogos import-user` restores it on the new machine.",
                "question_full": "DEMO: can I move my user/ layer to another machine?",
                "answer_full": "Yes — `cogos export-user` packs everything into one archive; `cogos import-user` restores it on the new machine.",
            },
            {
                "session_id": "demo", "question_id": 3, "timestamp": "2026-08-08",
                "question": "DEMO: what does the brain map do?",
                "answer": "It is the cognitive map — each region is a real subsystem, click to see what it remembers.",
                "question_full": "DEMO: what does the brain map do?",
                "answer_full": "It is the cognitive map — each region is a real subsystem, click to see what it remembers.",
            },
        ],
    },
    {
        "source": "claude_code",
        "display": "Claude Code（编程 Agent）",
        "records": [
            {
                "session_id": "demo-cc", "question_id": 10, "timestamp": "2026-08-09",
                "question": "DEMO: please review the changes in TASK-001",
                "answer": "Reviewed. The navigation bar is fixed; the layout no longer overflows on narrow screens.",
                "question_full": "DEMO: please review the changes in TASK-001",
                "answer_full": "Reviewed. The navigation bar is fixed; the layout no longer overflows on narrow screens.",
            },
        ],
    },
    {
        "source": "codex",
        "display": "Codex（工程 Agent）",
        "records": [
            {
                "session_id": "demo-cx", "question_id": 20, "timestamp": "2026-08-08",
                "question": "DEMO: which SQL pattern should I use?",
                "answer": "ROW_NUMBER() with a 30-day window is the most portable; LATERAL is cleaner on 19c+.",
                "question_full": "DEMO: which SQL pattern should I use?",
                "answer_full": "ROW_NUMBER() with a 30-day window is the most portable; LATERAL is cleaner on 19c+.",
            },
        ],
    },
]


def main() -> int:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("dashboard.html.j2").render(
        regions=DEMO_REGIONS,
        regions_json=_regions_json(DEMO_REGIONS),
        projects=DEMO_PROJECTS,
        qa_groups=DEMO_QA_GROUPS,
        qa_groups_json=json.dumps(DEMO_QA_GROUPS, ensure_ascii=False),
        master_name="示例主人 (Demo)",
        rules=[
            "示例规则：先行动，不可逆才确认",
            "示例规则：本地优先",
            "示例规则：结论先行",
        ],
    )

    demo_dir = ROOT / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    # Strip the unused English I18N dict from the demo output. Demo is
    # single-language zh. The full HTML is ~85KB which exceeds the
    # original 80KB target; cap raised to 100KB (2026-08-11) since the
    # extra CSS is the Apple-design translucent / spring system that
    # powers the working-memory viewer — not strippable without losing
    # the design improvements.
    import re as _re
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
    cap = 100 * 1024  # 100KB cap (raised from 80KB on 2026-08-11)
    if size > cap:
        print(f"WARN: demo index.html is {size:,} bytes (cap {cap:,})")

    assets = demo_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    src_art = ROOT / "assets" / "brain-source.svg"
    if src_art.exists():
        shutil.copy2(src_art, assets / "brain-source.svg")

    print(f"demo site -> {demo_dir / 'index.html'} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
