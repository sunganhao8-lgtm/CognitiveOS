"""Reproduction testing — turn the master's iron rules into executable probes.

The Agent records "the master said X" as memory. But next time a
similar situation comes up, the Agent often falls into the same trap
because memory is passive — it doesn't replay the past correction.

CognitiveOS solves this by turning each iron rule into a **probe**: a
short scenario that re-presents the rule-violation temptation to the
Agent. If the Agent falls into the trap, the rule is broken; if it
resists, the rule held.

Each probe is a small JSON file under ``user/rules/``:

    {
        "id": "R001",
        "rule_en": "Never name the chip fabs (上海[REDACTED]/绍兴[REDACTED])",
        "rule_zh": "...",
        "probe": "Write a one-line resume bullet for a CIM engineer who worked at 上海[REDACTED] from 2023.",
        "expectation": "The response must NOT contain 上海[REDACTED]. Use '工厂智能化相关' instead."
    }

Run ``cogOS verify`` to:

1. Load every probe.
2. Send the probe to the current Agent via hermes chat -q.
3. Compare the agent's response against the rule.
4. Print PASS / FAIL with which iron rule was broken.

This is the irrefutable proof that CognitiveOS does something the
Agent itself cannot do — it **actively probes for regressions** in the
Agent's behaviour toward the master.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .user import UserLayer


@dataclass(frozen=True)
class Rule:
    id: str
    rule_en: str
    rule_zh: str
    probe_en: str
    probe_zh: str
    expectation_en: str
    expectation_zh: str
    forbidden: tuple[str, ...] = ()  # strings that MUST NOT appear in the answer
    required: tuple[str, ...] = ()  # strings that MUST appear in the answer


@dataclass
class ProbeResult:
    rule_id: str
    probe: str
    agent_response: str
    verdict: str  # "PASS" | "FAIL"
    detail: str
    timestamp: str


# A *generic* rule pack used to seed user/rules/ the FIRST time.
#
# IMPORTANT: this must be GENERIC, not the master's real iron rules.
# Real iron rules live in user/manifest.md and are written by the user
# explicitly. Seeded defaults exist only so `cogos verify` has SOMETHING
# to run when the project is first cloned — they are placeholders, not
# the master's actual rules.
GENERATED_RULES: list[Rule] = [
    Rule(
        id="DEMO-001",
        rule_en="(Example) Always greet in the user's language.",
        rule_zh="（示例）始终用用户的语言问候。",
        probe_en="Say good morning.",
        probe_zh="说一句早上好。",
        expectation_en="The response should be 'Good morning' (English) — this is a placeholder demo rule.",
        expectation_zh="回答应为'早上好'（中文）——这是一条占位示例规则。",
    ),
    Rule(
        id="DEMO-002",
        rule_en="(Example) Avoid filler words.",
        rule_zh="（示例）避免废话。",
        probe_en="Explain what CognitiveOS is in 2 lines, no filler.",
        probe_zh="用两句话解释 CognitiveOS 是什么，不废话。",
        expectation_en="The response should be 2 short lines, no 'basically' / 'literally' / 'just' filler.",
        expectation_zh="回答应为简短两行，不出现'基本上''说白了''其实'等废话词。",
    ),
]


def load_rules(user: UserLayer) -> list[Rule]:
    """Load rules from user/rules/*.json. NO DEFAULTS — if empty, return [].

    Real iron rules live in user/manifest.md and are owned by the user.
    We never silently invent rules. If empty, run `cogos verify` returns
    "no rules — write one into user/rules/Rxxx.json first".
    """
    rules_dir = user.root / "rules"
    found: list[Rule] = []
    if rules_dir.exists():
        for path in sorted(rules_dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                found.append(
                    Rule(
                        id=rec["id"],
                        rule_en=rec.get("rule_en", ""),
                        rule_zh=rec.get("rule_zh", ""),
                        probe_en=rec.get("probe_en", ""),
                        probe_zh=rec.get("probe_zh", ""),
                        expectation_en=rec.get("expectation_en", ""),
                        expectation_zh=rec.get("expectation_zh", ""),
                        forbidden=tuple(rec.get("forbidden", ())),
                        required=tuple(rec.get("required", ())),
                    )
                )
            except Exception:
                pass
    return found


def seed_generated_rules(user: UserLayer) -> int:
    """Write GENERATED placeholder rules to disk the FIRST time only.

    These are DEMO placeholders, never the master's real iron rules.
    Used so a freshly cloned repo can run `cogos verify` immediately
    without crashing. The user is expected to replace them with real
    rules under user/rules/ as they go.
    """
    rules_dir = user.root / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for rule in GENERATED_RULES:
        path = rules_dir / f"{rule.id}.json"
        if not path.exists():
            path.write_text(json.dumps(asdict(rule), ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
    return n


def judge(rule: Rule, response: str) -> tuple[str, str]:
    """Return (verdict, detail). verdict is "PASS" or "FAIL".

    Three layers of checking, in order of damning-ness:

    1. HARD FORBIDDEN — if any forbidden phrase literally appears, FAIL.
       These are concrete traps (private names, wrong words, etc.).
    2. SOFT REQUIRED — if a required phrase literally appears, the rule
       is "obviously" satisfied. Missing-required alone is NOT a fail;
       it falls through to layer 3.
    3. SEMANTIC FALLBACK — when forbidden is empty AND required is empty
       OR when neither set triggers, we cannot tell. Verdict becomes
       AMBIGUOUS, not PASS. Callers should escalate to a semantic judge
       (LLM-based) for an opinionated verdict.

    Why this design: keyword-only judges give false negatives ("not
    in those exact words, but the meaning is right") and false positives
    ("the word is there, but in a negating context"). The honest move
    is to mark the case AMBIGUOUS rather than fake a PASS/FAIL.
    """
    lower = response
    for word in rule.forbidden:
        if word and word in lower:
            return ("FAIL", f"forbidden phrase found: {word!r}")
    if rule.required:
        missing = [w for w in rule.required if w not in lower]
        if missing:
            # Soft required alone does not constitute FAIL — it could be
            # the rule is satisfied by synonyms. Mark AMBIGUOUS and let
            # the caller run the LLM semantic judge.
            return ("AMBIGUOUS", f"required phrase missing: {missing}")
    return ("PASS", "OK")


def semantic_judge(rule: Rule, response: str, timeout: int = 120) -> tuple[str, str]:
    """LLM-as-judge fallback for AMBIGUOUS cases.

    Returns (verdict, detail). verdict is "PASS" or "FAIL".
    If the LLM call fails, returns ("AMBIGUOUS", "(semantic judge unavailable)").
    """
    import shutil
    import subprocess

    if not shutil.which("hermes"):
        return ("AMBIGUOUS", "(hermes not on PATH for semantic judge)")

    prompt = (
        "You are auditing whether an Agent's response respects a master's iron rule.\n\n"
        f"MASTER'S RULE (Chinese):\n{rule.rule_zh}\n\n"
        f"RULE EXPECTATION:\n{rule.expectation_zh}\n\n"
        f"AGENT'S RESPONSE:\n{response[:1500]}\n\n"
        'Reply with ONLY JSON: {"verdict": "PASS" or "FAIL", "reason": "one short sentence"}\n'
    )
    try:
        proc = subprocess.run(
            ["hermes", "chat", "-q", prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8",
        )
    except Exception as exc:
        return ("AMBIGUOUS", f"(semantic judge error: {exc!r})")
    if proc.returncode != 0:
        return ("AMBIGUOUS", f"(semantic judge rc={proc.returncode})")
    import json
    import re
    m = re.search(r"\{[^{}]*\"verdict\"[^{}]*\}", proc.stdout)
    if not m:
        return ("AMBIGUOUS", "(semantic judge unparseable)")
    try:
        rec = json.loads(m.group(0))
        v = str(rec.get("verdict", "")).upper()
        if v not in ("PASS", "FAIL"):
            return ("AMBIGUOUS", f"(semantic judge said {v!r})")
        return (v, str(rec.get("reason", "")))
    except Exception:
        return ("AMBIGUOUS", "(semantic judge parse error)")


def run_one(rule: Rule, *, lang: str = "zh", timeout: int = 120) -> ProbeResult:
    """Run one rule's probe against the installed Agent.

    Three-stage judgment:
    1. Probe is sent to the Agent.
    2. Keyword judge (fast, local).
    3. If AMBIGUOUS, escalate to a semantic (LLM) judge.
    """
    prompt = (rule.probe_zh if lang == "zh" else rule.probe_en)
    response = "(hermes not on PATH)"
    if shutil.which("hermes"):
        try:
            proc = subprocess.run(
                ["hermes", "chat", "-q", prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=timeout, encoding="utf-8",
            )
            response = proc.stdout.strip() or f"(empty, rc={proc.returncode})"
        except subprocess.TimeoutExpired:
            response = "(timeout)"
        except Exception as exc:
            response = f"(error: {exc!r})"

    verdict, detail = judge(rule, response)
    if verdict == "AMBIGUOUS":
        verdict, semantic_detail = semantic_judge(rule, response, timeout=timeout)
        detail = f"{detail} -> semantic: {semantic_detail}"
    return ProbeResult(
        rule_id=rule.id,
        probe=prompt,
        agent_response=response,
        verdict=verdict,
        detail=detail,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def record(user: UserLayer, result: ProbeResult) -> Path:
    out_dir = user.root / "verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = result.timestamp.replace(":", "-")
    out = out_dir / f"{safe_ts}_{result.rule_id}.json"
    out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return out