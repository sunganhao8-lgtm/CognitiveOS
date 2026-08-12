"""标准化器。

把 ``knowledge/来源们/`` 下每个 Agent 的原始收割转成
``knowledge/normalized/`` 里统一的、与 Agent 无关的索引。

v0.1 阶段标准化器故意做得很轻：只列出被拷过来的文件、来自哪，
让 wiki 层去接。不（还）解析 Markdown、不抽取记忆条目——这
些留给以后版本，依赖我们尚不掌握的各 Agent schema。
"""

from __future__ import annotations

import json
from pathlib import Path

from .paths import Paths


def build_normalized_index(paths: Paths) -> Path:
    """写 ``knowledge/normalized/index.json`` 描述每个数据源。"""
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