"""Tests for cogos.verify — judge logic and seed behaviour."""

import pytest

from cogos.verify import Rule, judge, GENERATED_RULES, load_rules
from cogos.user import UserLayer


def _rule(**overrides):
    base = dict(
        id="T001",
        rule_en="test",
        rule_zh="测试",
        probe_en="probe",
        probe_zh="探测",
        expectation_en="expect",
        expectation_zh="预期",
        forbidden=(),
        required=(),
    )
    base.update(overrides)
    return Rule(**base)


def test_judge_passes_when_neither_forbidden_nor_required():
    r = _rule()
    assert judge(r, "any text") == ("PASS", "OK")


def test_judge_fails_on_forbidden():
    r = _rule(forbidden=("ACME-Fab",))
    verdict, detail = judge(r, "I worked at ACME-Fab")
    assert verdict == "FAIL"
    assert "ACME-Fab" in detail


def test_judge_returns_ambiguous_when_required_phrase_missing():
    """Soft-required: missing alone is not a FAIL — the response might satisfy
    the rule via synonyms. Mark AMBIGUOUS so the caller escalates to the
    semantic judge. Only a literal forbidden hit is a hard FAIL."""
    r = _rule(required=("芯片制造",))
    verdict, detail = judge(r, "I worked in chip fabrication")
    assert verdict == "AMBIGUOUS"
    assert "芯片制造" in detail


def test_judge_forbidden_takes_priority_over_required():
    """If both fail, forbidden wins (most damning verdict)."""
    r = _rule(forbidden=("X",), required=("Y",))
    verdict, _ = judge(r, "X present, Y missing")
    assert verdict == "FAIL"


def test_generated_rules_are_demographic_safe():
    """The shipped placeholder rules must NEVER contain real master data.

    This is the canary that protects against accidentally inlining
    personal iron rules into the public package.

    Two layers:
    1. Structural (public): every GENERATED_RULES entry is a clearly-marked
       placeholder (DEMO- id + （示例） prefix).
    2. Substantive (local): if the LOCAL, gitignored pattern file
       .cogos/sensitive_patterns.json exists, its patterns must not match.
       The real master terms never ship with the repo — they live only in
       that local file, so the public package cannot leak them by accident.
    """
    import json
    import re
    from pathlib import Path

    blob = "\n".join([r.rule_en + r.rule_zh + r.probe_en + r.probe_zh
                       for r in GENERATED_RULES])

    # Layer 1 — structural canary (ships with the repo).
    for r in GENERATED_RULES:
        assert r.id.startswith("DEMO-"), f"placeholder id must start with DEMO-: {r.id}"
        assert r.rule_zh.startswith("（示例）"), f"placeholder must be marked （示例）: {r.rule_zh}"

    # Layer 2 — local substantive canary (patterns never shipped).
    patterns_file = Path(__file__).resolve().parent.parent / ".cogos" / "sensitive_patterns.json"
    if patterns_file.exists():
        try:
            local_patterns = json.loads(patterns_file.read_text(encoding="utf-8"))
        except Exception:
            local_patterns = []
        for pat in local_patterns:
            assert not re.search(pat, blob), f"GENERATED_RULES leak: {pat}"


def test_load_rules_returns_empty_when_dir_missing(tmp_path):
    user = UserLayer(root=tmp_path / "user")
    assert load_rules(user) == []


def test_load_rules_returns_empty_when_dir_empty(tmp_path):
    (tmp_path / "user" / "rules").mkdir(parents=True)
    user = UserLayer(root=tmp_path / "user")
    assert load_rules(user) == []