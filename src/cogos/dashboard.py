"""HTML Dashboard.

A single self-contained ``index.html`` that doubles as the CognitiveOS
cognitive map: a clickable brain diagram where every "region" maps to a
real subsystem of the project. Clicking a region opens a panel that lists
the region's responsibility, the files that implement it, and a short
prose summary.

The diagram is hand-drawn in SVG so it works fully offline and remains
editable by an AI agent.
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
class Region:
    """One clickable region of the cognitive map."""

    key: str
    label: str
    brain_name: str
    color: str
    summary: str
    responsibilities: tuple[str, ...]
    files: tuple[tuple[str, str], ...]  # (label, relative-path-from-root)


# SVG layout coordinates (viewBox 0 0 800 600) — drawn so that the brain
# silhouette is recognisable and regions don't overlap.
REGIONS: tuple[Region, ...] = (
    Region(
        key="prefrontal",
        label="Router",
        brain_name="Prefrontal Cortex",
        color="#6aa9ff",
        summary=(
            "Decides *what* should run when a task arrives. The discovery "
            "layer scans this machine for installed agents; the adapter "
            "layer gives every agent a uniform interface."
        ),
        responsibilities=(
            "Scan the local machine for AI agents",
            "Pick a Bootstrap Agent on first run",
            "Provide one Adapter per agent (Hermes today)",
            "Stay agent-agnostic — no agent-specific code lives here",
        ),
        files=(
            ("discovery module", "src/cogos/discovery.py"),
            ("probes registry", "src/cogos/probes.py"),
            ("adapter protocol", "src/cogos/adapters/__init__.py"),
            ("Hermes adapter", "src/cogos/adapters/hermes/adapter.py"),
        ),
    ),
    Region(
        key="hippocampus",
        label="Sources",
        brain_name="Hippocampus",
        color="#4ade80",
        summary=(
            "Where raw memories live. Every harvested file is copied "
            "verbatim into knowledge/sources/<agent>/ with its original "
            "layout preserved so it can always be traced back."
        ),
        responsibilities=(
            "Hold raw files copied from each agent",
            "Preserve the original directory layout",
            "Stay read-only after harvest (never mutate sources)",
            "Whitelist excludes caches, auth, sessions, logs",
        ),
        files=(
            ("root", "knowledge/"),
            ("sources root", "knowledge/sources/"),
            ("Hermes sources", "knowledge/sources/hermes/"),
        ),
    ),
    Region(
        key="cortex",
        label="Knowledge",
        brain_name="Cortex",
        color="#b78cff",
        summary=(
            "The structured, queryable view on top of the raw sources. "
            "The normalizer turns sources/ into a cross-agent index; the "
            "wiki renderer turns that index into human-readable pages."
        ),
        responsibilities=(
            "Build a normalized cross-agent index",
            "Render Markdown wiki pages with YAML frontmatter",
            "Keep pages short — they're pointers, not summaries",
        ),
        files=(
            ("normalized index", "knowledge/normalized/index.json"),
            ("wiki root", "knowledge/wiki/"),
            ("agent pages", "knowledge/wiki/<agent>.md"),
        ),
    ),
    Region(
        key="thalamus",
        label="Bootstrap",
        brain_name="Thalamus",
        color="#fbbf24",
        summary=(
            "The sensory relay that turns a user command into a CognitiveOS "
            "run. The bootstrap pipeline wires discovery → adapter → "
            "harvest → normalize → wiki → dashboard in a single function."
        ),
        responsibilities=(
            "Run discover / harvest / normalize / wiki / dashboard in order",
            "Produce a JSON report for every run",
            "Re-render index.html automatically",
        ),
        files=(
            ("pipeline", "src/cogos/bootstrap.py"),
            ("CLI entry", "src/cogos/cli.py"),
            ("paths config", "src/cogos/paths.py"),
        ),
    ),
    Region(
        key="reflection",
        label="Reflection",
        brain_name="Reflection Loop",
        color="#f472b6",
        summary=(
            "Where CognitiveOS would learn from past tasks. v0.1 only "
            "defines the place; the actual sleep-cycle / re-consolidation "
            "loop is scheduled for v0.3 — see DEC-007 and ROADMAP.md."
        ),
        responsibilities=(
            "Track design decisions (currently: 7 in design-decisions.md)",
            "Reserve the post-task hook for future re-consolidation",
            "Stay auditable — no silent auto-mutation in v0.1",
        ),
        files=(
            ("design decisions", "docs/design-decisions.md"),
            ("roadmap", "ROADMAP.md"),
            ("kernel design", "core/kernel/DESIGN.md"),
        ),
    ),
    Region(
        key="corpus",
        label="Protocol",
        brain_name="Corpus Callosum",
        color="#22d3ee",
        summary=(
            "The bridge that makes sure every agent speaks the same "
            "language. Adapters expose a uniform describe / harvest / "
            "bootstrap_query surface; new agents plug in without touching "
            "any other region."
        ),
        responsibilities=(
            "Define AgentHandle and Adapter protocol",
            "Map agent_id → adapter implementation",
            "Keep the cross-agent knowledge model honest",
        ),
        files=(
            ("protocol design", "core/protocol/README.md"),
            ("adapter loader", "src/cogos/adapters/__init__.py"),
        ),
    ),
    Region(
        key="brainstem",
        label="Runtime",
        brain_name="Brainstem",
        color="#94a3b8",
        summary=(
            "The boring but essential infrastructure: how you install "
            "CognitiveOS, where its files live, and how you invoke it."
        ),
        responsibilities=(
            "Provide the `cogos` command via pyproject.toml",
            "Keep the directory layout in one place (paths.py)",
            "Stay single-process in v0.1 (DEC-007)",
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
    """Serialise the brain regions for inlining into the HTML <script>."""
    import json

    payload = [
        {
            "key": r.key,
            "label": r.label,
            "brain_name": r.brain_name,
            "color": r.color,
            "summary": r.summary,
            "responsibilities": list(r.responsibilities),
            "files": [list(pair) for pair in r.files],
        }
        for r in regions
    ]
    return json.dumps(payload, ensure_ascii=False)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")