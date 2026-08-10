"""Persona fitting — semantic-match training against the master's past answers.

This is the training loop the user actually described:

1. Take a real **question the master asked the butler in the past**.
2. Give that question to the *current* butler (via Hermes CLI), along
   with the master's persona model (preferences, style, manifest).
3. The butler answers **as the master would answer the question** —
   not as the master's past butler answered, but as the master himself
   would have responded.
4. Compare the butler's answer to what the master **actually said**
   (their real historical reply) using semantic similarity.
5. Score the match. Write the sample to ``user/persona/samples/`` and
   the running log to ``user/persona/drivel.jsonl``.

The score is computed by the same LLM, but the *reference* is the
master's real words — not the butler's own earlier prediction. That is
the key difference from the previous (self-rewarding) design: there is
a ground-truth reference in the loop, so the score is a semantic match
against reality, not a self-evaluation.

Reward definition (0.0–1.0):

* >= 0.8 : the butler's persona reply semantically matches the
  master's real answer.
* 0.4–0.8: partial match — tone or intent right, details off.
* < 0.4  : the butler's persona reply does not sound like the master.

A high score means the persona model is a good fit. A low score means
the persona model needs updating (see ``maybe_update_model``).
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
# Loading historical QA pairs
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


PERSONA_FIT_PROMPT = """You are a butler fitting yourself to a specific master.
You are given (A) the master's persona, and (B) a real question the master
once asked a previous butler.

Your job: answer that question **the way the master himself would answer
it** — in their voice, their priorities, their decision style. This is
NOT about answering as a helpful assistant. It is about predicting the
master's own reply.

Then, after your persona answer, rate how well it matches the master's
actual historical answer, which you will be shown AFTER you write yours.

## THE MASTER'S PERSONA

{persona}

## THE QUESTION THE MASTER ASKED

{question}

## YOUR PERSONA ANSWER (3-6 lines, master's voice):

"""


EVAL_PROMPT = """Now rate the semantic match between the butler's persona
answer and the master's actual historical answer.

Butler's persona answer (what the master would say):

{butler_answer}

Master's actual historical answer:

{master_answer}

Score the semantic match from 0.0 (totally different) to 1.0 (identical
meaning, tone, and intent).

Reply with ONLY a JSON object, no prose:

{{"score": 0.85, "note": "one line about what matched or diverged"}}
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
    """Append a delta to model.md when the persona fit is weak."""
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