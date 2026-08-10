"""Hermes adapter — the first concrete Adapter in CognitiveOS."""

from __future__ import annotations

import shutil
from pathlib import Path

from ...adapters import Adapter, HarvestResult
from ...discovery import AgentHandle
from ...paths import Paths


# Files and directories that are safe to copy verbatim from a Hermes home.
# Anything not on this list stays on the original disk. Cache, auth.json,
# state.db, sessions, logs etc. are deliberately excluded.
SAFE_TOP_LEVEL = ("skills", "AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md")
SAFE_PROFILE_FILES = (
    "config.yaml",
    "SOUL.md",
    "AGENTS.md",
    "MEMORY.md",
    "USER.md",
)


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

    # ---- bootstrap ----------------------------------------------------------

    def bootstrap_query(self, paths: Paths) -> str | None:
        """Hermes exposes its state through files, not an API.

        v0.1 returns None — CognitiveOS synthesises the bootstrap summary
        from the harvested files itself. A future version could shell out
        to ``hermes chat -q`` to get a richer, agent-authored summary.
        """
        return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _copytree(src: Path, dst: Path) -> int:
    """Copy ``src`` tree into ``dst`` skipping symlinks; return file count."""
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
    """``os.walk`` without following symlinks."""
    import os

    for root, dirs, files in os.walk(src, followlinks=False):
        dirs[:] = [d for d in dirs if not _is_broken_symlink(Path(root) / d)]
        yield root, dirs, files


def _is_broken_symlink(p: Path) -> bool:
    try:
        return p.is_symlink() and not p.exists()
    except OSError:
        return True