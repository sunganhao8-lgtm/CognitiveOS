"""Cross-agent mailbox for the shared multi-agent workspace.

Every agent has an inbox directory ``<root>/.cogos/messages/TO_<agent_id>/``.
Messages are plain JSON files (persistent by design — an offline agent picks
them up on its next startup), see docs/shared-workspace-design.md.

Types follow the design doc: ``review_request`` / ``fix_request`` /
``progress_query``, plus ``general`` and ``lock_conflict`` (sent automatically
when a lock acquire collides with another agent's lock).
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
    """Raised for invalid recipient ids, types or malformed messages."""


@dataclass
class Message:
    """One mailbox message."""

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
        """JSON-friendly dict (``from_`` is serialized as ``from``)."""
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
    """Reject agent ids that are not safe as a directory name.

    This also blocks path traversal (``..``, ``/``, drive letters) so agent
    ids can never escape the messages directory.
    """
    if not _AGENT_ID_RE.fullmatch(agent_id):
        raise InboxError(
            f"invalid agent id: {agent_id!r} (use 1-64 letters, digits, . _ -)"
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
    """Drop a message into ``TO_<to>/``. Persistent: survives agent restarts."""
    ws.ensure()
    to = validate_agent_id(to)
    from_ = validate_agent_id(from_ or default_agent())
    if type not in MESSAGE_TYPES:
        raise InboxError(f"invalid message type {type!r}; choose from {', '.join(MESSAGE_TYPES)}")
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
    """List messages; ``to`` restricts to one agent, otherwise all inboxes.

    ``mark_read`` flips the ``read`` flag on the files that were listed, so a
    later ``check --unread-only`` stops showing them.
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
                continue  # skip corrupt files rather than failing the whole check
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
        help="Shared workspace root (default: $COGOS_WORKSPACE or D:/GitHub_Project/SharedWorkspace)",
    )
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")


def add_inbox_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("inbox", help="Cross-agent mailbox: send / check")
    inbox_sub = p.add_subparsers(dest="inbox_cmd", required=True)

    p_send = inbox_sub.add_parser("send", help="Send a message to another agent's inbox")
    p_send.add_argument("--to", required=True, help="Recipient agent id (inbox TO_<id>)")
    p_send.add_argument("--content", required=True, help="Message body")
    p_send.add_argument("--from", dest="from_", default=None,
                        help="Sender agent id (default: $COGOS_AGENT or 'cogos')")
    p_send.add_argument("--type", default="general",
                        help="review_request / fix_request / progress_query / general / lock_conflict")
    p_send.add_argument("--task-id", default=None, help="Optional related task id")
    p_send.add_argument("--attach", action="append", default=None,
                        help="Attachment label (repeatable), e.g. 'git diff --stat'")
    _add_io(p_send)

    p_check = inbox_sub.add_parser("check", help="Check inbox(es): all by default, one with --to")
    p_check.add_argument("--to", default=None, help="Only check this agent's inbox")
    p_check.add_argument("--unread-only", action="store_true", help="Only show unread messages")
    p_check.add_argument("--mark-read", action="store_true",
                         help="Mark the listed messages as read")
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
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(msg.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"sent [{msg.id}] ({msg.type}) to TO_{msg.to}: {msg.content[:80]}")
        return 0

    if args.inbox_cmd == "check":
        msgs = check_inbox(ws, to=args.to, unread_only=args.unread_only, mark_read=args.mark_read)
        if args.json:
            print(json.dumps([m.to_dict() for m in msgs], ensure_ascii=False, indent=2))
            return 0
        if not msgs:
            print("(no messages)" if args.to else "(no messages in any inbox)")
            return 0
        current: str | None = None
        for m in msgs:
            if m.to != current:
                current = m.to
                print(f"TO_{current}:")
            flag = "" if m.read else " (unread)"
            print(f"  [{m.id}] {m.type} from={m.from_} {m.created_at}{flag}")
            if m.task_id:
                print(f"      task: {m.task_id}")
            if m.content:
                print(f"      {m.content}")
            if m.attachments:
                print(f"      attach: {', '.join(m.attachments)}")
        return 0

    return 2
