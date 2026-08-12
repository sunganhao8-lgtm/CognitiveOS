"""Shared multi-agent workspace: layout, locks, and activity scan.

P0 of docs/shared-workspace-design.md: every agent works inside one shared
root directory while CognitiveOS keeps runtime state under ``<root>/.cogos/``::

    <root>/.cogos/
    ├── tasks/        task registry (one JSON file per task)
    ├── locks/        file locks (acquire / release / status)
    └── messages/     cross-agent mailbox (TO_<agent_id>/)

This module owns the ``Workspace`` layout plus the ``workspace`` and ``lock``
command groups. The task registry and the mailbox live in ``tasks.py`` and
``inbox.py`` respectively.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_WORKSPACE_ROOT = Path("D:/GitHub_Project/SharedWorkspace")
"""Default shared root when neither ``--root`` nor ``$COGOS_WORKSPACE`` is given."""

ENV_ROOT = "COGOS_WORKSPACE"
ENV_AGENT = "COGOS_AGENT"

LOCK_SUFFIX = ".lock"


class LockError(Exception):
    """Raised when a lock cannot be released or inspected."""


class LockConflict(LockError):
    """Raised when a lock is already held by another agent."""


@dataclass(frozen=True)
class Workspace:
    """A shared workspace root and its ``.cogos`` runtime directories."""

    root: Path

    @property
    def cogos_dir(self) -> Path:
        return self.root / ".cogos"

    @property
    def tasks_dir(self) -> Path:
        return self.cogos_dir / "tasks"

    @property
    def locks_dir(self) -> Path:
        return self.cogos_dir / "locks"

    @property
    def messages_dir(self) -> Path:
        return self.cogos_dir / "messages"

    def ensure(self) -> None:
        """Create every directory CognitiveOS writes to."""
        for d in (self.cogos_dir, self.tasks_dir, self.locks_dir, self.messages_dir):
            d.mkdir(parents=True, exist_ok=True)

    def resolve_target(self, rel: str) -> Path:
        """Normalize a workspace-relative path and make sure it stays inside the root.

        Rejects absolute paths, drive letters and ``..`` traversal so an agent
        can never lock or reference a file outside the shared workspace.
        """
        if (
            not rel
            or rel.startswith(("/", "\\"))
            or ":" in rel
            or Path(rel).is_absolute()
        ):
            raise ValueError(f"无效的工作区相对路径：{rel!r}")
        parts = [p for p in rel.replace("\\", "/").split("/") if p]
        if not parts or any(p in (".", "..") for p in parts):
            raise ValueError(f"invalid workspace-relative path: {rel!r}")
        return self.root.joinpath(*parts)


def resolve_root(root: Path | None) -> Path:
    """Pick the shared workspace root: ``--root`` flag, then ``$COGOS_WORKSPACE``,
    then the default location."""
    if root is not None:
        return Path(root).resolve()
    env_root = os.environ.get(ENV_ROOT)
    if env_root:
        return Path(env_root).resolve()
    return DEFAULT_WORKSPACE_ROOT.resolve()


def default_agent() -> str:
    """The agent id used when the caller does not say who they are."""
    return os.environ.get(ENV_AGENT) or "cogos"


def now_iso(now: datetime | None = None) -> str:
    """UTC ISO-8601 timestamp, seconds precision (injectable for tests)."""
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically (tmp file + ``os.replace``).

    Concurrent readers never see a half-written file, and ``os.replace`` is
    safe on Windows even when the destination already exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def init_workspace(ws: Workspace) -> dict[str, Any]:
    """Create the ``.cogos`` skeleton and report what exists."""
    ws.ensure()
    return {
        "root": str(ws.root),
        "dirs": [str(ws.cogos_dir), str(ws.tasks_dir), str(ws.locks_dir), str(ws.messages_dir)],
    }


# --- file locks -------------------------------------------------------------


def lock_file_for(ws: Workspace, rel: str) -> Path:
    """Map a workspace-relative file path to its lock file under ``.cogos/locks/``.

    ``repo1/src/index.html`` -> ``.cogos/locks/repo1/src/index.html.lock``
    """
    target = ws.resolve_target(rel)
    parts = target.relative_to(ws.root).parts
    return ws.locks_dir.joinpath(*parts[:-1], parts[-1] + LOCK_SUFFIX)


def acquire_lock(
    ws: Workspace,
    rel: str,
    holder: str | None = None,
    note: str | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Take an exclusive lock on a workspace-relative file.

    Raises :class:`LockConflict` when the lock is already held (unless
    ``force`` is set, which breaks the existing lock first).
    """
    ws.ensure()
    holder = holder or default_agent()
    lp = lock_file_for(ws, rel)
    if lp.exists() and not force:
        try:
            existing = json.loads(lp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        raise LockConflict(
            f"lock on {rel!r} already held by {existing.get('holder', '?')} "
            f"since {existing.get('acquired_at', '?')} (use --force to break)"
        )
    lp.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target": rel,
        "holder": holder,
        "note": note or "",
        "acquired_at": now_iso(now),
    }
    atomic_write_json(lp, payload)
    return payload


def release_lock(
    ws: Workspace,
    rel: str,
    holder: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Release a lock previously taken with :func:`acquire_lock`.

    Only the holder may release, unless ``force`` is set.
    """
    holder = holder or default_agent()
    lp = lock_file_for(ws, rel)
    if not lp.exists():
        raise LockError(f"{rel!r} 上没有锁")
    if not force:
        try:
            existing = json.loads(lp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if existing.get("holder") != holder:
            raise LockError(
                f"lock on {rel!r} is held by {existing.get('holder', '?')}, not {holder}"
            )
    lp.unlink()
    return {"target": rel, "holder": holder, "released": True}


def list_locks(ws: Workspace) -> list[dict[str, Any]]:
    """List every lock currently held in the workspace."""
    out: list[dict[str, Any]] = []
    if not ws.locks_dir.exists():
        return out
    for lp in sorted(ws.locks_dir.rglob(f"*{LOCK_SUFFIX}")):
        try:
            data = json.loads(lp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        data["target"] = data.get("target", str(lp.relative_to(ws.locks_dir))[:-len(LOCK_SUFFIX)])
        data["lock_file"] = str(lp.relative_to(ws.cogos_dir))
        out.append(data)
    return out


# --- activity scan (P1, simple implementation) ------------------------------


def _git(repo: Path, *args: str) -> str | None:
    """Run a git command inside a repo; return stdout or None on any failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _scan_repo(repo: Path, since_hours: int) -> dict[str, Any]:
    """Infer one repo's recent activity: branch, last commit, dirty files and
    files touched within the window (zero-invasion: reads git + mtimes only)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    recent: list[tuple[float, str]] = []
    for p in repo.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        except OSError:
            continue
        if mtime >= cutoff:
            recent.append((p.stat().st_mtime, str(p.relative_to(repo)).replace("\\", "/")))
    recent.sort(reverse=True)
    porcelain = _git(repo, "status", "--porcelain")
    return {
        "repo": repo.name,
        "path": str(repo),
        "branch": _git(repo, "branch", "--show-current"),
        "last_commit": _git(repo, "log", "-1", "--format=%cI"),
        "dirty_files": len(porcelain.splitlines()) if porcelain else 0,
        "recent_files": [f for _, f in recent[:50]],
    }


def scan_workspace(ws: Workspace, since_hours: int = 24) -> dict[str, Any]:
    """Scan every git repository directly under the workspace root."""
    repos: list[dict[str, Any]] = []
    if ws.root.exists():
        for child in sorted(ws.root.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / ".git").exists():
                repos.append(_scan_repo(child, since_hours))
    return {"since_hours": since_hours, "repos": repos}


# --- CLI: cogos workspace ---------------------------------------------------


def _add_io(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--root", dest="ws_root", type=Path, default=None,
        help="Shared workspace root (default: $COGOS_WORKSPACE or D:/GitHub_Project/SharedWorkspace)",
    )
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")


def add_workspace_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("workspace", help="Manage the shared multi-agent workspace")
    ws_sub = p.add_subparsers(dest="workspace_cmd", required=True)

    p_init = ws_sub.add_parser("init", help="Create the .cogos skeleton (tasks/, locks/, messages/)")
    _add_io(p_init)

    p_scan = ws_sub.add_parser("scan", help="Infer agent activity from git + file mtimes (P1, simple)")
    p_scan.add_argument("--hours", type=int, default=24, help="Activity window in hours (default: 24)")
    _add_io(p_scan)


def run_workspace(args: argparse.Namespace) -> int:
    ws = Workspace(root=resolve_root(args.ws_root))
    if args.workspace_cmd == "init":
        payload = init_workspace(ws)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"已初始化共享工作区：{payload['root']}")
            for d in payload["dirs"]:
                print(f"  {d}")
        return 0

    if args.workspace_cmd == "scan":
        payload = scan_workspace(ws, since_hours=args.hours)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        print(f"正在扫描 {ws.root}（{payload['since_hours']} 小时内的活动）...")
        if not payload["repos"]:
            print("（工作区根目录下未发现 git 仓库）")
            return 0
        for r in payload["repos"]:
            bits = [r["repo"]]
            if r["branch"]:
                bits.append(f"branch={r['branch']}")
            if r["last_commit"]:
                bits.append(f"last_commit={r['last_commit']}")
            bits.append(f"dirty={r['dirty_files']}")
            bits.append(f"recent_files={len(r['recent_files'])}")
            print("  ".join(bits))
            for f in r["recent_files"][:10]:
                print(f"    {f}")
        return 0

    return 2


# --- CLI: cogos lock --------------------------------------------------------


def add_lock_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("lock", help="Acquire / release file locks in the shared workspace")
    lock_sub = p.add_subparsers(dest="lock_cmd", required=True)

    p_acq = lock_sub.add_parser("acquire", help="Take an exclusive lock on a workspace-relative file")
    p_acq.add_argument("target", help="Workspace-relative file path, e.g. repo1/src/index.html")
    p_acq.add_argument("--holder", default=None, help="Agent id (default: $COGOS_AGENT or 'cogos')")
    p_acq.add_argument("--note", default=None, help="Optional note stored in the lock")
    p_acq.add_argument("--force", action="store_true", help="Break an existing lock and take it")
    p_acq.add_argument("--notify", default=None, metavar="AGENT",
                       help="On conflict, send a lock_conflict message to this agent's inbox")
    _add_io(p_acq)

    p_rel = lock_sub.add_parser("release", help="Release a lock (only the holder may, unless --force)")
    p_rel.add_argument("target", help="Workspace-relative file path")
    p_rel.add_argument("--holder", default=None, help="Agent id")
    p_rel.add_argument("--force", action="store_true", help="Release even if held by another agent")
    _add_io(p_rel)

    p_st = lock_sub.add_parser("status", help="List all held locks")
    _add_io(p_st)


def run_lock(args: argparse.Namespace) -> int:
    ws = Workspace(root=resolve_root(args.ws_root))

    if args.lock_cmd == "acquire":
        try:
            payload = acquire_lock(
                ws, args.target, holder=args.holder, note=args.note, force=args.force,
            )
        except LockConflict as e:
            if args.notify:
                from .inbox import send_message  # local import: avoid cycle at import time

                try:
                    send_message(
                        ws, to=args.notify, from_=args.holder,
                        type="lock_conflict", task_id="",
                        content=f"LOCK_CONFLICT on {args.target}: {e}",
                    )
                except Exception:
                    pass
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"已锁定 {payload['target']}（持有者：{payload['holder']}，时间：{payload['acquired_at']}）")
        return 0

    if args.lock_cmd == "release":
        try:
            payload = release_lock(ws, args.target, holder=args.holder, force=args.force)
        except LockError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"已释放 {payload['target']} 的锁")
        return 0

    if args.lock_cmd == "status":
        payload = list_locks(ws)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif not payload:
            print("(no locks held)")
        else:
            for lock in payload:
                print(f"{lock['target']}  由 {lock.get('holder', '?')} 持有，自 {lock.get('acquired_at', '?')} 起")
        return 0

    return 2
