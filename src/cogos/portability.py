"""Portable export / import of the user layer.

These commands exist because the user layer must travel across machines
and across agent products. They are deliberately the simplest possible
implementation: a tar archive, nothing fancy.

The tar includes a ``manifest.json`` with the archive timestamp, the
source path, and a SHA-256 of every file. ``import`` verifies the
manifest before writing — so a corrupted or tampered archive is
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
    """Pack ``user/`` into a tar.gz at ``dest``. Returns a manifest dict."""
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
    """Restore ``user/`` from ``archive``. Verifies manifest, refuses on mismatch."""
    if not archive.exists():
        raise FileNotFoundError(archive)

    with tarfile.open(archive, mode="r:gz") as tf:
        names = tf.getnames()
        if "manifest.json" not in names:
            raise ValueError("archive missing manifest.json — refusing to import")
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
                raise ValueError(f"archive contains non-user path: {member.name}")
            data = tf.extractfile(member).read()  # type: ignore[union-attr]
            sha = hashlib.sha256(data).hexdigest()
            if expected.get(member.name) != sha:
                raise ValueError(f"sha256 mismatch for {member.name}")
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