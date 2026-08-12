"""Codex Adapter — third concrete Adapter 在 CognitiveOS.

Codex 是 OpenAI's Agent CLI (codex-cli). It stores its config under
~/.codex/. We harvest 该 SAFE subset (config.toml) 和 执行 via
`codex exec` (non-interactive) so CognitiveOS 可以 route 任务们 到 it
精确地 like it routes 到 Hermes / Claude Code.

Safe-subset principle: we 从不 harvest 对话 history, OAuth
tokens, 或 auth.json.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...adapters import Adapter, HarvestResult
from ...discovery import AgentHandle
from ...kernel import Result
from ...paths import Paths


SAFE_FILES = ("config.toml", "config.yaml", "config.json")


class CodexAdapter:
    agent_id = "codex"

    def __init__(self, handle: AgentHandle) -> None:
        self.handle = handle

    def describe(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "display_name": self.handle.display_name,
            "paths": {k: str(v) for k, v in self.handle.paths.items()},
            "notes": list(self.handle.notes),
        }

    def harvest(self, sources_root: Path) -> HarvestResult:
        home = self.handle.paths.get("home")
        if home is None:
            return HarvestResult(agent_id=self.agent_id, copied_files=0, notes=["no home path"])

        target = sources_root / "codex"
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for name in SAFE_FILES:
            f = home / name
            if f.exists():
                try:
                    shutil.copy2(f, target / name)
                    copied += 1
                except OSError:
                    pass
        return HarvestResult(
            agent_id=self.agent_id,
            copied_files=copied,
            notes=[f"harvested from {home} (safe subset)"],
        )

    def execute(self, task, context) -> Result:
        """v0.1 执行 = shell out 到 `codex exec`."""
        prompt = (
            f"Task domain: {task.domain}\n"
            f"Task intent: {task.intent}\n"
            f"Respond in 3-6 lines: what would you do, and what files/knowledge would you consult."
        )
        answer = self._codex_query(prompt)
        status = "success" if answer and not answer.startswith("(") else "failed"
        return Result(
            task_id=task.id,
            status=status,
            output=answer or "(no answer from codex)",
            artifacts=[],
        )

    def bootstrap_query(self, prompt: str) -> str | None:
        return self._codex_query(prompt)

    def _codex_query(self, prompt: str) -> str | None:
        import shutil as _sh

        cli = _sh.which("codex")
        if cli is None:
            return "(codex not on PATH)"
        try:
            proc = subprocess.run(
                [
                    cli, "exec",
                    "--skip-git-repo-check",
                    "--sandbox", "read-only",
                    "--",
                    prompt,
                ],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
                stdin=subprocess.DEVNULL,  # critical: close stdin so codex doesn't wait
            )
        except subprocess.TimeoutExpired:
            return "(codex timeout after 120s)"
        except Exception as exc:
            return f"(codex error: {exc!r})"
        if proc.returncode != 0:
            return f"(codex rc={proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]})"
        return proc.stdout.strip() or None