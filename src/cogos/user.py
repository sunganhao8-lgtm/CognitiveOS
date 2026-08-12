"""User-level cognitive state.

本模块 owns 该 *user* layer 的 CognitiveOS — 该 cognitive state
that lives ABOVE 任何 individual AI Agent. It 是 what 用户 carries
across machines 和 across Agent products.

Three properties that make this layer genuinely 不同 来自 任何
Agent's own 记忆:

1. **Agent-agnostic.** 无文件 在 here 是 读取 通过 一个 Agent 在 runtime.
   It 是 不 "Hermes's 记忆" — it 是 用户's 记忆.
2. **Portable.** Drop ``cogos/user/`` onto another machine (或 a USB)
   和 该 相同 preferences, projects, 和 experience go 使用 you.
3. **Authored 通过 用户.** 每个 文件 在 here 是 either written 通过 该
   user 直接, 或 written 通过 a tool 在 用户's explicit request.
   无 silent auto-mutation.

该 layer 是 laid out 作为 a wiki-style 目录 because 也就是说 what
用户 可以 读取, edit, 和 grep 直接. 无 database, 无 opaque blob.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UserLayer:
    """Filesystem layout 的 用户-level cognitive state."""

    root: Path

    @classmethod
    def default(cls) -> "UserLayer":
        # ``user/`` lives inside 该 CognitiveOS project root so a single
        # ``git clone`` (或 rsync) carries it. v0.2+ 可能 move it 到
        # ~/.cognitiveos/user 到 make it independent 的 任何 one project.
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