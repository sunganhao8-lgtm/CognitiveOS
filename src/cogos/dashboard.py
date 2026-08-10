"""HTML Dashboard.

A single self-contained ``index.html`` that doubles as the CognitiveOS
cognitive map: a brain illustration with callout leader-lines pointing at
the seven real subsystems. Clicking a callout (or its label) opens a panel
that lists the region's responsibilities, the files that implement it, and
a short prose summary.

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
# Brain regions — every region maps to a REAL CognitiveOS subsystem.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Region:
    """One clickable region of the cognitive map.

    Coordinates are in the artwork's own 960×960 space (``brain-source.svg``).
    """

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
    brain_en: str
    brain_zh: str
    summary_en: str
    summary_zh: str
    responsibilities_en: tuple[str, ...]
    responsibilities_zh: tuple[str, ...]
    files: tuple[tuple[str, str], ...]  # (label, relative-path-from-root)


# The brain in brain-source.svg occupies roughly x:110–850, y:120–760
# (960×960 canvas). Anchors below are eyeballed against the artwork; the
# leader lines are drawn from anchor to a label placed just outside the
# silhouette so nothing overlaps the gyri.
REGIONS: tuple[Region, ...] = (
    Region(
        key="prefrontal",
        color="#E89A3C",  # warm orange
        ax=330, ay=300,
        lx=90, ly=210,
        label_en="Router",
        label_zh="路由",
        brain_en="Prefrontal Cortex",
        brain_zh="前额叶",
        summary_en=(
            "Decides *what* should run when a task arrives. The discovery "
            "layer scans this machine for installed agents; the adapter "
            "layer gives every agent a uniform interface."
        ),
        summary_zh=(
            "决定任务到来时*该做什么*。发现层扫描本机已安装的 Agent；"
            "适配器层给每个 Agent 提供统一接口。"
        ),
        responsibilities_en=(
            "Scan the local machine for AI agents",
            "Pick a Bootstrap Agent on first run",
            "Provide one Adapter per agent (Hermes today)",
            "Stay agent-agnostic — no agent-specific code lives here",
        ),
        responsibilities_zh=(
            "扫描本机已安装的 AI Agent",
            "首次运行时选择 Bootstrap Agent",
            "为每个 Agent 提供适配器（目前 Hermes）",
            "保持与 Agent 无关——这里不出现任何 Agent 专属代码",
        ),
        files=(
            ("discovery module", "src/cogos/discovery.py"),
            ("probes registry", "src/cogos/probes.py"),
            ("adapter protocol", "src/cogos/adapters/__init__.py"),
            ("Hermes adapter", "src/cogos/adapters/hermes/adapter.py"),
        ),
    ),
    Region(
        key="thalamus",
        color="#D97706",  # amber
        ax=440, ay=400,
        lx=90, ly=400,
        label_en="Bootstrap",
        label_zh="启动",
        brain_en="Thalamus",
        brain_zh="丘脑",
        summary_en=(
            "The sensory relay that turns a user command into a CognitiveOS "
            "run. The bootstrap pipeline wires discovery → adapter → "
            "harvest → normalize → wiki → dashboard in a single function."
        ),
        summary_zh=(
            "把用户命令变成一次 CognitiveOS 运行的感知中继。"
            "启动流水线把 发现→适配→收割→标准化→wiki→仪表盘 串成一次函数调用。"
        ),
        responsibilities_en=(
            "Run discover / harvest / normalize / wiki / dashboard in order",
            "Produce a JSON report for every run",
            "Re-render index.html automatically",
        ),
        responsibilities_zh=(
            "按顺序执行 发现/收割/标准化/wiki/仪表盘",
            "每次运行生成 JSON 报告",
            "自动重新渲染 index.html",
        ),
        files=(
            ("pipeline", "src/cogos/bootstrap.py"),
            ("CLI entry", "src/cogos/cli.py"),
            ("paths config", "src/cogos/paths.py"),
        ),
    ),
    Region(
        key="hippocampus",
        color="#16A34A",  # green
        ax=560, ay=520,
        lx=900, ly=440,
        label_en="Sources",
        label_zh="原始数据",
        brain_en="Hippocampus",
        brain_zh="海马体",
        summary_en=(
            "Where raw memories live. Every harvested file is copied "
            "verbatim into knowledge/sources/<agent>/ with its original "
            "layout preserved so it can always be traced back."
        ),
        summary_zh=(
            "原始记忆存放处。每个收割到的文件原样复制到 "
            "knowledge/sources/<agent>/，保留原始目录结构，永远可追溯。"
        ),
        responsibilities_en=(
            "Hold raw files copied from each agent",
            "Preserve the original directory layout",
            "Stay read-only after harvest (never mutate sources)",
            "Whitelist excludes caches, auth, sessions, logs",
        ),
        responsibilities_zh=(
            "保存从每个 Agent 复制来的原始文件",
            "保留原始目录结构",
            "收割后保持只读（绝不改动 sources）",
            "白名单排除缓存/认证/会话/日志",
        ),
        files=(
            ("root", "knowledge/"),
            ("sources root", "knowledge/sources/"),
            ("Hermes sources", "knowledge/sources/hermes/"),
        ),
    ),
    Region(
        key="cortex",
        color="#7C3AED",  # violet
        ax=640, ay=330,
        lx=900, ly=250,
        label_en="Knowledge",
        label_zh="知识",
        brain_en="Cortex",
        brain_zh="皮层",
        summary_en=(
            "The structured, queryable view on top of the raw sources. "
            "The normalizer turns sources/ into a cross-agent index; the "
            "wiki renderer turns that index into human-readable pages."
        ),
        summary_zh=(
            "原始数据之上的结构化可查询视图。"
            "标准化器把 sources/ 转成跨 Agent 索引；wiki 渲染器把索引转成可读页面。"
        ),
        responsibilities_en=(
            "Build a normalized cross-agent index",
            "Render Markdown wiki pages with YAML frontmatter",
            "Keep pages short — they're pointers, not summaries",
        ),
        responsibilities_zh=(
            "构建跨 Agent 的标准化索引",
            "渲染带 YAML frontmatter 的 Markdown wiki 页",
            "页面保持简短——它们是指针，不是摘要",
        ),
        files=(
            ("normalized index", "knowledge/normalized/index.json"),
            ("wiki root", "knowledge/wiki/"),
            ("agent pages", "knowledge/wiki/<agent>.md"),
        ),
    ),
    Region(
        key="reflection",
        color="#DB2777",  # pink
        ax=660, ay=540,
        lx=900, ly=560,
        label_en="Reflection",
        label_zh="反思",
        brain_en="Reflection Loop",
        brain_zh="反思回路",
        summary_en=(
            "Where CognitiveOS would learn from past tasks. v0.1 only "
            "defines the place; the actual sleep-cycle / re-consolidation "
            "loop is scheduled for v0.3 — see DEC-007 and ROADMAP.md."
        ),
        summary_zh=(
            "CognitiveOS 将从过往任务中学习的地方。v0.1 只定义了位置；"
            "真正的睡眠周期/记忆重固化回路计划在 v0.3——见 DEC-007 和 ROADMAP.md。"
        ),
        responsibilities_en=(
            "Track design decisions (currently: 7 in design-decisions.md)",
            "Reserve the post-task hook for future re-consolidation",
            "Stay auditable — no silent auto-mutation in v0.1",
        ),
        responsibilities_zh=(
            "记录设计决策（目前 design-decisions.md 中有 7 条）",
            "为未来的记忆重固化预留任务后钩子",
            "保持可审计——v0.1 不做任何静默自动变更",
        ),
        files=(
            ("design decisions", "docs/design-decisions.md"),
            ("roadmap", "ROADMAP.md"),
            ("kernel design", "core/kernel/DESIGN.md"),
        ),
    ),
    Region(
        key="corpus",
        color="#0891B2",  # cyan
        ax=500, ay=430,
        lx=90, ly=560,
        label_en="Protocol",
        label_zh="协议",
        brain_en="Corpus Callosum",
        brain_zh="胼胝体",
        summary_en=(
            "The bridge that makes sure every agent speaks the same "
            "language. Adapters expose a uniform describe / harvest / "
            "bootstrap_query surface; new agents plug in without touching "
            "any other region."
        ),
        summary_zh=(
            "确保每个 Agent 说同一种语言的桥梁。"
            "适配器暴露统一的 describe / harvest / bootstrap_query 接口；"
            "新增 Agent 无需触碰任何其他区域即可接入。"
        ),
        responsibilities_en=(
            "Define AgentHandle and Adapter protocol",
            "Map agent_id → adapter implementation",
            "Keep the cross-agent knowledge model honest",
        ),
        responsibilities_zh=(
            "定义 AgentHandle 与 Adapter 协议",
            "把 agent_id 映射到适配器实现",
            "保持跨 Agent 知识模型的诚实性",
        ),
        files=(
            ("protocol design", "core/protocol/README.md"),
            ("adapter loader", "src/cogos/adapters/__init__.py"),
        ),
    ),
    Region(
        key="brainstem",
        color="#64748B",  # slate
        ax=490, ay=700,
        lx=490, ly=820,
        label_en="Runtime",
        label_zh="运行时",
        brain_en="Brainstem",
        brain_zh="脑干",
        summary_en=(
            "The boring but essential infrastructure: how you install "
            "CognitiveOS, where its files live, and how you invoke it."
        ),
        summary_zh=(
            "无聊但必不可少的基础设施：如何安装 CognitiveOS、文件放在哪里、如何调用它。"
        ),
        responsibilities_en=(
            "Provide the `cogos` command via pyproject.toml",
            "Keep the directory layout in one place (paths.py)",
            "Stay single-process in v0.1 (DEC-007)",
        ),
        responsibilities_zh=(
            "通过 pyproject.toml 提供 cogos 命令",
            "在单一位置维护目录布局（paths.py）",
            "v0.1 保持单进程（DEC-007）",
        ),
        files=(
            ("package config", "pyproject.toml"),
            ("path layout", "src/cogos/paths.py"),
            ("CLI", "src/cogos/cli.py"),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_dashboard(paths: Paths) -> Path:
    """Render the root ``index.html``; return its on-disk path."""
    paths.root.mkdir(parents=True, exist_ok=True)

    normalized_index = paths.normalized / "index.json"
    agents: list[dict] = []
    if normalized_index.exists():
        try:
            data = json.loads(normalized_index.read_text(encoding="utf-8"))
            agents = data.get("agents", [])
        except json.JSONDecodeError:
            agents = []

    wiki_pages = sorted(p.name for p in paths.wiki.glob("*.md")) if paths.wiki.exists() else []
    total_files = sum(a.get("file_count", 0) for a in agents)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    html = template.render(
        regions=REGIONS,
        regions_json=_regions_json(REGIONS),
        agents=agents,
        wiki_pages=wiki_pages,
        total_files=total_files,
        knowledge_root=str(paths.knowledge),
        dashboard_generated_at=_now_iso(),
    )

    out = paths.dashboard_index
    out.write_text(html, encoding="utf-8")
    return out


def _regions_json(regions: tuple[Region, ...]) -> str:
    """Serialise regions (with both languages) for inlining into the HTML."""
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
            "summary_en": r.summary_en,
            "summary_zh": r.summary_zh,
            "responsibilities_en": list(r.responsibilities_en),
            "responsibilities_zh": list(r.responsibilities_zh),
            "files": [list(pair) for pair in r.files],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")