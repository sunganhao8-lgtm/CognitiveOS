"""Intent classification — the Observe step of the runtime loop.

Three stages (same philosophy as verify's judgement):

1. keyword  — deterministic regex patterns (free, local)
2. AMBIGUOUS — honest answer when patterns don't fire
3. llm      — one semantic classification call (JSON reply)

Also turns rule statements into structured verify-schema rules, with a
deterministic pattern fallback so the Golden Path works even when the
LLM is unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

#: Cheap rule-statement markers. "以后…", "记住…", "永远不要…" etc.
RULE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^(以后|从现在起|今后|记住|请记住|永远|永远不要|别再|不要再|不要再用|不允许再)"),
    re.compile(r"^我的[^\n]{0,30}(要|不要|别|不能|必须|禁止|不允许|不写|统一)"),
    # temporary-scoped rule statements — rule mode but NEVER permanent
    re.compile(r"^(今天|这次|本次|暂时|临时)"),
)

#: Explicit escape hatch: a "规则:" prefix forces rule mode.
FORCE_RULE = re.compile(r"^\s*规则[:：]")

#: Task-scoped exception markers — "今天/这次/暂时" statements must NEVER
#: form permanent cognition (Phase 3A minimal temporary support).
TEMPORARY_MARKERS = re.compile(r"(今天|这次|暂时|临时|仅这次|就这一次|本次)")

#: Project-scope markers — "这个项目/本项目/在X项目里" narrows a statement
#: to a project instead of global scope (Phase 3B scope model).
PROJECT_SCOPE_RE = re.compile(r"(这个项目|本项目|在我们项目|在项目里|项目里|该项目的)")

#: Project name capture: "在 <name> 项目里" / "<name> 项目以后…"
PROJECT_NAME_RE = re.compile(r"(?:在|对|给)?([\u4e00-\u9fffA-Za-z0-9]{2,20}?)项目(?:里|中|以后|中以后)?")


def detect_scope(text: str) -> tuple[str, str]:
    """(scope, scope_id) from a user statement — deterministic.

    "这个项目…" → project scope (id = "current" placeholder, refined by
    caller); temporary markers → temporary scope. Default global.
    """
    if TEMPORARY_MARKERS.search(text):
        return ("temporary", "")
    if PROJECT_SCOPE_RE.search(text):
        m = PROJECT_NAME_RE.search(text)
        name = m.group(1) if m else ""
        return ("project", name.strip() or "current")
    return ("global", "")

#: "不允许 X" / "不要 X" / "别用 X" — deterministic forbidden extraction.
FORBIDDEN_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?:不允许|不允许再|禁止|不要再用|不要再|不要用|不要|别用|别)\s*([^，。；,.;\n]+)"),
    re.compile(r"(?:不写|不出现|必须避免)\s*([^，。；,.;\n]+)"),
)

#: "必须 X" / "都要 X" — deterministic required extraction.
REQUIRED_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?:必须|都要|统一用|统一使用|一律)\s*([^，。；,.;\n]+)"),
)

#: "允许 X" / "可以用 X" — deterministic allowed extraction (temporary
#: exceptions carry these; they override rules whose forbidden matches).
ALLOW_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?:允许|可以用|能用|可以)\s*(?:使用|用)?\s*([^，。；,.;\n]+)"),
)


def extract_allows(text: str) -> list[str]:
    """Deterministic extraction of what a statement permits (temporary use)."""
    out: list[str] = []
    for pat in ALLOW_PATTERNS:
        for m in pat.finditer(text):
            token = _clean_token(m.group(1))
            if token and token not in out:
                out.append(token)
    return out

DOMAIN_HINTS: dict[str, str] = {
    "sql": "sql",
    "报表": "reporting",
    "代码": "coding",
    "文案": "writing",
    "python": "coding",
    "简历": "resume",
    "查询": "sql",
}


@dataclass
class Intent:
    type: str  # "rule" | "task"
    domain: str = "general"
    method: str = "keyword"  # keyword | llm | fallback
    confidence: float = 1.0
    temporary: bool = False  # task-scoped exception, never promoted
    scope: str = "global"    # global | project | task | temporary
    scope_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleDraft:
    rule_zh: str
    rule_en: str = ""
    probe_zh: str = ""
    probe_en: str = ""
    expectation_zh: str = ""
    expectation_en: str = ""
    forbidden: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    domain: str = "general"
    method: str = "llm"  # llm | pattern | raw

    def to_dict(self) -> dict:
        return asdict(self)


def classify_intent(text: str, llm_fn=None) -> Intent:
    """Classify ``text`` as a rule statement or a task.

    ``llm_fn(prompt) -> str|None`` is an optional semantic classifier used
    only when the keyword stage is AMBIGUOUS. Without it, AMBIGUOUS falls
    back to "task" — the honest default, recorded as method=fallback.
    """
    t = text.strip()
    temporary = bool(TEMPORARY_MARKERS.search(t))
    scope, scope_id = detect_scope(t)
    if temporary:
        scope, scope_id = "temporary", ""
    if FORCE_RULE.search(t):
        return Intent(type="rule", domain=_domain_hint(t), method="keyword",
                      temporary=temporary, scope=scope, scope_id=scope_id)
    for pat in RULE_PATTERNS:
        if pat.search(t):
            return Intent(type="rule", domain=_domain_hint(t), method="keyword",
                          temporary=temporary, scope=scope, scope_id=scope_id)

    if llm_fn is None:
        return Intent(type="task", domain=_domain_hint(t), method="fallback", confidence=0.6,
                      temporary=temporary, scope=scope, scope_id=scope_id)

    prompt = (
        'Classify this user message. Reply with ONLY JSON: '
        '{"type": "rule" or "task", "domain": "short english domain word or general"}\n\n'
        f"Message: {t[:500]}\n\n"
        'A "rule" is a standing preference/instruction the user wants remembered '
        '(e.g. "以后不要用 SELECT *"). A "task" is a request to do something.'
    )
    try:
        raw = llm_fn(prompt)
        if raw:
            m = re.search(r"\{[^{}]*\}", raw)
            if m:
                rec = json.loads(m.group(0))
                itype = str(rec.get("type", "task")).lower()
                if itype in ("rule", "task"):
                    return Intent(
                        type=itype,
                        domain=str(rec.get("domain") or _domain_hint(t)),
                        method="llm",
                        confidence=0.9,
                    )
    except Exception:
        pass
    return Intent(type="task", domain=_domain_hint(t), method="fallback", confidence=0.6)


def _domain_hint(text: str) -> str:
    low = text.lower()
    for hint, domain in DOMAIN_HINTS.items():
        if hint in low:
            return domain
    return "general"


def extract_rule(text: str, llm_fn=None) -> RuleDraft:
    """Turn a rule statement into a structured verify-schema RuleDraft.

    Priority: LLM structured extraction -> deterministic pattern fallback
    -> raw text (no patterns). The fallback keeps the Golden Path working
    without an LLM, extracting "不允许 X" into forbidden=[X] directly from
    the user's own words.
    """
    t = text.strip()

    if llm_fn is not None:
        prompt = (
            "Extract a structured rule from this user statement.\n"
            "Reply with ONLY JSON:\n"
            '{"rule_zh": "the rule in Chinese", "rule_en": "the rule in English", '
            '"domain": "short english domain word", '
            '"forbidden": ["exact strings that must NOT appear", ...], '
            '"required": ["exact strings that MUST appear", ...]}\n\n'
            f"Statement: {t[:500]}"
        )
        try:
            raw = llm_fn(prompt)
            if raw:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    rec = json.loads(m.group(0))
                    if rec.get("rule_zh"):
                        return RuleDraft(
                            rule_zh=str(rec["rule_zh"]),
                            rule_en=str(rec.get("rule_en", "")),
                            domain=str(rec.get("domain") or _domain_hint(t)),
                            forbidden=tuple(str(x) for x in rec.get("forbidden", ())),
                            required=tuple(str(x) for x in rec.get("required", ())),
                            method="llm",
                        )
        except Exception:
            pass

    forbidden: list[str] = []
    required: list[str] = []
    for pat in FORBIDDEN_PATTERNS:
        for m in pat.finditer(t):
            token = _clean_token(m.group(1))
            if token and token not in forbidden:
                forbidden.append(token)
    for pat in REQUIRED_PATTERNS:
        for m in pat.finditer(t):
            token = _clean_token(m.group(1))
            if token and token not in required:
                required.append(token)

    if forbidden or required:
        return RuleDraft(
            rule_zh=t,
            domain=_domain_hint(t),
            forbidden=tuple(forbidden),
            required=tuple(required),
            method="pattern",
        )

    return RuleDraft(rule_zh=t, domain=_domain_hint(t), method="raw")


def _clean_token(token: str) -> str:
    t = token.strip().strip("。；;，,、\"'“”‘’()（）[]【】")
    t = re.sub(r"^(使用|用|出现|写|提到|包含|讲|说)\s*", "", t)
    t = re.sub(r"(等|之类|这种|这些)$", "", t)
    return t.strip()


DOMAIN_SHORT = {
    "general": "GEN",
    "sql": "SQL",
    "coding": "COD",
    "reporting": "RPT",
    "writing": "WRT",
    "resume": "RES",
}


def next_rule_id(rules_dir, domain: str = "GEN") -> str:
    """Next rule id for a domain: R-<DOMAIN>-NNN (e.g. R-SQL-001)."""
    from pathlib import Path

    dom = DOMAIN_SHORT.get((domain or "gen").lower(), None)
    if dom is None:
        dom = re.sub(r"[^A-Z0-9]", "", (domain or "GEN").upper())[:12] or "GEN"
    rules_dir = Path(rules_dir)
    max_n = 0
    if rules_dir.exists():
        for p in rules_dir.glob(f"R-{dom}-*.json"):
            m = re.match(rf"R-{dom}-(\d+)", p.stem)
            if m:
                max_n = max(max_n, int(m.group(1)))
    return f"R-{dom}-{max_n + 1:03d}"
