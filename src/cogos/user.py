"""User-level cognitive state.

This module owns the *user* layer of CognitiveOS — the cognitive state
that lives ABOVE any individual AI agent. It is what the user carries
across machines and across agent products.

Three properties that make this layer genuinely different from any
agent's own memory:

1. **Agent-agnostic.** No file in here is read by an agent at runtime.
   It is not "Hermes's memory" — it is the user's memory.
2. **Portable.** Drop ``cogos/user/`` onto another machine (or a USB)
   and the same preferences, projects, and experience go with you.
3. **Authored by the user.** Every file in here is either written by the
   user directly, or written by a tool on the user's explicit request.
   No silent auto-mutation.

The layer is laid out as a wiki-style directory because that is what
the user can read, edit, and grep directly. No database, no opaque blob.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UserLayer:
    """Filesystem layout of the user-level cognitive state."""

    root: Path

    @classmethod
    def default(cls) -> "UserLayer":
        # ``user/`` lives inside the CognitiveOS project root so a single
        # ``git clone`` (or rsync) carries it. v0.2+ may move it to
        # ~/.cognitiveos/user to make it independent of any one project.
        return cls(root=Path.cwd().resolve() / "user")

    @property
    def preferences(self) -> Path:
        return self.root / "preferences.md"

    @property
    def style(self) -> Path:
        return self.root / "style.md"

    @property
    def projects(self) -> Path:
        return self.root / "projects"

    @property
    def experience(self) -> Path:
        return self.root / "experience"

    @property
    def cognitive(self) -> Path:
        return self.root / "cognitive"

    def ensure(self) -> None:
        for p in (self.root, self.projects, self.experience, self.cognitive):
            p.mkdir(parents=True, exist_ok=True)