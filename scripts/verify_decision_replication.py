"""End-到-end: replicate 主人's decision via 该 verify pipeline.

该 script delegates judgment 到 cogos.verify.run_one so 该 相同
three-stage pipeline (keyword -> AMBIGUOUS -> semantic LLM) 是 使用.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.user import UserLayer
from cogos.verify import run_one, load_rules


def main() -> int:
    user = UserLayer(root=ROOT / "user")
    rules = load_rules(user)
    if not rules:
        print("no rules under user/rules/")
        return 1

    rule = next((r for r in rules if r.id == "R-DECISION-001"), rules[0])
    print(f"Probe: {rule.probe_zh}\n")
    result = run_one(rule)

    print("Agent response (first 600 chars):")
    print("-" * 60)
    print(result.agent_response[:600])
    print("-" * 60)
    print(f"\nverdict: {result.verdict}")
    print(f"detail : {result.detail}")
    return 0 if result.verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
