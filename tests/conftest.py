"""pytest configuration for CognitiveOS."""

import sys
from pathlib import Path

# Make the in-tree cogos package importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))