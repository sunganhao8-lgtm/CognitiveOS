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
    # How this region participates in the overall cognitive flow
    role_en: str  # e.g. "First to receive input"
    role_zh: str
    # The principles the master cares about most, in this region.
    memory: tuple[MemoryItem, ...]


# Brain viewBox 960x960; anchors are eyeballed against the artwork.
# Each MemoryItem's `path` is a clickable link inside the dashboard —
# clicking the principle jumps to the actual file in the repo.
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
        role_en="Decides which agent to call and orchestrates the flow",
        role_zh="决定调用哪个 Agent，编排整体流程",
        memory=(),
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
        role_en="First to receive the master's input; routes it inward",
        role_zh="第一个接收到主人输入的脑区，向内路由",
        memory=(),
    ),
    Region(
        key="hippocampus",
        color="#16A34A",
        ax=560, ay=520,
        lx=870, ly=440,
        label_en="Sources",
        label_zh="原始数据",
        brain_en="Hippocampus",
        brain_zh="海马体",
        desc_en="Long-term memory formation — raw data, original layout preserved.",
        desc_zh="长期记忆形成——原始数据，保留原始目录结构。",
        role_en="Stashes the raw record of what happened verbatim",
        role_zh="把发生过的事情原样留档",
        memory=(),
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
        role_en="Distills raw records into reusable knowledge",
        role_zh="把原始记录提炼成可复用知识",
        memory=(),
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
        role_en="Sleeps, re-runs probes, audits whether the Agent still obeys the rules",
        role_zh="睡眠、回放探针，校验 Agent 是否仍守规则",
        memory=(),
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
        role_en="Bridges cognition with the external Agent (Hermes/Codex/Claude)",
        role_zh="把认知系统与外部 Agent 桥接起来",
        memory=(),
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
        role_en="Keeps the runtime alive: install, paths, CLI",
        role_zh="维持运行时：安装、路径、命令行",
        memory=(),
    ),
)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


def render_dashboard(paths: Paths) -> Path:
    """Render the root ``index.html``; return its on-disk path."""
    paths.root.mkdir(parents=True, exist_ok=True)

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
            if not m:
                continue
            title, rel_path, note = m.group(1), m.group(2), m.group(3) or ""
            local_md = user_dir / rel_path
            link = f"./user/{rel_path}" if local_md.exists() else f"./user/projects/{rel_path}"
            projects.append({"title": title, "path": link, "note": note})

    # user/conversations/ holds past agent session exports (typically
    # synced from external tooling). They are NOT the user's own Q&A
    # history — dashboard must NOT display them as such. Read paths
    # intentionally skipped; see docs/privacy-remediation.md.
    qa_groups: list[dict] = []

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    # Phase 3F: ONE query pass builds the complete ViewModel; the template
    # only renders. No hardcoded cognition anywhere.
    from .dashboard_query import DashboardQuery

    query = DashboardQuery(paths)
    try:
        vm = query.build()
    finally:
        query.close()
    vm_dict = vm.to_dict()

    html = template.render(
            regions=REGIONS,
            regions_json=_regions_json_with_real_memory(
                REGIONS,
                {
                    r["key"]: [{"title_zh": t, "title_en": t, "path": "", "content": t}
                               for t in r.get("recent", [])[:6]]
                    for r in vm_dict["brain_regions"]
                    if r.get("recent")
                },
            ),
            projects=projects,
            qa_groups=qa_groups,
            qa_groups_json=json.dumps(qa_groups, ensure_ascii=False),
            vm=vm,
            vm_json=json.dumps(vm_dict, ensure_ascii=False),
            executions=vm_dict["recent_executions"],
            memory_counts={"confirmed": vm_dict["overview"]["learned"]},
            skill_count=len(vm_dict["brain_regions"]),
            master_name="主人",
            rules=[],
        )

    out = paths.dashboard_index
    out.write_text(html, encoding="utf-8")
    return out


def _load_store_snapshot(paths: Paths) -> dict:
    """Read real runtime data from the Cognitive Store.

    Never raises: a missing/corrupt index degrades to empty panels — the
    dashboard is a projection, not a fact source.
    """
    try:
        from .store import Store

        store = Store(paths.cache / "cognitive.db")
    except Exception:
        return {"executions": [], "region_memories": {}, "memory_counts": {}, "skills": 0}
    try:
        return {
            "executions": store.recent_executions(limit=6),
            "region_memories": store.memories_for_regions(),
            "memory_counts": store.memory_counts(),
            "skills": store.skill_count(),
        }
    except Exception:
        return {"executions": [], "region_memories": {}, "memory_counts": {}, "skills": 0}
    finally:
        try:
            store.close()
        except Exception:
            pass


def _regions_json_with_real_memory(regions: tuple[Region, ...], region_memories: dict[str, list[dict]]) -> str:
    """Brain-region JSON where the memory items are REAL store data.

    Region definitions (anatomy, labels, roles) stay as static legend —
    allowed by the data-truth principle. What the system "knows" per region
    comes from the Cognitive Store, mapped subtype → region:
    preference → prefrontal, rule → hippocampus, semantic → cortex,
    episodic → reflection.
    """
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
            "role_en": r.role_en,
            "role_zh": r.role_zh,
            "memory": [
                {
                    "title_en": m["content"][:90],
                    "title_zh": m["content"][:90],
                    "path": "",
                    "content": m["content"],
                }
                for m in region_memories.get(r.key, [])
            ],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


def _read_mem_content(rel_path: str) -> str:
    """Read a workspace-relative .md file so the dashboard can render it
    inline (no fetch — works over file://). Returns '' when missing."""
    if not rel_path:
        return ""
    p = Path(rel_path)
    if not p.exists():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    # cap at ~8KB so the HTML stays light; reader can open the real file
    return text[:8000]


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
            "role_en": r.role_en,
            "role_zh": r.role_zh,
            "memory": [
                {
                    "title_en": m.title_en,
                    "title_zh": m.title_zh,
                    "path": m.path,
                    "content": _read_mem_content(m.path),
                }
                for m in r.memory
            ],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)