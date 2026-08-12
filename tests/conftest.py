"""pytest configuration 用于 CognitiveOS."""

import sys
from pathlib import Path

# Make 该 在-tree cogos package importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))