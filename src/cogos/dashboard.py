"""HTML Dashboard.

A single self-contained ``index.html`` that summarises the current state
of the cognitive knowledge base. Generated from Jinja2 templates in this
directory; no external CSS/JS framework is loaded so the dashboard
works offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .paths import Paths


TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_dashboard(paths: Paths) -> Path:
    """Render ``dashboard/index.html``; return its on-disk path."""
    paths.dashboard.mkdir(parents=True, exist_ok=True)

    normalized_index = paths.normalized / "index.json"
    agents: list[dict] = []
    if normalized_index.exists():
        try:
            data = json.loads(normalized_index.read_text(encoding="utf-8"))
            agents = data.get("agents", [])
        except json.JSONDecodeError:
            agents = []

    wiki_pages = sorted(p.name for p in paths.wiki.glob("*.md")) if paths.wiki.exists() else []

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")

    html = template.render(
        agents=agents,
        wiki_pages=wiki_pages,
        knowledge_root=str(paths.knowledge),
        dashboard_generated_at=_now_iso(),
    )

    out = paths.dashboard_index
    out.write_text(html, encoding="utf-8")
    return out


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")