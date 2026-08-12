"""共享多 Agent 工作区的跨 Agent 收件箱。

每个 Agent 有一个收件箱目录 ``<root>/.cogos/messages/TO_<agent_id>/``。
消息是普通 JSON 文件（持久化——离线的 Agent 下次启动时就能取到），
见 docs/shared-workspace-design.md。

类型按设计文档：``review_request`` / ``fix_request`` / ``progress_query``，
外加 ``general`` 和 ``lock_conflict``（加锁冲突时自动发）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
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

MESSAGE_TYPES = ("general", "review_request", "fix_request", "progress_query", "lock_conflict")

_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class InboxError(Exception):
    """无效的收件人 id、类型或格式错误的消息都会抛此异常。"""


@dataclass
class Message:
    """一封收件箱消息。"""

    id: str
    from_: str
    to: str
    type: str = "general"
    content: str = ""
    task_id: str = ""
    attachments: list[str] = field(default_factory=list)
    created_at: str = ""
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON 友好字典（``from_`` 序列化为 ``from``）。"""
        d = asdict(self)
        d["from"] = d.pop("from_")
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        data = dict(data)
        if "from" in data:
            data["from_"] = data.pop("from")
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def validate_agent_id(agent_id: str) -> str:
    """拒绝不适合作为目录名的 agent id。

    同时阻挡路径穿越（``..``、``/``、盘符），保证 agent id 永远跑不出
    messages 目录。
    """
    if not _AGENT_ID_RE.fullmatch(agent_id):
        raise InboxError(
            f"无效的 Agent id：{agent_id!r}（使用 1-64 位字母、数字、点、下划线、连字符）"
        )
    return agent_id


def mailbox_dir(ws: Workspace, agent_id: str) -> Path:
    return ws.messages_dir / f"TO_{validate_agent_id(agent_id)}"


def send_message(
    ws: Workspace,
    *,
    to: str,
    content: str,
    from_: str | None = None,
    type: str = "general",
    task_id: str | None = None,
    attachments: list[str] | None = None,
    now: datetime | None = None,
) -> Message:
    """把消息塞进 ``TO_<to>/``。持久化：Agent 重启不丢。"""
    ws.ensure()
    to = validate_agent_id(to)
    from_ = validate_agent_id(from_ or default_agent())
    if type not in MESSAGE_TYPES:
        raise InboxError(f"无效的消息类型 {type!r}；可选：{', '.join(MESSAGE_TYPES)}")
    ts = now_iso(now)
    msg = Message(
        id=uuid.uuid4().hex[:12],
        from_=from_,
        to=to,
        type=type,
        content=content,
        task_id=task_id or "",
        attachments=list(attachments or []),
        created_at=ts,
    )
    # Windows-safe filename: ISO timestamps contain ':' which is illegal.
    fname = f"{ts.replace(':', '-')}-{msg.id}.json"
    atomic_write_json(mailbox_dir(ws, to) / fname, msg.to_dict())
    return msg


def check_inbox(
    ws: Workspace,
    to: str | None = None,
    unread_only: bool = False,
    mark_read: bool = False,
) -> list[Message]:
    """列消息；``to`` 限定只看一个 Agent，否则看所有收件箱。

    ``mark_read`` 会把列出的消息 ``read`` 标志置位，这样再跑
    ``check --unread-only`` 就看不到了。
    """
    if to is not None:
        to = validate_agent_id(to)
    out: list[Message] = []
    if not ws.messages_dir.exists():
        return out
    boxes = [mailbox_dir(ws, to)] if to else sorted(ws.messages_dir.glob("TO_*"))
    for box in boxes:
        if not box.is_dir():
            continue
        for p in sorted(box.glob("*.json")):
            try:
                msg = Message.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue  # 跳过损坏文件，别让整个 check 挂掉
            if unread_only and msg.read:
                continue
            if mark_read and not msg.read:
                msg.read = True
                atomic_write_json(p, msg.to_dict())
            out.append(msg)
    return out


# --- CLI --------------------------------------------------------------------


def _add_io(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--root", dest="ws_root", type=Path, default=None,
        help="共享工作区根（默认：$COGOS_WORKSPACE 或 D:/GitHub_Project/SharedWorkspace）",
    )
    p.add_argument("--json", action="store_true", help="机器可读 JSON 输出")


def add_inbox_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("inbox", help="跨 Agent 收件箱：send / check")
    inbox_sub = p.add_subparsers(dest="inbox_cmd", required=True)

    p_send = inbox_sub.add_parser("send", help="往另一个 Agent 的收件箱发一封消息")
    p_send.add_argument("--to", required=True, help="收件 Agent id（inbox TO_<id>）")
    p_send.add_argument("--content", required=True, help="消息正文")
    p_send.add_argument("--from", dest="from_", default=None,
                        help="发件 Agent id（默认：$COGOS_AGENT 或 cogos）")
    p_send.add_argument("--type", default="general",
                        help="review_request / fix_request / progress_query / general / lock_conflict")
    p_send.add_argument("--task-id", default=None, help="可选关联任务 id")
    p_send.add_argument("--attach", action="append", default=None,
                        help="附件标签（可重复），如 'git diff --stat'")
    _add_io(p_send)

    p_check = inbox_sub.add_parser("check", help="查看收件箱：不传 --to 看全部，传了只该 Agent）")
    p_check.add_argument("--to", default=None, help="只看这个 Agent 的收件箱")
    p_check.add_argument("--unread-only", action="store_true", help="只看未读")
    p_check.add_argument("--mark-read", action="store_true",
                         help="把列出的消息标记为已读")
    _add_io(p_check)


def run_inbox(args: argparse.Namespace) -> int:
    ws = Workspace(root=resolve_root(args.ws_root))

    if args.inbox_cmd == "send":
        try:
            msg = send_message(
                ws, to=args.to, content=args.content, from_=args.from_,
                type=args.type, task_id=args.task_id, attachments=args.attach,
            )
        except InboxError as e:
            print(f"出错：{e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(msg.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"已发送 [{msg.id}]（{msg.type}）到 TO_{msg.to}：{msg.content[:80]}")
        return 0

    if args.inbox_cmd == "check":
        msgs = check_inbox(ws, to=args.to, unread_only=args.unread_only, mark_read=args.mark_read)
        if args.json:
            print(json.dumps([m.to_dict() for m in msgs], ensure_ascii=False, indent=2))
            return 0
        if not msgs:
            print("（无消息）" if args.to else "（所有收件箱均为空）")
            return 0
        current: str | None = None
        for m in msgs:
            if m.to != current:
                current = m.to
                print(f"TO_{current}:")
            flag = "" if m.read else "（未读）"
            print(f"  [{m.id}] {m.type} from={m.from_} {m.created_at}{flag}")
            if m.task_id:
                print(f"      task: {m.task_id}")
            if m.content:
                print(f"      {m.content}")
            if m.attachments:
                print(f"      attach: {', '.join(m.attachments)}")
        return 0

    return 2
