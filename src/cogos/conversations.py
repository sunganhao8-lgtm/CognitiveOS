"""Conversation extraction.

Reads Hermes's SQLite session store and extracts user → assistant
question/answer pairs that can later be used for persona training.

The extraction is deliberately conservative:

- Only the ``default`` profile's session DB is read (the main
  conversation store).  Profiles like ``vidiator`` / ``researcher`` are
  worker profiles and their conversations are not "the master's".
- We only keep pairs where the user message is a *question* (ends with
  a question mark — Chinese or ASCII), because those are the most
  informative for training a persona: a question demands an answer that
  matches how the master would reply.
- We skip tool/compaction/system messages.
- Output is written to ``user/conversations/`` as JSONL, one record per
  question/answer pair, with provenance (session_id, message ids).

The store is read-only; this module never writes to Hermes's DB.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


QUESTION_RE = re.compile(r"[?？]\s*$")


@dataclass(frozen=True)
class QA:
    session_id: str
    question_id: int
    answer_id: int | None
    question: str
    answer: str
    timestamp: str


def extract_qa(db_path: Path, *, limit: int | None = None, min_len: int = 20) -> list[QA]:
    """Extract question/answer pairs from a Hermes state.db.

    A pair is: a user message ending in a question mark, followed by the
    next assistant text message in the same session.
    """
    if not db_path.exists():
        return []

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT id, session_id, role, content, timestamp FROM messages "
            "WHERE role IN ('user','assistant') ORDER BY session_id, id"
        ).fetchall()
    finally:
        con.close()

    pairs: list[QA] = []
    by_session: dict[str, list[tuple[int, str, str, str]]] = {}
    for mid, sid, role, content, ts in rows:
        content = (content or "").strip()
        if not content:
            continue
        by_session.setdefault(sid, []).append((mid, role, content, ts))

    for sid, msgs in by_session.items():
        for i, (mid, role, content, ts) in enumerate(msgs):
            if role != "user":
                continue
            if len(content) < min_len:
                continue
            if not QUESTION_RE.search(content):
                continue
            # Find the next assistant text message.
            answer = None
            for j in range(i + 1, len(msgs)):
                if msgs[j][1] == "assistant":
                    answer = msgs[j]
                    break
            if answer is None:
                continue
            answer_text = answer[2]
            if len(answer_text) < 10:
                continue
            pairs.append(
                QA(
                    session_id=sid,
                    question_id=mid,
                    answer_id=answer[0],
                    question=content,
                    answer=answer_text[:2000],
                    timestamp=ts,
                )
            )

    if limit:
        pairs = pairs[:limit]
    return pairs


def write_conversations(user: UserLayer, pairs: list[QA]) -> Path:
    """Append extracted QA pairs to ``user/conversations/*.jsonl``."""
    conv_dir = user.root / "conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)
    out = conv_dir / f"hermes-{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    existing = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            existing.add(rec["question_id"])
    added = 0
    with out.open("a", encoding="utf-8") as fh:
        for p in pairs:
            if p.question_id in existing:
                continue
            fh.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
            added += 1
    return out


def sample_conversations(user: UserLayer, *, k: int = 3) -> list[dict]:
    """Return a few random QA records for inspection / testing."""
    import random

    conv_dir = user.root / "conversations"
    if not conv_dir.exists():
        return []
    records = []
    for f in sorted(conv_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    rng = random.Random()
    rng.shuffle(records)
    return records[:k]