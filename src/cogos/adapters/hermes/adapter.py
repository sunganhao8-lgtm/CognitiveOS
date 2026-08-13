"""Hermes adapter — the first concrete Adapter in CognitiveOS."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ...adapters import Adapter, HarvestResult
from ...discovery import AgentHandle
from ...kernel import Result
from ...paths import Paths


# Files and directories that CognitiveOS does NOT touch.
#
# Rationale: every AI agent already manages its own SOUL / AGENTS /
# MEMORY / USER files at runtime. CognitiveOS does not need to copy,
# index, or "own" those — the agent will read them itself on a new
# machine. What CognitiveOS owns is the *user-level* cognitive state
# that NO agent owns (preferences, project know-how, cross-agent
# decisions, accumulated experience).
#
# So we deliberately exclude the agent's self-managed files.
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
        self.last_error: str = ""

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
        """Mirror the safe subset of Hermes files into ``sources/hermes/``."""
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

        # Per-profile safe subset only. Each profile's state.db, auth.json,
        # sessions/, cache/ etc. are explicitly NOT copied — they are not
        # "knowledge", they are runtime state.
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
        """Execute the task with the assembled CognitiveOS context block.

        Phase 2B fix (was the P0-2 bug): the kernel now passes a bounded
        SYSTEM CONTEXT block (retrieved preferences/rules/memories/skills)
        inside ``context.context_block``, and this adapter actually injects
        it into the agent prompt. The block is budget-capped upstream —
        never dump all memory here.
        """
        block = getattr(context, "context_block", "") or ""
        if block.strip():
            prompt = (
                "[COGNITIVEOS SYSTEM CONTEXT]\n"
                f"{block}\n"
                "[/SYSTEM CONTEXT]\n\n"
                f"[TASK]\n{task.intent}\n\n"
                "Based on the context above, complete the task. "
                "If the context is empty or irrelevant, proceed with common sense."
            )
        else:
            prompt = (
                f"[TASK]\n{task.intent}\n\n"
                "Complete the task."
            )
        answer = self.bootstrap_query(prompt)
        status = "success" if answer else "failed"
        return Result(
            task_id=task.id,
            status=status,
            output=answer or f"(agent error: {self.last_error or 'no response'})",
            artifacts=[],
        )

    def bootstrap_query(self, prompt: str) -> str | None:
        """Actually shell out to ``hermes chat -q`` for v0.1.

        Returns the agent's response, or None on failure (error text is
        stored on ``self.last_error`` so callers can report honestly).
        Bounded by a timeout so a misbehaving agent never hangs the kernel.
        """
        import shutil as _sh

        self.last_error = ""
        if _sh.which("hermes") is None:
            self.last_error = "hermes CLI not on PATH"
            return None

        try:
            proc = subprocess.run(
                [
                    "hermes", "--profile", _isolation_profile(),
                    "chat",
                    "-q", prompt,
                    "-t", "terminal,file",
                    "--max-turns", "1",
                    "-Q",  # quiet: no banner/spinner
                    "--reasoning", "none",  # never surface model-internal reasoning
                ],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
            )
        except subprocess.TimeoutExpired:
            self.last_error = "hermes bootstrap_query timed out after 60s"
            return None
        except Exception as exc:
            self.last_error = f"hermes bootstrap_query failed: {exc!r}"
            return None

        if proc.returncode != 0:
            self.last_error = (proc.stderr or proc.stdout).strip()[:300]
            return None
        from cogos.cli import _clean_hermes_stdout  # single place for stdout normalization (late import: cli is fully loaded at runtime)

        return _clean_hermes_stdout(proc.stdout) or None


def _isolation_profile() -> str:
    """All kernel-driven hermes calls are quarantined in the cogos-test
    profile so machine-initiated runs never pollute the master's session
    list (same policy as cogos.verify)."""
    import os

    return os.environ.get("COGOS_HERMES_PROFILE", "cogos-test")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _copytree(src: Path, dst: Path) -> int:
    """Copy ``src`` tree into ``dst`` skipping symlinks and VCS dirs; return file count."""
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
    """``os.walk`` without following symlinks; skip VCS internals."""
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