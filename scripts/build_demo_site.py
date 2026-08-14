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

from cogos.dashboard import REGIONS, TEMPLATES_DIR, MemoryItem

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
    # REGIONS.memory is empty by design (Phase 3F §11: no hardcoded
    # cognition) — the demo fabricates its own synthetic principles.
    mem = tuple(
        MemoryItem(en, zh, "demo-file.md")
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


def _demo_vm():
    """Synthetic ViewModel for the public demo — every panel is explicitly
    labeled 示例; nothing real, nothing private. Phase 3F §29."""
    from cogos.dashboard_query import (
        BrainRegionVM, CandidateVM, CognitiveDashboardViewModel, ConflictVM,
        CorrectionVM, ExecutionVM, HealthVM, LearningCardVM, OverviewVM,
        TimelineEventVM,
    )

    vm = CognitiveDashboardViewModel()
    vm.overview = OverviewVM(learned=3, applied=2, avoided_errors=1, corrected=1,
                             reused=2, conflicts_pending=0, candidates_pending=1,
                             window_days=7)
    vm.recent_learning = [
        LearningCardVM(
            id="示例 · P-SQL-001", content="（示例）复杂 SQL 使用 CTE 组织",
            subtype="preference", confidence=0.93, evidence_count=7,
            verify_pass_count=5, scope="global", scope_id="",
            formed_at="2026-08-10 09:12", user_confirmed=True, actions=["modify", "forget"]),
        LearningCardVM(
            id="示例 · R-SQL-001", content="（示例）SQL 查询禁止 SELECT *",
            subtype="rule", confidence=0.97, evidence_count=14,
            verify_pass_count=11, scope="global", scope_id="",
            formed_at="2026-08-06 18:02", user_confirmed=True, actions=["modify", "forget"]),
    ]
    vm.candidates = [
        CandidateVM(id="示例 · cand-001", content="（示例）用户似乎偏好固定的报表列顺序",
                    confidence=0.64, evidence_count=4, target_type="preference",
                    observed_at="2026-08-12 20:45"),
    ]
    vm.recent_corrections = [
        CorrectionVM(ts="2026-08-11 15:30", action="modify", memory_id="示例 · P-001",
                     old_status="confirmed", new_status="superseded",
                     old_version=1, new_version=2, reason="user explicit modification"),
    ]
    vm.timeline = [
        TimelineEventVM(date="2026-08-06", label="（示例）第一次观察到 CTE 使用", kind="observation"),
        TimelineEventVM(date="2026-08-10", label="（示例）认知形成：P-SQL-001", kind="promotion"),
        TimelineEventVM(date="2026-08-11", label="（示例）应用：销售查询任务", kind="application"),
    ]
    vm.recent_executions = [
        ExecutionVM(execution_id="示例 · ex-000021", task="（示例）帮我写销售 SQL",
                    agent_id="hermes", status="success", verdict="PASS",
                    started_at="2026-08-13 10:02", retrieved=4, applied=2,
                    memory_impact="HIGH",
                    retrieved_memories=[{"id": "示例 · R-SQL-001", "subtype": "rule",
                                         "why": "关键词命中 rank=1; scope=global (匹配任务范围)"}]),
    ]
    vm.cognitive_health = HealthVM(memory_count=22, retrieval_healthy=True,
                                   conflicts_unresolved=0, index_healthy=True,
                                   last_reindex="2026-08-13 10:28",
                                   embedding_model="bge-small-zh-v1.5",
                                   embedding_dimension=512, schema_version=4)
    vm.brain_regions = [
        BrainRegionVM(key=k, label_zh=l, brain_zh=b, color="", domain="",
                      count=c, avg_confidence=0.9, recent=["（示例）"])
        for k, l, b, c in [("prefrontal", "路由", "前额叶", 6), ("hippocampus", "规则", "海马体", 8),
                           ("cortex", "知识", "皮层", 5), ("reflection", "反思", "睡眠周期", 3)]
    ]
    return vm


def _regions_json(regions):
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
        vm=_demo_vm(),
        vm_json=json.dumps(_demo_vm().to_dict(), ensure_ascii=False),
        executions=_demo_vm().to_dict()["recent_executions"],
        memory_counts={"confirmed": 3},
        skill_count=7,
        master_name="示例主人 (Demo)",
        rules=[],
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
    cap = 120 * 1024  # 120KB cap (raised from 100KB on 2026-08-14: Phase 3F cockpit panels)
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
