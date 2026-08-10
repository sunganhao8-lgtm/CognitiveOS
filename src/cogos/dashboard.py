"""HTML Dashboard.

A single self-contained ``index.html`` that doubles as the CognitiveOS
cognitive map: a brain illustration with callout leader-lines pointing at
the seven real subsystems. Clicking a callout opens a small panel that
shows ONLY three things per region:

* a one-line description of what the region does;
* the markdown design files inside the repo that implement it;
* a list of "things this region remembers" — each item is a clickable
  link that opens the corresponding markdown file in the user's editor.

The brain artwork is ``assets/brain-source.svg`` (CC0, Wikimedia Commons).
Leader lines and hotspots are drawn in an overlay SVG that is pixel-aligned
with the artwork via a shared ``viewBox``.
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
    """One thing a region 'remembers'.

    ``path`` is a relative path inside the CognitiveOS project root; the
    dashboard opens it as a ``file://`` link so the user's editor can take
    over.
    """

    title_en: str
    title_zh: str
    path: str  # relative to repo root


@dataclass(frozen=True)
class Region:
    """One clickable region of the cognitive map."""

    key: str
    color: str
    # artwork anchor (where the leader line starts)
    ax: int
    ay: int
    # label position in the same space
    lx: int
    ly: int
    label_en: str
    label_zh: str
    desc_en: str  # one-line description
    desc_zh: str
    files: tuple[tuple[str, str], ...]  # (label, md-path-from-root)
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
        desc_en="Decides which agent should run a given task.",
        desc_zh="决定一个任务交给哪个 Agent 执行。",
        files=(
            ("Adapter protocol", "core/protocol/README.md"),
            ("Adapter list", "agents/README.md"),
        ),
        memory=(
            MemoryItem("Agent handles discovered", "已发现的 Agent 列表", "knowledge/sources/hermes/profiles/"),
            MemoryItem("Bootstrap Agent selection rule", "Bootstrap Agent 选择规则", "docs/design-decisions.md"),
            MemoryItem("Adapter whitelist", "适配器白名单", "src/cogos/adapters/hermes/adapter.py"),
        ),
    ),
    Region(
        key="thalamus",
        color="#D97706",
        ax=440, ay=400,
        lx=90, ly=400,
        label_en="Bootstrap",
        label_zh="启动",
        desc_en="Turns a user command into a CognitiveOS run.",
        desc_zh="把用户命令变成一次 CognitiveOS 运行。",
        files=(
            ("Bootstrap pipeline", "core/kernel/DESIGN.md"),
            ("Quickstart", "docs/quickstart.md"),
        ),
        memory=(
            MemoryItem("Last bootstrap report", "上一次启动报告", ".cogos/last_report.json"),
            MemoryItem("Run log", "启动日志", ".cogos/"),
            MemoryItem("Path layout", "目录布局", "docs/architecture.md"),
        ),
    ),
    Region(
        key="hippocampus",
        color="#16A34A",
        ax=560, ay=520,
        lx=900, ly=440,
        label_en="Sources",
        label_zh="原始数据",
        desc_en="Verbatim copies of each agent's data, original layout preserved.",
        desc_zh="每个 Agent 数据的原样拷贝，原始目录结构保留。",
        files=(
            ("Source whitelist rules", "docs/design-decisions.md"),
            ("Harvest contract", "core/protocol/README.md"),
        ),
        memory=(
            MemoryItem("Hermes skills", "Hermes 技能", "knowledge/sources/hermes/skills/"),
            MemoryItem("Hermes profiles", "Hermes 配置", "knowledge/sources/hermes/profiles/"),
            MemoryItem("Hermes AGENTS.md", "Hermes AGENTS", "knowledge/sources/hermes/AGENTS.md"),
            MemoryItem("Hermes SOUL.md", "Hermes SOUL", "knowledge/sources/hermes/SOUL.md"),
        ),
    ),
    Region(
        key="cortex",
        color="#7C3AED",
        ax=640, ay=330,
        lx=900, ly=250,
        label_en="Knowledge",
        label_zh="知识",
        desc_en="Structured, human-readable view over the raw sources.",
        desc_zh="原始数据之上的结构化、可读视图。",
        files=(
            ("Wiki index", "knowledge/wiki/index.md"),
            ("Normalized index", "knowledge/normalized/index.json"),
        ),
        memory=(
            MemoryItem("Hermes wiki page", "Hermes wiki", "knowledge/wiki/hermes.md"),
            MemoryItem("Wiki index", "知识索引", "knowledge/wiki/index.md"),
            MemoryItem("Normalized index", "标准化索引", "knowledge/normalized/index.json"),
        ),
    ),
    Region(
        key="reflection",
        color="#DB2777",
        ax=660, ay=540,
        lx=900, ly=560,
        label_en="Reflection",
        label_zh="反思",
        desc_en="Where CognitiveOS would learn from past tasks (v0.3).",
        desc_zh="CognitiveOS 将从过往任务中学习的地方（v0.3）。",
        files=(
            ("Sleep-cycle sketch", "reflection/sleep_cycle.md"),
            ("Roadmap", "ROADMAP.md"),
            ("Design decisions", "docs/design-decisions.md"),
        ),
        memory=(
            MemoryItem("Design decisions", "设计决策记录", "docs/design-decisions.md"),
            MemoryItem("Roadmap", "路线图", "ROADMAP.md"),
            MemoryItem("Kernel design", "Kernel 设计", "core/kernel/DESIGN.md"),
        ),
    ),
    Region(
        key="corpus",
        color="#0891B2",
        ax=500, ay=430,
        lx=90, ly=560,
        label_en="Protocol",
        label_zh="协议",
        desc_en="The bridge that keeps every agent speaking the same language.",
        desc_zh="确保每个 Agent 说同一种语言的桥梁。",
        files=(
            ("Cognitive protocol", "core/protocol/README.md"),
            ("Adapter list", "agents/README.md"),
        ),
        memory=(
            MemoryItem("AgentHandle schema", "AgentHandle 定义", "src/cogos/discovery.py"),
            MemoryItem("Adapter protocol", "适配器协议", "src/cogos/adapters/__init__.py"),
        ),
    ),
    Region(
        key="brainstem",
        color="#64748B",
        ax=490, ay=700,
        lx=490, ly=820,
        label_en="Runtime",
        label_zh="运行时",
        desc_en="How you install CognitiveOS and invoke `cogos`.",
        desc_zh="CognitiveOS 的安装与命令入口。",
        files=(
            ("Package config", "pyproject.toml"),
            ("Quickstart", "docs/quickstart.md"),
        ),
        memory=(
            MemoryItem("CLI commands", "CLI 命令清单", "docs/quickstart.md"),
            MemoryItem("Path layout", "目录布局", "src/cogos/paths.py"),
            MemoryItem("Install command", "安装命令", "pyproject.toml"),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_dashboard(paths: Paths) -> Path:
    """Render the root ``index.html``; return its on-disk path."""
    paths.root.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    html = template.render(
        regions=REGIONS,
        regions_json=_regions_json(REGIONS),
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
            "desc_en": r.desc_en,
            "desc_zh": r.desc_zh,
            "files": [list(pair) for pair in r.files],
            "memory": [{"title_en": m.title_en, "title_zh": m.title_zh, "path": m.path} for m in r.memory],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")