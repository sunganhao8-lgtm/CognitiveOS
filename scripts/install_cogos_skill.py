"""Install cogos-bridge SKILL into DeepSeek Harness.

    PYTHONPATH=src python scripts/install_cogs_skill.py [target]

Default target: ~/.dsh/skills/cogos-bridge/   (DeepSeek Harness convention,
per its "Everything is a plugin" docs: ~/.dsh/skills/<name>/SKILL.md).

The skill directory is COPIED (not symlinked) so the harness reads a stable
file even after CognitiveOS moves. Re-running overwrites.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "cogos" / "skills" / "cogos-bridge"


def main(argv: list[str]) -> int:
    if not SOURCE.exists():
        print(f"ERROR: skill source not found: {SOURCE}", file=sys.stderr)
        return 1
    target = Path(argv[1]) if len(argv) > 1 else (Path.home() / ".dsh" / "skills" / "cogos-bridge")
    target.mkdir(parents=True, exist_ok=True)
    for f in SOURCE.iterdir():
        shutil.copy2(f, target / f.name)
    print(f"installed cogos-bridge → {target}")
    print("files:", sorted(p.name for p in target.iterdir()))
    print()
    print("next steps (DeepSeek Harness):")
    print("  1. start your harness — it auto-discovers ~/.dsh/skills/*")
    print("  2. open a session and run: cogos run --json '帮我写销售 SQL'")
    print("  3. confirm the Cognitive Context block is wired into the prompt")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))