"""Portable export / import 的 用户 layer.

These commands exist because 用户 layer 必须 travel across machines
和 across Agent products. They 是 deliberately 该 simplest possible
implementation: a tar archive, nothing fancy.

该 tar includes a ``manifest.json`` 使用 该 archive timestamp, 该
来源 路径, 和 a SHA-256 的 每个 文件. ``import`` 验证
manifest before writing — so a corrupted 或 tampered archive 是
refused.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


def export_user(user: UserLayer, dest: Path) -> dict:
    """Pack ``user/`` into a tar.gz 在 ``dest``. 返回 a manifest dict."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict] = []
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for path in sorted(user.root.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(user.root.parent).as_posix()  # include the "user/" prefix
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            manifest_files.append({"path": arcname, "sha256": sha, "size": len(data)})
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            tf.addfile(info, io.BytesIO(data))

        manifest = {
            "format_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_root": str(user.root),
            "files": manifest_files,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tf.addfile(info, io.BytesIO(manifest_bytes))

    dest.write_bytes(buf.getvalue())
    return {**manifest, "archive": str(dest), "archive_bytes": dest.stat().st_size}


def import_user(user: UserLayer, archive: Path) -> dict:
    """Restore ``user/`` 来自 ``archive``. 验证 manifest, refuses 在 mismatch."""
    if not archive.exists():
        raise FileNotFoundError(archive)

    with tarfile.open(archive, mode="r:gz") as tf:
        names = tf.getnames()
        if "manifest.json" not in names:
            raise ValueError("归档缺少 manifest.json —— 拒绝导入")
        manifest_member = tf.extractfile("manifest.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read().decode("utf-8"))
        expected = {f["path"]: f["sha256"] for f in manifest["files"]}

        user.root.parent.mkdir(parents=True, exist_ok=True)
        restored = 0
        for member in tf.getmembers():
            if member.isdir() or member.name == "manifest.json":
                continue
            if not member.name.startswith("user/"):
                raise ValueError(f"归档包含非 user/ 路径：{member.name}")
            data = tf.extractfile(member).read()  # type: ignore[union-attr]
            sha = hashlib.sha256(data).hexdigest()
            if expected.get(member.name) != sha:
                raise ValueError(f"{member.name} 的 sha256 校验不一致")
            target = user.root.parent / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            restored += 1

    return {
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files_restored": restored,
        "manifest_files": len(manifest["files"]),
        "source_root": manifest.get("source_root"),
    }