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
from .persona import build_prompt, pick_random, parse_sample_output, maybe_update_model, record_sample, list_experiences


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

    p_persona = sub.add_parser("persona", help="Train / inspect the user persona model")
    persona_sub = p_persona.add_subparsers(dest="persona_cmd", required=True)

    p_ptrain = persona_sub.add_parser("train", help="Run one offline persona-training round")
    p_ptrain.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    p_plist = persona_sub.add_parser("list", help="List available experiences")

    p_pshow = persona_sub.add_parser("show", help="Show the current persona model")

    p_plog = persona_sub.add_parser("log", help="Show recent training samples")
    p_plog.add_argument("--last", type=int, default=5)

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

    if args.cmd == "persona":
        user = UserLayer(root=paths.root / "user")
        if args.persona_cmd == "list":
            for e in list_experiences(user):
                print(e.path.relative_to(paths.root))
            return 0
        if args.persona_cmd == "show":
            mp = user.root / "persona" / "model.md"
            print(mp.read_text(encoding="utf-8") if mp.exists() else "(model.md does not exist yet — run `cogos persona train` to start)")
            return 0
        if args.persona_cmd == "log":
            log = user.root / "persona" / "drivel.jsonl"
            if not log.exists():
                print("(no samples yet)")
                return 0
            lines = log.read_text(encoding="utf-8").splitlines()[-args.last:]
            for line in lines:
                rec = json.loads(line)
                print(f"[{rec['timestamp']}] {rec['experience']} reward={rec['reward']:.2f}")
                print(f"    prediction: {rec['prediction'][:120].replace(chr(10), ' ')}...")
                if rec.get("model_diff"):
                    print(f"    diff: {rec['model_diff']}")
                print()
            return 0
        if args.persona_cmd == "train":
            import shutil, subprocess, time
            exp = pick_random(user, seed=args.seed)
            if exp is None:
                print("No experiences under user/experience/. Add one with `cogos add-experience` or write directly.", file=sys.stderr)
                return 1
            prompt = build_prompt(user, exp)
            if shutil.which("hermes") is None:
                print("hermes CLI not on PATH", file=sys.stderr)
                return 1
            t0 = time.time()
            proc = subprocess.run(
                ["hermes", "chat", "-q", prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
            )
            elapsed = time.time() - t0
            if proc.returncode != 0:
                print(f"hermes failed: {proc.stderr[:200]}", file=sys.stderr)
                return 2
            sample, sample_path = record_sample(user, exp, prompt, proc.stdout)
            updated = maybe_update_model(user, sample)
            print(json.dumps({
                "experience": sample.experience,
                "reward": sample.reward,
                "model_updated": updated,
                "sample_path": str(sample_path),
                "elapsed": round(elapsed, 2),
            }, ensure_ascii=False, indent=2))
            return 0

    parser.error(f"unknown command: {args.cmd}")
    return 2