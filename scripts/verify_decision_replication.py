"""End-to-end: replicate the master's decision via the verify pipeline.

The script delegates judgment to cogos.verify.run_one so the same
three-stage pipeline (keyword -> AMBIGUOUS -> semantic LLM) is used.
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
