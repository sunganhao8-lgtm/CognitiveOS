"""Build a public demo site (GitHub Pages).

The demo site is built from FAKE data so nothing personal leaks:

- Projects: fictional example entries
- Q&A: clearly-labelled sample exchanges
- Region memory: generic principles (no [REDACTED] / no privacy red lines)

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
        type(r.memory[0])(en, zh, "") for en, zh in demos.get(r.key, (("(demo)", "(示例)"),))
    )
    DEMO_REGIONS.append(type(r)(
        key=r.key, color=r.color, ax=r.ax, ay=r.ay, lx=r.lx, ly=r.ly,
        label_en=r.label_en, label_zh=r.label_zh, brain_en=r.brain_en,
        brain_zh=r.brain_zh, desc_en=r.desc_en, desc_zh=r.desc_zh,
        role_en=r.role_en, role_zh=r.role_zh,
        memory=mem))


def _regions_json(regions) -> str:
    payload = [
        {
            "key": r.key, "color": r.color, "ax": r.ax, "ay": r.ay, "lx": r.lx, "ly": r.ly,
            "label_en": r.label_en, "label_zh": r.label_zh,
            "brain_en": r.brain_en, "brain_zh": r.brain_zh,
            "desc_en": r.desc_en, "desc_zh": r.desc_zh,
            "memory": [{"title_en": m.title_en, "title_zh": m.title_zh, "path": m.path} for m in r.memory],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


DEMO_PROJECTS = [
    {"title": "Demo Project Alpha", "path": "#", "note": "example: an example project"},
    {"title": "Demo Project Beta", "path": "#", "note": "example: another example"},
]

DEMO_QA = [
    {"session_id": "demo", "question_id": 1, "question": "DEMO: how does CognitiveOS discover my agents?", "answer": "", "timestamp": "2026-08-10"},
    {"session_id": "demo", "question_id": 2, "question": "DEMO: what does the brain map do?", "answer": "", "timestamp": "2026-08-09"},
    {"session_id": "demo", "question_id": 3, "question": "DEMO: can I move my user/ layer to another machine?", "answer": "", "timestamp": "2026-08-08"},
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
        recent_qa=DEMO_QA,
        master_name="Example Master",
        rules=[
            "示例规则：先行动，不可逆才确认",
            "示例规则：本地优先",
            "示例规则：结论先行",
        ],
    )

    demo_dir = ROOT / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    (demo_dir / "index.html").write_text(html, encoding="utf-8")

    assets = demo_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    src_art = ROOT / "assets" / "brain-source.svg"
    if src_art.exists():
        shutil.copy2(src_art, assets / "brain-source.svg")

    print(f"demo site -> {demo_dir / 'index.html'} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
