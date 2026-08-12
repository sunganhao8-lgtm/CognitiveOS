"""Claude Code Adapter — second concrete Adapter 在 CognitiveOS.

Proves Agent-agnostic claim: Claude Code 是 discovered, harvested,
和 probed through 该 相同 interface 作为 Hermes. 无 if-claude special
cases anywhere else 在 该 codebase.

Discovery 注意：
- Claude Code keeps its state under ~/.claude (config, projects,
  history) plus per-project .claude/ 目录们.
- We only harvest 该 SAFE, user-authored subset: CLAUDE.md 文件们
  (project instructions) 和 该 top-level settings. We 从不 harvest
  对话们/raw history (private), credentials, 或 OAuth tokens.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...adapters import Adapter, HarvestResult
from ...discovery import AgentHandle
from ...kernel import Result
from ...paths import Paths


SAFE_GLOB = ("CLAUDE.md", "*.md")


class ClaudeCodeAdapter:
    agent_id = "claude_code"

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
        """Copy CLAUDE.md + settings subset into 来源们/claude_code/."""
        home = self.handle.paths.get("home")
        if home is None:
            return HarvestResult(agent_id=self.agent_id, copied_files=0, notes=["no home path"])

        target = sources_root / "claude_code"
        target.mkdir(parents=True, exist_ok=True)
        copied = 0

        # Top-level config subset: settings.json + CLAUDE.md 在 home
        for name in ("settings.json", "CLAUDE.md"):
            f = home / name
            if f.exists():
                try:
                    shutil.copy2(f, target / name)
                    copied += 1
                except OSError:
                    pass

        # Per-project CLAUDE.md 文件们 discovered via .claude dirs 将
        # 为 a huge 扫描 — skip 在 v0.1, 注意 it.
        notes = [f"harvested from {home} (safe subset only)"]
        if not copied:
            notes.append("no files matched the safe subset")
        return HarvestResult(agent_id=self.agent_id, copied_files=copied, notes=notes)

    def execute(self, task, context) -> Result:
        """v0.1 执行 = shell out 到 `claude -p` (print mode)."""
        prompt = (
            f"You are being invoked as the Claude Code adapter of CognitiveOS.\n"
            f"Task domain: {task.domain}\n"
            f"Task intent: {task.intent}\n"
            f"Respond in 3-6 lines: what would you do, and what files/knowledge would you consult."
        )
        answer = self._claude_query(prompt)
        status = "success" if answer and not answer.startswith("(") else "failed"
        return Result(
            task_id=task.id,
            status=status,
            output=answer or "(no answer from claude)",
            artifacts=[],
        )

    def bootstrap_query(self, prompt: str) -> str | None:
        return self._claude_query(prompt)

    def _claude_query(self, prompt: str) -> str | None:
        import shutil as _sh

        # Claude Code 在 Windows: 该 `claude` shim 是 a .cmd/.ps1 that
        # needs a shell; resolve 该 native binary 直接.
        cli_candidates = [
            Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe",
            Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude",
            Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js",
        ]
        cli = next((c for c in cli_candidates if c.exists()), None)
        if cli is None and _sh.which("claude"):
            cli = Path(_sh.which("claude"))  # fallback: try the shim directly
        if cli is None:
            return "(claude not found: no binary and no claude on PATH)"

        cmd = [str(cli), "-p", prompt, "--output-format", "text"]
        if cli.name.endswith(".js"):
            cmd = ["node", *cmd]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=30, encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            return "(claude timeout after 30s)"
        except Exception as exc:
            return f"(claude error: {exc!r})"
        if proc.returncode != 0:
            return f"(claude rc={proc.returncode}: {(proc.stderr or proc.stdout).strip()[:200]})"
        return proc.stdout.strip() or None