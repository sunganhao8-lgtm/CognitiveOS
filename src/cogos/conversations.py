"""对话抽取。

读取 Hermes 的 SQLite 会话存储，抽出主人→管家的问答对，供后续
persona 训练使用。

抽取刻意保守：

- 只读 ``默认`` profile 的 session DB（主对话存储）。
  像 ``vidiator`` / ``researcher`` 这种是 worker profile，里面的
  对话不算「主人的」。
- 只保留「主人问的问题」（以问号结尾——中文问号或英文问号），
  因为问题最有训练价值：一个问题需要的就是主人风格的回答。
- 跳过 tool / 压缩 / 系统消息。
- 输出写到 ``user/对话们/`` 的 JSONL 文件，每行一条问答对，
  含出处（session_id、消息 id）。

只读，**永远不写** Hermes 的 DB。
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
    """从 Hermes state.db 抽取问答对。

    一对 = 主人一条以问号结尾的消息 + 同会话下一条助手文本消息。
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

    def _iso(ts_raw) -> str:
        """把任何时间戳列形态归一为 ISO。"""
        if ts_raw is None:
            return ""
        if isinstance(ts_raw, (int, float)):
            from datetime import datetime as _dt, timezone as _tz
            return _dt.fromtimestamp(float(ts_raw), _tz.utc).isoformat(timespec="seconds")
        return str(ts_raw)

    pairs: list[QA] = []
    by_session: dict[str, list[tuple[int, str, str, str]]] = {}
    for mid, sid, role, content, ts in rows:
        content = (content or "").strip()
        if not content:
            continue
        by_session.setdefault(sid, []).append((mid, role, content, _iso(ts)))

    for sid, msgs in by_session.items():
        for i, (mid, role, content, ts) in enumerate(msgs):
            if role != "user":
                continue
            if len(content) < min_len:
                continue
            if not QUESTION_RE.search(content):
                continue
            # 找下一条助手文本消息。
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
    """追加抽出的问答对到 ``user/对话们/*.jsonl``。"""
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
    """随机返回几条问答记录，方便看 / 测试。"""
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