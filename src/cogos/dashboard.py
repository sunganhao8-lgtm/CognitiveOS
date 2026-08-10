"""HTML Dashboard.

A single self-contained ``index.html`` that doubles as the CognitiveOS
cognitive map: a brain illustration with callout leader-lines pointing at
the seven real subsystems. Clicking a callout opens the **working memory**
strip below the map.

Design notes (user-directed):

* The map is the visual anchor — "this is a system that thinks like a
  brain" — so every region keeps its anatomical name (海马体 / 前额叶 …).
* Working memory shows what the MASTER cares about and repeats — the
  rules, preferences and principles — NOT file paths. File paths are
  secondary detail and only appear inline when genuinely useful.
* A second tab (About / 关于) presents the master's own vision document
  (from the ChatGPT conversation) as a static HTML page, so the
  dashboard also carries the philosophy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .paths import Paths


TEMPLATES_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Brain regions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryItem:
    """One thing a region remembers — a PRINCIPLE the master cares about.

    ``path`` is optional; when present it becomes a small inline link so
    the master can jump to the source, but it is NOT the headline.
    """

    title_en: str
    title_zh: str
    path: str = ""


@dataclass(frozen=True)
class Region:
    key: str
    color: str
    ax: int
    ay: int
    lx: int
    ly: int
    label_en: str
    label_zh: str
    brain_en: str  # anatomical name (English)
    brain_zh: str  # anatomical name (中文)
    desc_en: str
    desc_zh: str
    # The principles the master cares about most, in this region.
    memory: tuple[MemoryItem, ...]


# Brain viewBox 960x960; anchors are eyeballed against the artwork.
REGIONS: tuple[Region, ...] = (
    Region(
        key="prefrontal",
        color="#E89A3C",
        ax=330, ay=300,
        lx=90, ly=210,
        label_en="Router",
        label_zh="路由",
        brain_en="Prefrontal Cortex",
        brain_zh="前额叶",
        desc_en="Decides which agent should run a given task — the planning & decision centre.",
        desc_zh="决定任务交给哪个 Agent——规划与决策中枢。",
        memory=(
            MemoryItem("Hands-off by default; only confirm irreversible actions", "默认别每步问我；只有不可逆操作才确认"),
            MemoryItem("Lead with the conclusion; details after", "结论先行，过程后置"),
            MemoryItem("\"[REDACTED] / [REDACTED]\" means: act now, don't explain", "听到「[REDACTED] / [REDACTED]」：立刻执行，不解释"),
        ),
    ),
    Region(
        key="thalamus",
        color="#D97706",
        ax=440, ay=400,
        lx=90, ly=400,
        label_en="Bootstrap",
        label_zh="启动",
        brain_en="Thalamus",
        brain_zh="丘脑",
        desc_en="Sensory relay — first run must be automatic, no manual directory lists.",
        desc_zh="感官中继——首次初始化必须全自动，不需要用户手动告诉读哪些目录。",
        memory=(
            MemoryItem("Bootstrap discovers the environment itself; never ask what to scan", "初始化要自己发现环境，绝不问「要扫描哪些目录」"),
            MemoryItem("First run does the minimum; refine progressively", "第一次只做必要工作，后续逐步完善"),
            MemoryItem("Produce a JSON report every run", "每次运行都要产出 JSON 报告"),
        ),
    ),
    Region(
        key="hippocampus",
        color="#16A34A",
        ax=560, ay=520,
        lx=900, ly=440,
        label_en="Sources",
        label_zh="原始数据",
        brain_en="Hippocampus",
        brain_zh="海马体",
        desc_en="Long-term memory formation — raw data, original layout preserved.",
        desc_zh="长期记忆形成——原始数据，保留原始目录结构。",
        memory=(
            MemoryItem("Memory must be layered; never mix everything together", "记忆必须分层，不能把什么都混在一起记"),
            MemoryItem("Traceability: source → normalized → wiki, always reversible", "可追溯：原始 → 标准化 → wiki，层层可查"),
            MemoryItem("Resume privacy: never name the chip fabs; say \"factory-side\" only", "简历隐私红线：不写具体公司名，只说「工厂智能化相关」"),
            MemoryItem("The store is 筹备阶段, not failed; brand is 品牌叫[REDACTED]", "铺子说「筹备阶段」不说「没开起来」；品牌叫「[REDACTED]」"),
        ),
    ),
    Region(
        key="cortex",
        color="#7C3AED",
        ax=640, ay=330,
        lx=900, ly=250,
        label_en="Knowledge",
        label_zh="知识",
        brain_en="Cortex",
        brain_zh="皮层",
        desc_en="Integration of experience into generalised, queryable knowledge.",
        desc_zh="把经验整合成可查询的通用知识。",
        memory=(
            MemoryItem("The directory structure IS the knowledge structure", "目录结构本身就是知识结构"),
            MemoryItem("Human-readable AND machine-readable", "知识库要人可读，也要机器可读"),
            MemoryItem("No giant everything.json — keep it vertical and tidy", "不要一个巨大的 everything.json——垂直、整洁、可追溯"),
        ),
    ),
    Region(
        key="reflection",
        color="#DB2777",
        ax=660, ay=540,
        lx=900, ly=560,
        label_en="Reflection",
        label_zh="反思",
        brain_en="Sleep Cycle",
        brain_zh="睡眠周期",
        desc_en="Offline consolidation — what the system learns after tasks (v0.3).",
        desc_zh="离线巩固——任务结束后系统学到什么（v0.3）。",
        memory=(
            MemoryItem("Train on real past Q&A, compare against the master's actual words", "用过去真实的问答训练，对照主人原话做语义匹配打分"),
            MemoryItem("Never self-reward; the master's judgement is the signal", "绝不自评自嗨；主人的判断才是训练信号"),
            MemoryItem("Lessons become long-term memory; task state stays in the session", "教训进长期记忆；任务进度留在会话里"),
        ),
    ),
    Region(
        key="corpus",
        color="#0891B2",
        ax=500, ay=430,
        lx=90, ly=560,
        label_en="Protocol",
        label_zh="协议",
        brain_en="Corpus Callosum",
        brain_zh="胼胝体",
        desc_en="The bridge — agents share knowledge without being merged.",
        desc_zh="左右脑的桥——Agent 之间共享知识但不合并。",
        memory=(
            MemoryItem("Hermes is the first adapter, NOT the core", "Hermes 是第一个 Adapter，不是 CognitiveOS 的核心"),
            MemoryItem("Agent-agnostic: no if-hermes / elif-claude switch", "与 Agent 无关：不做 if Hermes / elif Claude 的硬编码"),
            MemoryItem("Shared cognition, per-agent identity preserved", "统一认知，但保留每个 Agent 的来源与身份"),
        ),
    ),
    Region(
        key="brainstem",
        color="#64748B",
        ax=490, ay=700,
        lx=490, ly=820,
        label_en="Runtime",
        label_zh="运行时",
        brain_en="Brainstem",
        brain_zh="脑干",
        desc_en="Life support — install, paths, CLI. Boring but essential.",
        desc_zh="生命维持——安装、路径、命令行。无聊但必不可少。",
        memory=(
            MemoryItem("Local-first: your data stays on your machine", "本地优先：数据默认留在本地"),
            MemoryItem("When tooling is missing: install/fix/wire it, don't retreat", "工具链缺失时默认走「装/修/接」路径，不给退缩型选项"),
            MemoryItem("Portable: user/ travels to any machine, any agent", "可移植：user/ 能带到任何电脑、任何 Agent"),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_dashboard(paths: Paths) -> Path:
    """Render the root ``index.html``; return its on-disk path."""
    paths.root.mkdir(parents=True, exist_ok=True)

    # Active projects: read directly from user/projects/. INDEX.md first.
    user_dir = paths.root / "user"
    projects: list[dict] = []
    projects_index = user_dir / "projects" / "INDEX.md"
    if projects_index.exists():
        for line in projects_index.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("- ["):
                continue
            import re as _re
            m = _re.match(r"^- \[([^\]]+)\]\(([^)]+)\)\s*(?:—\s*(.*))?$", line)
            if m:
                projects.append({"title": m.group(1), "path": m.group(2), "note": m.group(3) or ""})

    # Recent Q/A: most recent 6 entries from user/conversations/hermes-*.jsonl.
    qa_records: list[dict] = []
    conv_dir = user_dir / "conversations"
    if conv_dir.exists():
        for f in sorted(conv_dir.glob("hermes-*.jsonl"), reverse=True):
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                qa_records.append(json.loads(line))
    qa_records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    recent_qa = qa_records[:6]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    html = template.render(
        regions=REGIONS,
        regions_json=_regions_json(REGIONS),
        projects=projects,
        recent_qa=recent_qa,
        master_name="Lin's Cognitive Layer",
        rules=[
            "叫「品牌叫[REDACTED]」",
            "AI 是核心杠杆",
            "店铺处于筹备阶段",
            "简历 隐私红线",
            "hands-off 模式",
        ],
    )

    out = paths.dashboard_index
    out.write_text(html, encoding="utf-8")
    return out


def _regions_json(regions: tuple[Region, ...]) -> str:
    payload = [
        {
            "key": r.key,
            "color": r.color,
            "ax": r.ax,
            "ay": r.ay,
            "lx": r.lx,
            "ly": r.ly,
            "label_en": r.label_en,
            "label_zh": r.label_zh,
            "brain_en": r.brain_en,
            "brain_zh": r.brain_zh,
            "desc_en": r.desc_en,
            "desc_zh": r.desc_zh,
            "memory": [
                {"title_en": m.title_en, "title_zh": m.title_zh, "path": m.path}
                for m in r.memory
            ],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)