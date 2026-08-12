"""任务 registry 用于 该 shared multi-Agent 工作区.

每个 任务 是 one JSON 文件 under ``<root>/.cogos/任务们/<id>.json`` (see
docs/shared-工作区-design.md). Agents report progress 使用
``cogos 任务 更新``; 任何 Agent 可以 ask "what 是 everyone doing" 使用
``cogos 任务 列出``. 所有 写入 是 atomic so concurrent 更新 从不
corrupt 一个任务 文件.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from .workspace import (
    Workspace,
    atomic_write_json,
    default_agent,
    now_iso,
    resolve_root,
)

STATUSES = ("pending", "in_progress", "review", "done")

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NUMERIC_ID_RE = re.compile(r"TASK-(\d+)")


class TaskError(Exception):
    """Base error 用于 任务 registry."""


class TaskNotFound(TaskError):
    """Raised 当 一个任务 id 做 不 exist."""


class TaskExists(TaskError):
    """Raised 当 创建中 一个任务 whose id 是 already taken."""


@dataclass
class Task:
    """A single 任务 在 该 shared registry."""

    id: str
    title: str
    assignee: str = ""
    status: str = "pending"
    progress: int = 0
    current_file: str = ""
    branch: str = ""
    pr_url: str = ""
    created_at: str = ""
    updated_at: str = ""
    history: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def task_file(ws: Workspace, task_id: str) -> Path:
    return ws.tasks_dir / f"{task_id}.json"


def _clamp_progress(progress: int) -> int:
    return max(0, min(100, int(progress)))


def next_task_id(ws: Workspace) -> str:
    """Auto-generate ``任务-001``, ``任务-002``, ... after 该 highest existing id."""
    highest = 0
    if ws.tasks_dir.exists():
        for p in ws.tasks_dir.glob("TASK-*.json"):
            m = _NUMERIC_ID_RE.fullmatch(p.stem)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"TASK-{highest + 1:03d}"


def _sort_key(t: Task) -> tuple[int, int | str]:
    m = _NUMERIC_ID_RE.fullmatch(t.id)
    return (0, int(m.group(1))) if m else (1, t.id)


def create_task(
    ws: Workspace,
    *,
    title: str,
    task_id: str | None = None,
    assignee: str | None = None,
    status: str = "pending",
    progress: int = 0,
    current_file: str | None = None,
    branch: str | None = None,
    pr_url: str | None = None,
    note: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> Task:
    """创建 一个任务 和 写入 it 到 该 registry. 抛出 TaskExists 在 id clash."""
    ws.ensure()
    actor = actor or default_agent()
    tid = task_id or next_task_id(ws)
    if not _TASK_ID_RE.fullmatch(tid):
        raise TaskError(f"无效的任务 id：{tid!r}（只能使用字母、数字、点、下划线、连字符）")
    if task_file(ws, tid).exists():
        raise TaskExists(f"任务 {tid} 已存在")
    if status not in STATUSES:
        raise TaskError(f"无效的状态 {status!r}；可选：{', '.join(STATUSES)}")
    ts = now_iso(now)
    history: list[dict[str, str]] = []
    if note:
        history.append({"t": ts, "msg": f"{actor}: {note}"})
    task = Task(
        id=tid,
        title=title,
        assignee=assignee or "",
        status=status,
        progress=_clamp_progress(progress),
        current_file=current_file or "",
        branch=branch or "",
        pr_url=pr_url or "",
        created_at=ts,
        updated_at=ts,
        history=history,
    )
    atomic_write_json(task_file(ws, tid), task.to_dict())
    return task


def update_task(
    ws: Workspace,
    task_id: str,
    *,
    title: str | None = None,
    assignee: str | None = None,
    status: str | None = None,
    progress: int | None = None,
    current_file: str | None = None,
    branch: str | None = None,
    pr_url: str | None = None,
    note: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> Task:
    """更新 任何 subset 的 一个任务's fields 和 append a history entry.

    每个 写入 goes through 该 registry 文件 使用 ``updated_at`` bumped, so
    任何 Agent 可以 see 在 a glance how fresh 该 state 是.
    """
    ws.ensure()
    task = show_task(ws, task_id)
    actor = actor or default_agent()
    ts = now_iso(now)
    changes: list[str] = []

    if title is not None and title != task.title:
        task.title = title
        changes.append("title")
    if assignee is not None and assignee != task.assignee:
        task.assignee = assignee
        changes.append("assignee")
    if status is not None:
        if status not in STATUSES:
            raise TaskError(f"invalid status {status!r}; choose from {', '.join(STATUSES)}")
        if status != task.status:
            task.status = status
            changes.append("status")
    if progress is not None:
        p = _clamp_progress(progress)
        if p != task.progress:
            task.progress = p
            changes.append("progress")
    if current_file is not None and current_file != task.current_file:
        task.current_file = current_file
        changes.append("current_file")
    if branch is not None and branch != task.branch:
        task.branch = branch
        changes.append("branch")
    if pr_url is not None and pr_url != task.pr_url:
        task.pr_url = pr_url
        changes.append("pr_url")

    msg = note or (f"updated: {', '.join(changes)}" if changes else "")
    if msg:
        task.history.append({"t": ts, "msg": f"{actor}: {msg}"})
    task.updated_at = ts
    atomic_write_json(task_file(ws, task_id), task.to_dict())
    return task


def list_tasks(ws: Workspace, status: str | None = None, assignee: str | None = None) -> list[Task]:
    """列出 所有 任务们, optionally filtered 通过 状态 / assignee, sorted 通过 id."""
    if not ws.tasks_dir.exists():
        return []
    out: list[Task] = []
    for p in sorted(ws.tasks_dir.glob("*.json")):
        try:
            task = Task.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue  # skip corrupt files rather than failing the whole list
        if status and task.status != status:
            continue
        if assignee and task.assignee != assignee:
            continue
        out.append(task)
    out.sort(key=_sort_key)
    return out


def show_task(ws: Workspace, task_id: str) -> Task:
    """读取 one 任务; 抛出 TaskNotFound 当 it 做 不 exist."""
    p = task_file(ws, task_id)
    if not p.exists():
        raise TaskNotFound(f"在 {ws.tasks_dir} 中找不到任务 {task_id}")
    try:
        return Task.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise TaskError(f"任务 {task_id} 已损坏：{e}") from e


# --- CLI --------------------------------------------------------------------


def _add_io(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--root", dest="ws_root", type=Path, default=None,
        help="Shared workspace root (default: $COGOS_WORKSPACE or D:/GitHub_Project/SharedWorkspace)",
    )
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")


def _add_actor(p: argparse.ArgumentParser) -> None:
    p.add_argument("--actor", default=None, help="Agent id reporting the change (default: $COGOS_AGENT or 'cogos')")


def add_task_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("task", help="Task registry: create / update / list / show")
    task_sub = p.add_subparsers(dest="task_cmd", required=True)

    p_create = task_sub.add_parser("create", help="Create a task")
    p_create.add_argument("--title", required=True, help="Task title")
    p_create.add_argument("--id", dest="task_id", default=None, help="Explicit id (default: auto TASK-NNN)")
    p_create.add_argument("--assignee", default=None, help="Agent that will execute the task")
    p_create.add_argument("--status", default="pending", help="pending / in_progress / review / done")
    p_create.add_argument("--progress", type=int, default=0, help="0-100")
    p_create.add_argument("--current-file", default=None, help="File the assignee is working on")
    p_create.add_argument("--branch", default=None, help="Git branch")
    p_create.add_argument("--pr-url", default=None, help="Pull request URL")
    p_create.add_argument("--note", default=None, help="Optional kickoff note (goes into history)")
    _add_actor(p_create)
    _add_io(p_create)

    p_update = task_sub.add_parser("update", help="Update a task (progress / status / fields)")
    p_update.add_argument("task_id")
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--assignee", default=None)
    p_update.add_argument("--status", default=None, help="pending / in_progress / review / done")
    p_update.add_argument("--progress", type=int, default=None, help="0-100")
    p_update.add_argument("--current-file", default=None)
    p_update.add_argument("--branch", default=None)
    p_update.add_argument("--pr-url", default=None)
    p_update.add_argument("--note", default=None, help="Note appended to the task history")
    _add_actor(p_update)
    _add_io(p_update)

    p_list = task_sub.add_parser("list", help="List tasks (optionally filtered)")
    p_list.add_argument("--status", default=None, help="Filter by status")
    p_list.add_argument("--assignee", default=None, help="Filter by assignee")
    _add_io(p_list)

    p_show = task_sub.add_parser("show", help="Show one task in full")
    p_show.add_argument("task_id")
    _add_io(p_show)


def run_task(args: argparse.Namespace) -> int:
    ws = Workspace(root=resolve_root(args.ws_root))
    actor = getattr(args, "actor", None) or default_agent()

    if args.task_cmd == "create":
        try:
            task = create_task(
                ws, title=args.title, task_id=args.task_id, assignee=args.assignee,
                status=args.status, progress=args.progress, current_file=args.current_file,
                branch=args.branch, pr_url=args.pr_url, note=args.note, actor=actor,
            )
        except TaskError as e:
            print(f"出错：{e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(
                f"已创建 {task.id}：{task.title} "
                f"（负责人={task.assignee or '-'}，状态={task.status}，进度={task.progress}%）"
            )
        return 0

    if args.task_cmd == "update":
        try:
            task = update_task(
                ws, args.task_id, title=args.title, assignee=args.assignee, status=args.status,
                progress=args.progress, current_file=args.current_file, branch=args.branch,
                pr_url=args.pr_url, note=args.note, actor=actor,
            )
        except TaskError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(
                f"已更新 {task.id}：状态={task.status}，进度={task.progress}%，"
                f"历史记录 {len(task.history)} 条"
            )
        return 0

    if args.task_cmd == "list":
        tasks = list_tasks(ws, status=args.status, assignee=args.assignee)
        if args.json:
            print(json.dumps([t.to_dict() for t in tasks], ensure_ascii=False, indent=2))
        elif not tasks:
            print("（暂无任务）")
        else:
            for t in tasks:
                print(
                    f"{t.id.ljust(9)} {t.status.ljust(11)} {str(t.progress).rjust(3)}%  "
                    f"{t.assignee.ljust(12)} {t.title}"
                )
        return 0

    if args.task_cmd == "show":
        try:
            task = show_task(ws, args.task_id)
        except TaskError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{task.id}  {task.title}")
            print(f"  status:       {task.status}")
            print(f"  assignee:     {task.assignee or '-'}")
            print(f"  progress:     {task.progress}%")
            print(f"  current_file: {task.current_file or '-'}")
            print(f"  branch:       {task.branch or '-'}")
            print(f"  pr_url:       {task.pr_url or '-'}")
            print(f"  created_at:   {task.created_at}")
            print(f"  updated_at:   {task.updated_at}")
            print("  history:")
            for h in task.history:
                print(f"    [{h.get('t', '?')}] {h.get('msg', '')}")
        return 0

    return 2
