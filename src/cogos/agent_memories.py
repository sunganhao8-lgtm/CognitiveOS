"""从非 Hermes Agent 中抽取对话记忆。

本模块把*对话历史*从其他 AI Agent 中抽出来，写入 CognitiveOS 的
``user/conversations/`` 存储，格式与 Hermes 抽取器一致——都是
主人问答对。这是「主人的认知」层：跨 Agent 切换也能保留的记忆。

当前支持的数据源：

* Codex（``~/.codex/sessions/**/rollout-*.jsonl``）：``response_item``
  记录中含 ``role: user`` / ``role: assistant`` 消息。
* Claude Code（``~/.claude/projects/**/*.jsonl``）：``user`` 和
  ``assistant`` 记录。

只读，不修改 Agent 文件；只保存「问题 → 答案」对（不保存工具调用
轨迹），与 conversations.py 保持一致。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


@dataclass(frozen=True)
class QA:
    session_id: str
    question_id: str
    question: str
    answer: str
    timestamp: str
    source: str  # e.g. "codex", "claude_code"


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


def _is_noise(text: str) -> bool:
    """Heuristic: skip internal Codex plumbing messages that are not
    master↔agent conversation (approval prompts, tool permission echoes,
    system context injections)."""
    markers = (
        "The following is the Codex agent history",
        "whose request action you are",
        "outcome\":\"allow",
        "approval",
        "request action",
        "added since your last",
        "context from my IDE",
        "Open tabs:",
        "<user_instructions>",
        "<context",
        "tool_use",
        "permission",
        "deny",
        "sandbox_policy",
        "approval_policy",
    )
    low = text.lower()
    return any(m.lower() in low for m in markers)


def _codex_text(content) -> str:
    """Extract plain text from a Codex content block (list of dicts or str)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                ctype = c.get("type")
                if ctype in ("input_text", "output_text", "text"):
                    parts.append(c.get("text", ""))
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    return ""


def extract_codex(codex_root: Path, *, limit: int | None = None) -> list[QA]:
    """Extract QA pairs from Codex rollout JSONL files."""
    if not codex_root.exists():
        return []
    files = sorted(codex_root.rglob("rollout-*.jsonl"))
    pairs: list[QA] = []
    for f in files:
        session_id = f.stem.replace("rollout-", "")
        # walk records in order; pair user message with next assistant message
        last_user: tuple[str, str, str] | None = None  # (ts, text, qid)
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "response_item":
                continue
            payload = rec.get("payload", {})
            role = payload.get("role")
            ts = rec.get("timestamp", "")
            if role == "user":
                text = _codex_text(payload.get("content"))
                if text and len(text) > 10 and not _is_noise(text):
                    last_user = (ts, text, f"{session_id[:12]}-{ts}")
            elif role == "assistant" and last_user is not None:
                text = _codex_text(payload.get("content"))
                if text and len(text) > 10 and not _is_noise(text):
                    u_ts, u_text, qid = last_user
                    pairs.append(
                        QA(
                            session_id=session_id,
                            question_id=qid,
                            question=u_text[:2000],
                            answer=text[:2000],
                            timestamp=u_ts,
                            source="codex",
                        )
                    )
                    last_user = None  # consume the pair
            if limit and len(pairs) >= limit:
                return pairs
    return pairs


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------


def extract_claude_code(claude_root: Path, *, limit: int | None = None) -> list[QA]:
    """Extract QA pairs from Claude Code project JSONL files."""
    if not claude_root.exists():
        return []
    files = sorted(claude_root.rglob("*.jsonl"))
    pairs: list[QA] = []
    for f in files:
        session_id = f.stem
        last_user: tuple[str, str, str] | None = None
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = rec.get("type")
            if t == "user":
                msg = rec.get("message", {})
                if msg.get("role") == "user":
                    content = msg.get("content")
                    text = content if isinstance(content, str) else _codex_text(content)
                    ts = rec.get("timestamp", "")
                    if text and len(text) > 10:
                        last_user = (ts, text, f"{session_id[:12]}-{ts}")
            elif t == "assistant":
                msg = rec.get("message", {})
                if msg.get("role") == "assistant" and last_user is not None:
                    content = msg.get("content")
                    text = content if isinstance(content, str) else _codex_text(content)
                    if text and len(text) > 10:
                        u_ts, u_text, qid = last_user
                        pairs.append(
                            QA(
                                session_id=session_id,
                                question_id=qid,
                                question=u_text[:2000],
                                answer=text[:2000],
                                timestamp=u_ts,
                                source="claude_code",
                            )
                        )
                        last_user = None
            if limit and len(pairs) >= limit:
                return pairs
    return pairs


# ---------------------------------------------------------------------------
# Write into CognitiveOS store
# ---------------------------------------------------------------------------


def write_pairs(user: UserLayer, pairs: list[QA], source: str) -> Path:
    """Append QA pairs to ``user/conversations/<source>-<date>.jsonl``."""
    conv_dir = user.root / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    out = conv_dir / f"{source}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"

    existing = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing.add(json.loads(line).get("question_id"))
            except json.JSONDecodeError:
                pass

    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for p in pairs:
            if p.question_id in existing:
                continue
            fh.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
            added += 1
    return out


def extract_all(user: UserLayer, *, limit_per_source: int | None = None) -> dict[str, int]:
    """Extract from every known agent home; return {source: added_count}."""
    import os

    home = Path(os.path.expanduser("~"))
    results: dict[str, int] = {}

    codex_pairs = extract_codex(home / ".codex" / "sessions", limit=limit_per_source)
    if codex_pairs:
        write_pairs(user, codex_pairs, "codex")
        results["codex"] = len(codex_pairs)

    claude_pairs = extract_claude_code(home / ".claude" / "projects", limit=limit_per_source)
    if claude_pairs:
        write_pairs(user, claude_pairs, "claude_code")
        results["claude_code"] = len(claude_pairs)

    return results