"""Hermes Adapter — 第一个 concrete Adapter 在 CognitiveOS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...adapters import Adapter, HarvestResult
from ...discovery import AgentHandle
from ...kernel import Result
from ...paths import Paths


# 文件们 和 目录们 that CognitiveOS 做 不 touch.
# 
# Rationale: 每个 AI Agent already manages its own SOUL / Agents /
# 记忆 / USER 文件们 在 runtime. CognitiveOS 做 不 need 到 copy,
# index, 或 "own" those — Agent 将 读取 them itself 在 a 新
# machine. What CognitiveOS owns 是 该 *user-level* cognitive state
# that 无 Agent owns (preferences, project know-how, cross-Agent
# decisions, accumulated experience).
# 
# So we deliberately exclude Agent's self-managed 文件们.
EXCLUDE_TOP_LEVEL = (
    "SOUL.md",      # agent self-description
    "AGENTS.md",    # agent self-instructions
    "IDENTITY.md",  # agent identity
    "USER.md",      # agent's per-user preferences (duplicate of cogos user/)
)

SAFE_TOP_LEVEL = ("skills",)
SAFE_PROFILE_FILES = ()  # v0.2+ will define a USER-only whitelist


class HermesAdapter:
    agent_id = "hermes"

    def __init__(self, handle: AgentHandle) -> None:
        self.handle = handle

    # ---- introspection -----------------------------------------------------

    def describe(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "display_name": self.handle.display_name,
            "paths": {k: str(v) for k, v in self.handle.paths.items()},
            "notes": list(self.handle.notes),
        }

    # ---- harvest ------------------------------------------------------------

    def harvest(self, sources_root: Path) -> HarvestResult:
        """Mirror 该 safe subset 的 Hermes 文件们 into ``来源们/hermes/``."""
        home = self.handle.paths.get("home")
        if home is None:
            return HarvestResult(agent_id=self.agent_id, copied_files=0, notes=["no home path"])

        target = sources_root / "hermes"
        target.mkdir(parents=True, exist_ok=True)

        copied = 0
        for entry in SAFE_TOP_LEVEL:
            src = home / entry
            if not src.exists():
                continue
            dst = target / entry
            if src.is_dir():
                copied += _copytree(src, dst)
            else:
                shutil.copy2(src, dst)
                copied += 1

        # Per-profile safe subset only. 每个 profile's state.db, auth.json,
        # sessions/, cache/ 等等. 是 explicitly 不 copied — they 是 不
        # "knowledge", they 是 runtime state.
        profiles_src = home / "profiles"
        if profiles_src.exists():
            dst_profiles = target / "profiles"
            dst_profiles.mkdir(parents=True, exist_ok=True)
            for profile in sorted(profiles_src.iterdir()):
                if not profile.is_dir():
                    continue
                prof_dst = dst_profiles / profile.name
                prof_dst.mkdir(parents=True, exist_ok=True)
                for fname in SAFE_PROFILE_FILES:
                    f = profile / fname
                    if f.exists():
                        shutil.copy2(f, prof_dst / fname)
                        copied += 1

        return HarvestResult(
            agent_id=self.agent_id,
            copied_files=copied,
            notes=[f"harvested from {home}"],
        )

    # ---- Kernel execution ---------------------------------------------------

    def execute(self, task, context) -> Result:
        """v0.1 执行 = shell out 到 ``hermes chat -q`` 使用 任务 intent.

        返回 raw text 来自 Hermes 作为 结果 output. Timeout 是
        bounded so 该 kernel 从不 hangs.
        """
        prompt = (
            f"You are being invoked as the Hermes bootstrap agent of CognitiveOS.\n"
            f"Task domain: {task.domain}\n"
            f"Task intent: {task.intent}\n"
            f"Required memory keys: {', '.join(task.required_memory) or '(none)'}\n"
            f"Respond in 3-6 lines: what would you do, and what files/knowledge would you consult."
        )
        answer = self.bootstrap_query(prompt)
        status = "success" if answer else "failed"
        return Result(
            task_id=task.id,
            status=status,
            output=answer or "(no answer from hermes)",
            artifacts=[],
        )

    def bootstrap_query(self, prompt: str) -> str | None:
        """Actually shell out 到 ``hermes chat -q`` 用于 v0.1.

        返回 Agent's response, 或 None if Hermes 是 不 在 路径 或
        该 call fails. Bounded 通过 a timeout so a misbehaving Agent 从不
        hangs 该 kernel.
        """
        import shutil as _sh

        if _sh.which("hermes") is None:
            return None

        try:
            proc = subprocess.run(
                [
                    "hermes", "chat",
                    "-q", prompt,
                    "-t", "terminal,file",
                    "--max-turns", "1",
                    "-Q",  # quiet: no banner/spinner
                ],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            return "(hermes bootstrap_query timed out after 60s)"
        except Exception as exc:
            return f"(hermes bootstrap_query failed: {exc!r})"

        if proc.returncode != 0:
            return f"(hermes returned {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]})"
        return proc.stdout.strip()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _copytree(src: Path, dst: Path) -> int:
    """Copy ``src`` tree into ``dst`` skipping symlinks 和 VCS dirs; 返回 文件 count."""
    count = 0
    for root, dirs, files in _walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copy2(Path(root) / name, out_dir / name)
            count += 1
    return count


def _walk(src: Path):
    """``os.walk`` 不使用 following symlinks; skip VCS internals."""
    import os

    for root, dirs, files in os.walk(src, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if d != ".git" and not _is_broken_symlink(Path(root) / d)
        ]
        yield root, dirs, files


def _is_broken_symlink(p: Path) -> bool:
    try:
        return p.is_symlink() and not p.exists()
    except OSError:
        return True