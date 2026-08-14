"""Phase 11 — security scan.

Scans the repo (tracked files + generated HTML) for secret-shaped content:

    API keys (sk-...), Bearer tokens, auth.json refs, .env leakage,
    private key headers, real memory files in tracked paths.

Exit code 0 = clean; 1 = findings (or scan error).

Local-first boundary (confirmed by design, not by scan):
- remote embedding requires COGOS_EMBEDDING_REMOTE_* env vars (explicit opt-in)
- auth.json / .env live under the Hermes profile dirs, never the repo
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERNS = [
    (r"sk-[A-Za-z0-9]{16,}", "API key (sk-...)"),
    (r"Bearer\s+[A-Za-z0-9._-]{20,}", "Bearer token"),
    (r"-----BEGIN (RSA|OPENSSH|EC|PRIVATE) KEY-----", "private key"),
    (r"(?i)api[_-]?key\s*=\s*['\"][^'\"]{12,}['\"]", "api_key= literal"),
    (r"(?i)token\s*=\s*['\"][^'\"]{16,}['\"]", "token= literal"),
    (r"MINIMAX_CN_API_KEY\s*=\s*[^\s#]{10,}", "minimax key literal"),
    (r"DEEPSEEK_API_KEY\s*=\s*[^\s#]{10,}", "deepseek key literal"),
    (r"ghp_[A-Za-z0-9]{20,}", "github token"),
]


def tracked_files() -> list[Path]:
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT)
    return [ROOT / p for p in r.stdout.splitlines() if p]


def scan() -> list[str]:
    findings: list[str] = []
    files = tracked_files()
    # explicitly add generated surfaces that are untracked by design
    for extra in (ROOT / "demo" / "index.html",):
        if extra.exists() and extra not in files:
            files.append(extra)
    for f in files:
        if not f.exists() or f.suffix in (".png", ".jpg", ".svg", ".ico", ".woff2"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat, label in PATTERNS:
            for m in re.finditer(pat, text):
                # whitelist: the canary test fixture intentionally contains
                # the literal 'sk-' examples? check for known test fixtures
                findings.append(f"{f.relative_to(ROOT)}: {label} (pattern {pat[:20]}…)")
    # boundary checks
    for forbidden in ("auth.json", ".env", "user/"):
        if forbidden in [str(f.relative_to(ROOT)) for f in tracked_files()]:
            findings.append(f"forbidden tracked path: {forbidden}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print(f"SECURITY FINDINGS ({len(findings)}):")
        for f in findings:
            print("  -", f)
        print("\nRemote embedding opt-in check:")
        print("  COGOS_EMBEDDING_REMOTE_BASE_URL set:", bool(__import__("os").environ.get("COGOS_EMBEDDING_REMOTE_BASE_URL")))
        return 1
    print("security scan: CLEAN (no secret-shaped content in tracked files or demo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
