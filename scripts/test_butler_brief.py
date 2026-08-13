"""Real butler-induction test.

This proves the end-to-end handoff: render the manifest, hand it to a
real Hermes session, then ask two questions designed to verify the
butler absorbed the "forged-not-to-be-forged" list.

Run:
    PYTHONPATH=src python scripts/test_butler_brief.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cogos.brief import render_brief
from cogos.user import UserLayer


VERIFY_PROMPT = (
    "Based ONLY on the brief you just received, answer two questions:\n"
    "1. The store project described in the brief — is it currently open, "
    "in preparation, or failed? (One sentence.)\n"
    "2. In that store's brand story, is AI positioned as a 'core lever' "
    "or as 'just a tool'? (One sentence.)\n"
    "Do not consult any other source. Just the brief."
)


def main() -> int:
    user = UserLayer(root=ROOT / "user")
    brief = render_brief(user, "raw")
    print(f"[1/3] brief size: {len(brief)} chars, {len(brief.splitlines())} lines")

    if shutil.which("hermes") is None:
        print("hermes CLI not on PATH; aborting")
        return 1

    # Two-step: first install the brief as the butler's context, then ask.
    combined = brief + "\n\n---\n\n" + VERIFY_PROMPT

    print("[2/3] dispatching to hermes chat -q (max-turns 1, quiet) ...")
    import time
    t0 = time.time()
    proc = subprocess.run(
        [
            "hermes", "chat",
            "-q", combined,
            "-t", "terminal,file",
            "--max-turns", "1",
            "-Q",
        ],
        capture_output=True,
        text=True,
        timeout=90,
        encoding="utf-8",
    )
    elapsed = time.time() - t0

    print(f"      elapsed: {elapsed:.1f}s")
    print(f"      exit    : {proc.returncode}")
    print()
    print("[3/3] BUTLER ANSWER:")
    print("-" * 60)
    print((proc.stdout or "(empty)").strip())
    print("-" * 60)

    out = ROOT / ".cogos" / "butler_brief_test.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(proc.stdout or "", encoding="utf-8")
    print(f"      saved   -> {out}")
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())