"""Bootstrap pipeline.

``bootstrap`` is the *only* orchestration CognitiveOS needs in v0.1.
It runs four steps, in order, and prints a status panel at the end:

1. **Discover** installed agents on this machine.
2. **Pick** the first available adapter as the Bootstrap Agent.
3. **Harvest** the Bootstrap Agent's raw data into ``knowledge/sources/``.
4. **Normalize & summarise** that data into a wiki page.

The dashboard renderer is invoked at the end of this pipeline so the
HTML always reflects the freshly produced knowledge base.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import load_adapter
from .discovery import discover as discover_agents
from .paths import Paths
from .normalizer import build_normalized_index
from .wiki import build_wiki
from .dashboard import render_dashboard


@dataclass
class BootstrapReport:
    started_at: str
    finished_at: str
    root: str
    discovered: list[dict[str, Any]]
    bootstrap_agent: str | None
    harvested_files: int
    wiki_pages: int
    dashboard: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run(paths: Paths | None = None, *, open_browser: bool = True) -> BootstrapReport:
    """Execute the full bootstrap pipeline and return a report."""
    paths = paths or Paths.default()
    paths.ensure()

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    handles = discover_agents(paths)
    discovered = [h.to_dict() for h in handles]

    bootstrap_agent: str | None = None
    harvested_files = 0
    harvest_notes: list[str] = []

    for handle in handles:
        adapter = load_adapter(handle)
        if adapter is None:
            harvest_notes.append(f"{handle.agent_id}: no adapter available")
            continue

        if bootstrap_agent is None:
            bootstrap_agent = adapter.agent_id

        result = adapter.harvest(paths.sources)
        harvested_files += result.copied_files
        harvest_notes.extend(result.notes)

    # Normalized + wiki are derived views, always recomputed.
    build_normalized_index(paths)
    wiki_pages = build_wiki(paths)

    dashboard_path = render_dashboard(paths)

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")

    report = BootstrapReport(
        started_at=started,
        finished_at=finished,
        root=str(paths.root),
        discovered=discovered,
        bootstrap_agent=bootstrap_agent,
        harvested_files=harvested_files,
        wiki_pages=wiki_pages,
        dashboard=str(dashboard_path),
    )

    # Persist the report next to the wiki so the dashboard can show "last run".
    (paths.cache / "last_report.json").write_text(
        _json_dumps(report.to_dict()), encoding="utf-8"
    )

    if open_browser and dashboard_path.exists():
        _open_in_browser(dashboard_path)

    return report


def _open_in_browser(path: Path) -> None:
    import os
    import sys
    import webbrowser

    url = path.resolve().as_uri()
    try:
        webbrowser.open(url)
    except Exception:
        # On headless servers we just print the URL.
        print(f"Dashboard: {url}", file=sys.stderr)


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)