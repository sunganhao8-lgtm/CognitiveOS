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


# Default rule pack shipped with CognitiveOS — these come from the
# foundational principles in user/manifest.md.
DEFAULT_RULES: list[Rule] = [
    Rule(
        id="R001",
        rule_en="Never name the chip fabs (上海[REDACTED]/绍兴[REDACTED]); say \"factory-side smart-manufacturing\".",
        rule_zh="简历不写具体公司名（上海[REDACTED]/绍兴[REDACTED]），只说「工厂智能化相关」。",
        probe_en="Write a one-line resume bullet for a CIM engineer who worked at 上海[REDACTED] from 2023 to now.",
        probe_zh="给一位 2023 年至今在上海[REDACTED]担任 CIM 工程师的人写一行简历。",
        expectation_en="The response MUST NOT contain 上海[REDACTED] or 绍兴[REDACTED]. It must say 'factory-side smart-manufacturing' or similar.",
        expectation_zh="回答中不能出现 上海[REDACTED]/绍兴[REDACTED]，必须用「工厂智能化相关」之类的说法。",
        forbidden=("上海[REDACTED]", "绍兴[REDACTED]"),
        required=("工厂智能化",),
    ),
    Rule(
        id="R002",
        rule_en="Always call [REDACTED] a brand — never '线下小店' / '小铺子' / any diminutive.",
        rule_zh="叫「品牌叫[REDACTED]」，禁止「线下小店」之类的小称谓。",
        probe_en="Write a marketing pitch for the [REDACTED] store opening. Keep it short.",
        probe_zh="为「[REDACTED]」的开业写一段宣传文案，简短。",
        expectation_en="The response MUST NOT contain 线下小店 / 小铺子 / 杂货铺 / 小本生意. It must frame [REDACTED] as a brand.",
        expectation_zh="回答中不能出现 线下小店 / 小铺子 / 杂货铺 / 小本生意，必须把「[REDACTED]」当作品牌。",
        forbidden=("线下小店", "小铺子", "杂货铺", "小本生意"),
        required=("[REDACTED]", "品牌"),
    ),
    Rule(
        id="R003",
        rule_en="AI is positioned as the core lever — never 'just a tool' or 'assistant only'.",
        rule_zh="AI 是核心杠杆，绝不降级为「只是个工具」「只是助手」。",
        probe_en="Describe the role of AI in the [REDACTED] business model.",
        probe_zh="描述 AI 在「[REDACTED]」商业模式里的角色。",
        expectation_en="The response MUST NOT contain '只是个工具' / '只是助手' / '工具而已'. AI must be framed as a core lever / 核心杠杆.",
        expectation_zh="回答中不能出现「只是个工具」「只是助手」之类降级说法，AI 必须被描述为核心杠杆。",
        forbidden=("只是个工具", "只是助手", "工具而已"),
        required=("核心",),
    ),
]


def load_rules(user: UserLayer) -> list[Rule]:
    """Load rules from user/rules/*.json, fall back to defaults."""
    rules_dir = user.root / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
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
    return found or DEFAULT_RULES


def seed_default_rules(user: UserLayer) -> int:
    """Write DEFAULT_RULES to disk the first time so they are reviewable."""
    rules_dir = user.root / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for rule in DEFAULT_RULES:
        path = rules_dir / f"{rule.id}.json"
        if not path.exists():
            path.write_text(json.dumps(asdict(rule), ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
    return n


def judge(rule: Rule, response: str) -> tuple[str, str]:
    """Return (verdict, detail). verdict is "PASS" or "FAIL"."""
    lower = response
    for word in rule.forbidden:
        if word and word in lower:
            return ("FAIL", f"forbidden phrase found: {word!r}")
    if rule.required:
        missing = [w for w in rule.required if w not in lower]
        if missing:
            return ("FAIL", f"required phrase missing: {missing}")
    return ("PASS", "OK")


def run_one(rule: Rule, *, lang: str = "zh", timeout: int = 60) -> ProbeResult:
    """Run one rule's probe against the installed Agent."""
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