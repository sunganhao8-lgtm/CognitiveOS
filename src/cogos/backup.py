"""Backup / restore — Phase 6.

`cogos export <target>`   — copy the ENTIRE canonical user/ layer + a
                           readable JSONL dump of executions/traces + meta.
`cogos import <source>`   — restore a user/ layer from an export into THIS
                           workspace (overwrite), then rebuild the index.

Export is fully READABLE (md/json/jsonl + README + meta.json) — never a
binary blob. Restore round-trip is tested end-to-end (memory/preferences/
rules/history identical after fresh-workspace import + reindex).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .paths import Paths
from .store import Store
from .user import UserLayer


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def export_user(paths: Paths, target: str | Path, *, include_index: bool = True) -> dict:
    """Export canonical user/ + readable trace dumps to target dir."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    user_dir = paths.root / "user"
    if not user_dir.exists():
        raise FileNotFoundError(f"no user/ layer at {user_dir}")

    # 1. canonical files (md/json/jsonl — already human-readable)
    for item in user_dir.rglob("*"):
        if item.is_file():
            rel = item.relative_to(user_dir)
            dest = target / "user" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    # 2. readable trace dumps (executions + events as JSONL)
    store = Store(paths.cache / "cognitive.db")
    try:
        execs = [dict(r) for r in store._conn.execute(
            "SELECT * FROM executions ORDER BY started_at")]
        events = [dict(r) for r in store._conn.execute(
            "SELECT * FROM trace_events ORDER BY id")]
        verifs = [dict(r) for r in store._conn.execute(
            "SELECT * FROM verifications ORDER BY id")]
        vectors_n = store._conn.execute("SELECT COUNT(*) FROM mem_vectors").fetchone()[0]
        stats = store.vector_stats()
    finally:
        store.close()

    trace_dir = target / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "executions.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in execs) + "\n",
        encoding="utf-8")
    (trace_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")
    (trace_dir / "verifications.jsonl").write_text(
        "\n".join(json.dumps(v, ensure_ascii=False) for v in verifs) + "\n",
        encoding="utf-8")

    # 3. meta + README
    meta = {
        "format": "cogos-export",
        "version": 1,
        "exported_at": _now(),
        "schema_version": stats["schema_version"],
        "user_files": len(execs) + len(events) + len(verifs) or None,
        "stats": {
            "executions": len(execs),
            "trace_events": len(events),
            "verifications": len(verifs),
            "embedding_vectors": vectors_n,
            "embedding_model": stats["embedding_model"],
        },
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if include_index:
        (target / "README.md").write_text(
            "# CognitiveOS Export\n\n"
            "可读备份，非二进制：\n\n"
            "- `user/` — 全部 canonical 认知数据（md / json / jsonl）\n"
            "- `traces/executions.jsonl` — 执行历史\n"
            "- `traces/events.jsonl` — trace 事件\n"
            "- `traces/verifications.jsonl` — 验证记录\n"
            "- `meta.json` — 导出元信息（schema 版本 / 统计）\n\n"
            "恢复：`cogos import <此目录>`\n",
            encoding="utf-8")
    return meta


def import_user(paths: Paths, source: str | Path) -> dict:
    """Restore a user/ layer from an export into THIS workspace.

    Overwrites the current user/ with the exported one, then rebuilds the
    Cognitive Store index so retrieval works immediately.
    """
    source = Path(source)
    src_user = source / "user"
    if not src_user.exists():
        raise FileNotFoundError(f"no user/ inside export at {source}")

    # overwrite user/ (canonical = source of truth from the export)
    user_dir = paths.root / "user"
    if user_dir.exists():
        shutil.rmtree(user_dir)
    shutil.copytree(src_user, user_dir)

    # rebuild the derived index
    user = UserLayer(root=paths.root / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    try:
        report = store.reindex(paths)
    finally:
        store.close()
    return {
        "imported_from": str(source),
        "reindex": {
            "entities": report.entities,
            "executions": report.executions,
        },
    }
