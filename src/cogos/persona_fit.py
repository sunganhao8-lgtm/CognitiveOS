"""Persona fitting — semantic-match training against 主人's past answers.

This 是 该 training loop 用户 actually described:

1. Take a real **question 主人 asked 该 butler 在 该 past**.
2. Give that question 到 该 *当前* butler (via Hermes CLI), along
   使用 主人's persona model (preferences, style, manifest).
3. 该 butler answers **作为 主人 将 answer 该 question** —
   不 作为 主人's past butler answered, but 作为 主人 himself
   将 有 responded.
4. Compare 该 butler's answer 到 what 主人 **actually said**
   (their real historical reply) using semantic similarity.
5. Score 该 match. 写入 该 sample 到 ``user/persona/samples/`` 和
   该 running log 到 ``user/persona/drivel.jsonl``.

该 score 是 computed 通过 该 相同 LLM, but 该 *reference* 是 该
master's real words — 不 该 butler's own earlier prediction. 也就是说
键 difference 来自 上一个 (self-rewarding) design: there 是
a ground-truth reference 在 该 loop, so 该 score 是 a semantic match
against reality, 不 a self-evaluation.

Reward definition (0.0–1.0):

* >= 0.8 : 该 butler's persona reply semantically matches 该
  master's real answer.
* 0.4–0.8: partial match — tone 或 intent right, details off.
* < 0.4  : 该 butler's persona reply 做 不 sound like 主人.

A high score means 该 persona model 是 a good fit. A low score means
该 persona model needs updating (see ``maybe_update_model``).
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


@dataclass(frozen=True)
class QAItem:
    session_id: str
    question_id: int
    answer_id: int | None
    question: str
    answer: str
    timestamp: str


@dataclass
class FitSample:
    timestamp: str
    question_id: int
    question: str
    butler_answer: str
    master_answer: str  # ground truth (historical)
    semantic_score: float
    diff_note: str = ""
    session_id: str = ""


# ---------------------------------------------------------------------------
# 加载中 historical QA pairs
# ---------------------------------------------------------------------------


def load_qa_pairs(user: UserLayer) -> list[QAItem]:
    conv_dir = user.root / "conversations"
    if not conv_dir.exists():
        return []
    records: list[QAItem] = []
    for f in sorted(conv_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            records.append(
                QAItem(
                    session_id=rec.get("session_id", ""),
                    question_id=rec.get("question_id", 0),
                    answer_id=rec.get("answer_id"),
                    question=rec.get("question", ""),
                    answer=rec.get("answer", ""),
                    timestamp=rec.get("timestamp", ""),
                )
            )
    return records


def pick_random_qa(user: UserLayer, *, seed: int | None = None) -> QAItem | None:
    pairs = load_qa_pairs(user)
    if not pairs:
        return None
    rng = random.Random(seed)
    return rng.choice(pairs)


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


PERSONA_FIT_PROMPT = """You 是 a butler fitting yourself 到 a 具体 master.
You 是 given (A) 主人's persona, 和 (B) a real question 主人
once asked a 上一个 butler.

Your job: answer that question **该 way 主人 himself 将 answer
it** — 在 their voice, their priorities, their decision style. This 是
不 about answering 作为 a helpful assistant. It 是 about predicting 该
master's own reply.

Then, after your persona answer, rate how well it matches 主人's
actual historical answer, which you 将 为 shown AFTER you 写入 yours.

## 主人'S PERSONA

{persona}

## 该 QUESTION 主人 ASKED

{question}

## YOUR PERSONA ANSWER (3-6 lines, master's voice):

"""


EVAL_PROMPT = """给下面两段答案的语义匹配程度打分。

Butler's persona answer（主人会怎么说）：

{butler_answer}

Master's actual historical answer（主人真实历史答案）：

{master_answer}

分数范围 0.0（完全不同）到 1.0（含义、语气、意图完全一致）。
打分要严。

只回一个 JSON 对象，不要其他文字：

{{"score": 0.85, "注意": "一句话说明匹配或偏离点"}}
"""


def build_persona_block(user: UserLayer) -> str:
    prefs = user.preferences.read_text(encoding="utf-8") if user.preferences.exists() else ""
    style = user.style.read_text(encoding="utf-8") if user.style.exists() else ""
    manifest = (user.root / "manifest.md").read_text(encoding="utf-8") if (user.root / "manifest.md").exists() else ""
    return f"# PREFERENCES\n\n{prefs}\n\n# STYLE\n\n{style}\n\n# MANIFEST\n\n{manifest}"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def record_fit_sample(user: UserLayer, sample: FitSample) -> Path:
    persona_dir = user.root / "persona"
    samples_dir = persona_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = sample.timestamp.replace(":", "-")
    out = samples_dir / f"{safe_ts}_q{sample.question_id}.json"
    out.write_text(json.dumps(asdict(sample), ensure_ascii=False, indent=2), encoding="utf-8")

    drivel = persona_dir / "drivel.jsonl"
    with drivel.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")
    return out


def maybe_update_model(user: UserLayer, sample: FitSample) -> bool:
    """Append a delta 到 model.md 当 该 persona fit 是 weak."""
    if sample.semantic_score >= 0.7:
        return False

    persona_dir = user.root / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    model_path = persona_dir / "model.md"
    if not model_path.exists():
        model_path.write_text(
            "# User Persona Model\n\n"
            "Candidate observations produced by persona-fitting rounds.\n"
            "Edit freely; delete lines to revert.\n\n",
            encoding="utf-8",
        )

    delta = (
        f"\n## {sample.timestamp} — q{sample.question_id} (semantic score={sample.semantic_score:.2f})\n\n"
        f"**Question:** {sample.question[:200]}\n\n"
        f"**Butler answered:** {sample.butler_answer[:200]}\n\n"
        f"**Master actually said:** {sample.master_answer[:200]}\n\n"
        f"**Divergence:** {sample.diff_note or '(no note)'}\n"
    )
    with model_path.open("a", encoding="utf-8") as fh:
        fh.write(delta)
    return True