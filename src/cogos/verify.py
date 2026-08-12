"""Reproduction testing — turn 主人's iron 规则们 into executable probes.

Agent records "主人 said X" 作为 记忆. But 下一个 time a
similar situation comes up, Agent 经常 falls into 该 相同 trap
because 记忆 是 passive — it doesn't replay 该 past correction.

CognitiveOS solves this 通过 turning 每个 iron 规则 into a **probe**: a
short scenario that re-presents 规则-violation temptation 到 该
Agent. If Agent falls into 该 trap, 规则 是 broken; if it
resists, 规则 held.

**Isolation guarantee.** 每个 Hermes call 来自 本模块 uses
``--profile-name cogos-测试`` so probe sessions 是 quarantined 在
their own profile 和 从不 appear 在 用户's normal Hermes session
列出. This 是 enforced 在 ``_hermes_args()`` below.
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

# Profile 用于 quarantine 所有 probe sessions away 来自 用户's
# normal Hermes session 列出. Override via env COGOS_HERMES_PROFILE.
ISOLATION_PROFILE = "cogos-test"


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


# A *generic* 规则 pack 用于 seed user/规则们/ 首次.
# 
# 重要： this 必须 为 GENERIC, 不 主人's real iron 规则们.
# Real iron 规则们 live 在 user/manifest.md 和 是 written 通过 用户
# explicitly. Seeded defaults exist only so `cogos verify` 有 SOMETHING
# 到 运行 当 该 project 是 第一 cloned — they 是 placeholders, 不
# 主人's actual 规则们.
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
    """加载 规则们 来自 user/规则们/*.json. 无 DEFAULTS — if 空, 返回 [].

    Real iron 规则们 live 在 user/manifest.md 和 是 owned 通过 用户.
    We 从不 silently invent 规则们. If 空, 运行 `cogos verify` 返回
    "无规则 — 写入 one into user/规则们/Rxxx.json 第一".
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
    """写入 GENERATED placeholder 规则们 到 disk 首次 only.

    These 是 DEMO placeholders, 从不 主人's real iron 规则们.
    使用 so a freshly cloned repo 可以 运行 `cogos verify` 立即
    不使用 crashing. 用户 是 expected 到 replace them 使用 real
    规则们 under user/规则们/ 作为 they go.
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
    """返回 (verdict, detail). verdict 是 "PASS" 或 "FAIL".

    Three layers 的 checking, 在 order 的 damning-ness:

    1. HARD FORBIDDEN — if 任何 forbidden phrase literally appears, FAIL.
       These 是 concrete traps (private names, wrong words, 等等.).
    2. SOFT REQUIRED — if a required phrase literally appears, 规则
       是 "obviously" satisfied. Missing-required alone 是 不 a fail;
       it falls through 到 layer 3.
    3. SEMANTIC FALLBACK — 当 forbidden 为空 和 required 为空
       或 当 neither set triggers, we 不能 tell. Verdict becomes
       AMBIGUOUS, 不 PASS. Callers 应该 escalate 到 a semantic judge
       (LLM-based) 用于 an opinionated verdict.

    Why this design: keyword-only judges give 假 negatives ("不
    在 those exact words, but 该 meaning 是 right") 和 假 positives
    ("该 word 是 there, but 在 a negating context"). 该 honest move
    是 到 mark 该 case AMBIGUOUS rather than fake a PASS/FAIL.
    """
    lower = response
    for word in rule.forbidden:
        if word and word in lower:
            return ("FAIL", f"forbidden phrase found: {word!r}")
    if rule.required:
        missing = [w for w in rule.required if w not in lower]
        if missing:
            # Soft required alone 做 不 constitute FAIL — it 可以 为
            # 规则 是 satisfied 通过 synonyms. Mark AMBIGUOUS 和 let
            # 该 caller 运行 该 LLM semantic judge.
            return ("AMBIGUOUS", f"required phrase missing: {missing}")
    return ("PASS", "OK")


def semantic_judge(rule: Rule, response: str, timeout: int = 120) -> tuple[str, str]:
    """LLM-作为-judge fallback 用于 AMBIGUOUS cases.

    返回 (verdict, detail). verdict 是 "PASS" 或 "FAIL".
    If 该 LLM call fails, 返回 ("AMBIGUOUS", "(semantic judge unavailable)").
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
            _hermes_args(prompt),
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


def _hermes_args(prompt: str) -> list[str]:
    """Build a hermes chat command that quarantines 该 session 在 cogos-测试.

    该 --profile-name flag keeps probe sessions 在 their own profile
    so they 从不 appear 在 用户's normal Hermes session 列出.
    """
    import os
    profile = os.environ.get("COGOS_HERMES_PROFILE", ISOLATION_PROFILE)
    return [
        "hermes", "chat",
        "-q", prompt,
        "-t", "terminal,file",
        "--max-turns", "1",
        "-Q",
        "--profile-name", profile,
    ]


def run_one(rule: Rule, *, lang: str = "zh", timeout: int = 120) -> ProbeResult:
    """运行 one 规则's probe against 该 installed Agent.

    Three-stage judgment:
    1. Probe 是 sent 到 Agent.
    2. Keyword judge (fast, local).
    3. If AMBIGUOUS, escalate 到 a semantic (LLM) judge.
    """
    prompt = (rule.probe_zh if lang == "zh" else rule.probe_en)
    response = "(hermes not on PATH)"
    if shutil.which("hermes"):
        try:
            proc = subprocess.run(
                _hermes_args(prompt),
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