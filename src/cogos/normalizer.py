"""Normalizer.

Turns the per-agent raw harvests under ``knowledge/sources/`` into a
single, agent-agnostic index under ``knowledge/normalized/``.

For v0.1 the normalizer is intentionally lightweight: it lists what was
copied, where it came from, and lets the wiki layer pick it up. It does
not (yet) parse Markdown or extract memory entries — those belong in
later versions and depend on per-agent schemas that we don't have yet.
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import Paths


def build_normalized_index(paths: Paths) -> Path:
    """Write ``knowledge/normalized/index.json`` describing every source."""
    index_path = paths.normalized / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    sources_root = paths.sources
    entries: list[dict] = []
    if sources_root.exists():
        for agent_dir in sorted(p for p in sources_root.iterdir() if p.is_dir()):
            files = sorted(_walk_files(agent_dir))
            entries.append(
                {
                    "agent_id": agent_dir.name,
                    "file_count": len(files),
                    "files": [str(p.relative_to(sources_root)) for p in files],
                }
            )

    payload = {
        "version": 1,
        "agents": entries,
    }
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def _walk_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return out