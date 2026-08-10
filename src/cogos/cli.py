"""Command-line entry point.

This module is what ``pyproject.toml`` points ``cogos`` at. It must stay
small: parse the command, dispatch to a function, print a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .bootstrap import run as bootstrap_run
from .paths import Paths
from .user import UserLayer
from .portability import export_user, import_user
from .brief import render_brief


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cogos", description="CognitiveOS CLI")
    parser.add_argument("--root", type=Path, default=None, help="Project root (default: cwd)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="Run the bootstrap pipeline")
    p_bootstrap.add_argument("--no-browser", action="store_true", help="Don't open the dashboard")

    p_status = sub.add_parser("status", help="Show last bootstrap report")

    p_export = sub.add_parser("export-user", help="Export the user/ layer to a tar.gz")
    p_export.add_argument("--to", type=Path, required=True, help="Destination .tar.gz path")

    p_import = sub.add_parser("import-user", help="Import the user/ layer from a tar.gz")
    p_import.add_argument("--from", dest="src", type=Path, required=True, help="Source .tar.gz path")

    p_brief = sub.add_parser("brief", help="Render a butler induction brief for a specific agent")
    p_brief.add_argument(
        "--agent",
        choices=["hermes", "codex", "claude", "raw"],
        default="raw",
        help="Target agent format (default: raw markdown)",
    )

    args = parser.parse_args(argv)
    paths = Paths(root=(args.root or Path.cwd()).resolve())

    if args.cmd == "bootstrap":
        report = bootstrap_run(paths, open_browser=not args.no_browser)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "status":
        last = paths.cache / "last_report.json"
        if not last.exists():
            print("No previous bootstrap run recorded.", file=sys.stderr)
            return 1
        print(last.read_text(encoding="utf-8"))
        return 0

    if args.cmd == "export-user":
        user = UserLayer(root=paths.root / "user")
        manifest = export_user(user, args.to)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "import-user":
        user = UserLayer(root=paths.root / "user")
        result = import_user(user, args.src)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "brief":
        user = UserLayer(root=paths.root / "user")
        print(render_brief(user, args.agent))
        return 0

    parser.error(f"unknown command: {args.cmd}")
    return 2