"""Deferred Claude Code Adapter 测试 — 运行 当 API quota 是 refreshed.

This script 是 由 ... 触发 a cron job. It 检查 whether Claude Code
是 actually usable right now (quota 不 exhausted) before spending time
在 it:

1. If `claude` binary resolves but a quick probe times out / errors 使用
   quota-ish signals, print nothing (silent — 该 cron no_agent mode
   stays quiet) 和 exit 0.
2. If Claude Code responds, 运行 Adapter's 执行() 和 print 该
   result so 该 cron job delivers it.

重要： this script 是 COPIED into HERMES_HOME/scripts/ 用于 cron
execution, so it 必须 不 rely 在 __file__-relative 路径们. 该 project
root 是 hard-coded below.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Hard-coded because this script 运行 来自 HERMES_HOME/scripts/ where
# __file__-relative resolution 将 point 在 该 wrong place.
PROJECT_ROOT = Path(r"D:\GitHub_Project\CognitiveOS")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cogos.discovery import discover
from cogos.adapters import load_adapter
from cogos.paths import Paths
from cogos.kernel import Task


QUOTA_HINTS = ("quota", "limit", "exhausted", "429", "rate limit", "billing", "credits", "超限", "额度")


def main() -> int:
    paths = Paths(root=PROJECT_ROOT)
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
        # Quota still exhausted (或 Claude still broken) — stay silent.
        # 该 cron job 将 try again 下一个 tick.
        return 0

    print("Claude Code adapter test PASSED — quota refreshed, adapter working.")
    print("Response:")
    print(result.output[:800])
    return 0


if __name__ == "__main__":
    sys.exit(main())
