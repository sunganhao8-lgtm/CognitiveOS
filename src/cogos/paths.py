"""Paths used by CognitiveOS.

Everything is rooted under a single ``root`` directory so the project can
live anywhere on disk. The default is the current working directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """A bundle of every directory CognitiveOS cares about.

    Keeping them in one place makes it easy to override ``root`` for tests
    and to print a clear status panel at the end of a bootstrap run.
    """

    root: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(root=Path.cwd().resolve())

    # --- top-level layout ---------------------------------------------------

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def sources(self) -> Path:
        return self.knowledge / "sources"

    @property
    def normalized(self) -> Path:
        return self.knowledge / "normalized"

    @property
    def wiki(self) -> Path:
        return self.knowledge / "wiki"

    @property
    def dashboard(self) -> Path:
        return self.root / "dashboard"

    @property
    def dashboard_index(self) -> Path:
        return self.dashboard / "index.html"

    @property
    def cache(self) -> Path:
        return self.root / ".cogos"

    @property
    def config_file(self) -> Path:
        return self.root / "cogos.yaml"

    # --- helpers ------------------------------------------------------------

    def ensure(self) -> None:
        """Create every directory CognitiveOS writes to."""
        for p in (
            self.knowledge,
            self.sources,
            self.normalized,
            self.wiki,
            self.dashboard,
            self.cache,
        ):
            p.mkdir(parents=True, exist_ok=True)