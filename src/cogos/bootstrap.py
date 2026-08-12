"""引导流程。

``bootstrap`` 是 CognitiveOS 在 v0.1 阶段唯一需要的编排流程。
它按顺序跑四步，最后打印状态面板：

1. **发现**本机已安装的 Agent。
2. **挑选**第一个可用的 adapter 作为 Bootstrap Agent。
3. **收割**Bootstrap Agent 的原始数据到 ``knowledge/sources/``。
4. **标准化并汇总**为 wiki 页面。

仪表盘渲染器会在流程末尾被调用，确保 HTML 永远反映最新的知识库。
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
from .user import UserLayer
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
    """执行完整的引导流程并返回报告。"""
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

    # Normalized + wiki 都是派生视图，每次都重新计算。
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

    # 把报告写一份在 wiki 旁边，方便 dashboard 显示 "上次运行"。
    (paths.cache / "last_report.json").write_text(
        _json_dumps(report.to_dict()), encoding="utf-8"
    )

    # 首次 bootstrap 时保证主人层骨架存在。我们不会自动往里塞数据——
    # ``user/`` 下的每个文件都由主人（或显式的 cogos 命令）写，
    # 永远不会被静默覆盖。
    user = UserLayer(root=paths.root / "user")
    user.ensure()
    _ensure_user_readme(user)

    if open_browser and dashboard_path.exists():
        _open_in_browser(dashboard_path)

    return report


def _ensure_user_readme(user: UserLayer) -> None:
    readme = user.root / "README.md"
    if readme.exists():
        return
    readme.write_text(
        (
            "# user/\n\n"
            "This directory is **yours**. CognitiveOS never silently\n"
            "writes here. You author files directly with a text editor.\n\n"
            "It is the layer that travels with you — across machines and\n"
            "across AI agent products. Copy this directory to another\n"
            "computer (or `cogos export user/`) and your preferences,\n"
            "project knowledge, and accumulated experience come with you.\n\n"
            "See `preferences.md`, `style.md`, `projects/`, `experience/`,\n"
            "and `cognitive/`.\n"
        ),
        encoding="utf-8",
    )


def _open_in_browser(path: Path) -> None:
    import os
    import sys
    import webbrowser

    url = path.resolve().as_uri()
    try:
        webbrowser.open(url)
    except Exception:
        # 在无 GUI 的服务器上只打印 URL。
        print(f"Dashboard: {url}", file=sys.stderr)


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)