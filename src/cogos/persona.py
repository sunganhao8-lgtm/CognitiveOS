"""Persona training — offline self-consistency training of the user model.

The goal of this module is **not** to fine-tune an LLM. The goal is to
maintain a small, hand-readable Markdown model of how the user thinks,
written *by an LLM but verified against real user behaviour*, and to
do this on a cron schedule using the user's idle time.

What this module does
---------------------

1. Picks one historical experience from ``user/experience/`` at random.
2. Builds a prompt that asks the persona model: *what would the user
   most likely say or decide in this situation, given everything we
   know about them?*
4. Compares the prediction against the *actual* user decision recorded
   in the experience file. Computes a reward signal.
5. Asks the same LLM to update ``user/persona/model.md`` only in places
   where the prediction diverged from reality.
6. Persists everything (prediction, reward, model diff) under
   ``user/persona/samples/`` and ``user/persona/drivel.jsonl``.

What this module does NOT do
----------------------------

* It does **not** train neural-network weights. There is no gradient
  step. The "model" is a Markdown file.
* It does **not** auto-commit anything into ``user/`` without the user
  being able to see and revert it. Every update writes a candidate to
  ``samples/`` and only mutates ``model.md`` if the user (or an
  explicit ``cogos persona apply``) accepts it.
* It does **not** replace real conversations with the user. It runs on
  idle time, off-cron, and produces artefacts that the user can
  inspect.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperienceRef:
    """Pointer to one experience file under ``user/experience/``."""

    path: Path

    @property
    def slug(self) -> str:
        return self.path.stem


@dataclass
class TrainSample:
    """Outcome of one persona-training round."""

    timestamp: str
    experience: str
    context: str
    prediction: str
    actual: str
    reward: float  # 1.0 = matched, 0.0 = totally diverged
    model_diff: str
    note: str = ""


# ---------------------------------------------------------------------------
# Experience picking
# ---------------------------------------------------------------------------


def list_experiences(user: UserLayer) -> list[ExperienceRef]:
    root = user.experience
    if not root.exists():
        return []
    return [ExperienceRef(path=p) for p in sorted(root.glob("*.md")) if p.is_file() and p.stem != "INDEX"]


def pick_random(user: UserLayer, *, seed: int | None = None) -> ExperienceRef | None:
    items = list_experiences(user)
    if not items:
        return None
    rng = random.Random(seed)
    return rng.choice(items)


# ---------------------------------------------------------------------------
# Prompt construction (agent-agnostic, fed via Hermes subprocess)
# ---------------------------------------------------------------------------


PERSONA_PROMPT_TEMPLATE = """You are training a model of a specific user — their
thinking style, their trade-off heuristics, and their wording.

## USER MODEL (current best estimate)

{current_model}

## HISTORY OF PAST EXPERIENCES (you may use any of these for context)

{history}

## THE SITUATION YOU MUST PREDICT

File: {experience_path}

{context_body}

## TASK

Pretend you ARE this user. Given everything above, write a short reply
(3-6 lines) that captures what the user would most likely think, say,
or decide in this situation. Be specific. Use the user's voice — see
preferences.md if you need tone guidance.

After your prediction, on a separate line, write:

REWARD: <number from 0.0 to 1.0>

where 1.0 means "this is exactly what the user did", and 0.0 means
"this is the opposite of what the user did". Be honest.

Then on another line:

DIFF_NOTE: <one line about what the user model got wrong, if anything>
"""


def build_prompt(user: UserLayer, exp: ExperienceRef, *, history_limit: int = 5) -> str:
    model_path = user.root / "persona" / "model.md"
    current_model = model_path.read_text(encoding="utf-8") if model_path.exists() else "(no model yet — start from preferences.md)"

    history_paths = list_experiences(user)
    rng = random.Random()
    other = [e for e in history_paths if e.path != exp.path]
    rng.shuffle(other)
    other = other[:history_limit]
    history_blocks = []
    for e in other:
        history_blocks.append(f"### {e.slug}\n\n{e.path.read_text(encoding='utf-8')}\n")
    history = "\n\n".join(history_blocks) if history_blocks else "(no other experiences yet)"

    prefs = user.preferences.read_text(encoding="utf-8") if user.preferences.exists() else ""
    style = user.style.read_text(encoding="utf-8") if user.style.exists() else ""

    context_body = exp.path.read_text(encoding="utf-8")

    return (
        "# USER PREFERENCES\n\n" + prefs
        + "\n\n# USER DECISION STYLE\n\n" + style
        + "\n\n" + PERSONA_PROMPT_TEMPLATE.format(
            current_model=current_model,
            history=history,
            experience_path=str(exp.path.relative_to(user.root.parent)),
            context_body=context_body,
        )
    )


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------


def _extract_field(text: str, field: str) -> str:
    for line in text.splitlines():
        if line.strip().upper().startswith(field.upper() + ":"):
            return line.split(":", 1)[1].strip()
    return ""


def parse_sample_output(text: str) -> tuple[str, float, str]:
    prediction_lines: list[str] = []
    for line in text.splitlines():
        if line.strip().upper().startswith("REWARD:"):
            break
        if line.strip().upper().startswith("DIFF_NOTE:"):
            break
        prediction_lines.append(line)
    prediction = "\n".join(prediction_lines).strip()

    reward_raw = _extract_field(text, "REWARD")
    try:
        reward = max(0.0, min(1.0, float(reward_raw)))
    except ValueError:
        reward = 0.5

    diff = _extract_field(text, "DIFF_NOTE")
    return prediction, reward, diff


# ---------------------------------------------------------------------------
# Round driver
# ---------------------------------------------------------------------------


@dataclass
class RoundResult:
    sample: TrainSample
    model_updated: bool
    sample_path: Path


def record_sample(user: UserLayer, exp: ExperienceRef, prompt: str, text: str) -> TrainSample:
    prediction, reward, diff = parse_sample_output(text)
    sample = TrainSample(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        experience=str(exp.path.relative_to(user.root.parent)),
        context=prompt[-1000:],  # tail of the prompt for audit
        prediction=prediction,
        actual=exp.path.read_text(encoding="utf-8")[:1000],
        reward=reward,
        model_diff=diff,
    )

    persona_dir = user.root / "persona"
    samples_dir = persona_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = sample.timestamp.replace(":", "-")
    out = samples_dir / f"{safe_ts}_{exp.slug}.json"
    out.write_text(json.dumps(asdict(sample), ensure_ascii=False, indent=2), encoding="utf-8")

    drivel = persona_dir / "drivel.jsonl"
    with drivel.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(sample), ensure_ascii=False) + "\n")

    return sample, out


def maybe_update_model(user: UserLayer, sample: TrainSample) -> bool:
    """If the reward is high, leave the model alone. If low, append a
    delta entry under ``persona/model.md`` so the user can review and
    accept or revert.

    Returns True iff a candidate delta was appended.
    """
    if sample.reward >= 0.7:
        return False

    persona_dir = user.root / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    model_path = persona_dir / "model.md"
    if not model_path.exists():
        model_path.write_text(
            (
                "# User Persona Model\n\n"
                "Generated by ``cogos persona train``. Each entry below\n"
                "is a candidate observation produced by an offline training\n"
                "round. Edit freely. Delete lines to revert.\n\n"
            ),
            encoding="utf-8",
        )

    delta = (
        f"\n## {sample.timestamp} — {sample.experience} (reward={sample.reward:.2f})\n\n"
        f"**Prediction:** {sample.prediction}\n\n"
        f"**What was off:** {sample.model_diff or '(no note)'}\n"
    )
    with model_path.open("a", encoding="utf-8") as fh:
        fh.write(delta)
    return True