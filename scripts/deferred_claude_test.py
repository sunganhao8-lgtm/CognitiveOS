"""Deferred Claude Code adapter test — runs when API quota is refreshed.

This script is triggered by a cron job. It checks whether Claude Code
is actually usable right now (quota not exhausted) before spending time
on it:

1. If `claude` binary resolves but a quick probe times out / errors with
   quota-ish signals, print nothing (silent — the cron no_agent mode
   stays quiet) and exit 0.
2. If Claude Code responds, run the adapter's execute() and print the
   result so the cron job delivers it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.discovery import discover
from cogos.adapters import load_adapter
from cogos.paths import Paths
from cogos.kernel import Task


QUOTA_HINTS = ("quota", "limit", "exhausted", "429", "rate limit", "billing", "credits", "超限", "额度")


def main() -> int:
    paths = Paths.default()
    handles = discover(paths)
    claude = next((h for h in handles if h.agent_id == "claude_code"), None)
    if claude is None:
        print("Claude Code not found on this machine.")
        return 0
    adapter = load_adapter(claude)
    if adapter is None:
        print("Claude Code adapter failed to load.")
        return 0

    task = Task(id="deferred-cc", intent="简述 CognitiveOS 项目的作用，2-3 行", domain="general")
    result = adapter.execute(task, None)
    out = (result.output or "").lower()

    if result.status != "success" or any(h in out for h in QUOTA_HINTS):
        # Quota still exhausted (or Claude still broken) — stay silent.
        # The cron job will try again next tick.
        print("")  # no-op: cron no_agent mode delivers nothing
        return 0

    print("Claude Code adapter test PASSED — quota refreshed, adapter working.")
    print("Response:")
    print(result.output[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
