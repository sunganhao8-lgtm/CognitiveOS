"""Command-line entry point.

This module is what ``pyproject.toml`` points ``cogos`` at. It must stay
small: parse the command, dispatch to a function, print a result.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .bootstrap import run as bootstrap_run
from .paths import Paths
from .user import UserLayer
from .portability import export_user, import_user
from .brief import render_brief
from .verify import GENERATED_RULES, load_rules, seed_generated_rules, run_one, record
from .agent_memories import extract_all as ingest_agent_memories
from .persona_fit import (
    build_persona_block,
    load_qa_pairs,
    pick_random_qa,
    record_fit_sample,
    maybe_update_model,
    FitSample,
)
from .tasks import add_task_parser, run_task
from .inbox import add_inbox_parser, run_inbox
from .workspace import add_workspace_parser, run_workspace, add_lock_parser, run_lock


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

    p_ptrain = persona_sub.add_parser("fit", help="Run one persona-fitting round (semantic match against master's past answer)")
    p_ptrain.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    p_plist = persona_sub.add_parser("list", help="List available experiences")

    p_pshow = persona_sub.add_parser("show", help="Show the current persona model")

    p_plog = persona_sub.add_parser("log", help="Show recent training samples")
    p_plog.add_argument("--last", type=int, default=5)

    p_verify = sub.add_parser("verify", help="Run reproduction tests: throw iron rules at the current agent and report breaches")
    p_verify.add_argument("--seed", type=int, default=None, help="Optional seed for reproducibility")

    p_ingest = sub.add_parser("ingest", help="Extract conversation memories from other agents (Codex / Claude Code) into user/conversations/")
    p_ingest.add_argument("--limit", type=int, default=None, help="Max pairs per source")

    add_task_parser(sub)
    add_inbox_parser(sub)
    add_workspace_parser(sub)
    add_lock_parser(sub)

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
            for e in load_qa_pairs(user)[:20]:
                print(f"q{e.question_id} [{e.session_id[:8]}] {e.question[:60].replace(chr(10), ' ')}")
            return 0
        if args.persona_cmd == "show":
            mp = user.root / "persona" / "model.md"
            print(mp.read_text(encoding="utf-8") if mp.exists() else "(model.md does not exist yet — run `cogos persona fit` to start)")
            return 0
        if args.persona_cmd == "log":
            log = user.root / "persona" / "drivel.jsonl"
            if not log.exists():
                print("(no samples yet)")
                return 0
            lines = log.read_text(encoding="utf-8").splitlines()[-args.last:]
            for line in lines:
                rec = json.loads(line)
                print(f"[{rec['timestamp']}] q{rec['question_id']} score={rec.get('semantic_score', '?')}")
                print(f"    Q: {rec['question'][:100].replace(chr(10), ' ')}")
                print(f"    butler: {rec['butler_answer'][:100].replace(chr(10), ' ')}")
                print(f"    master: {rec['master_answer'][:100].replace(chr(10), ' ')}")
                if rec.get("diff_note"):
                    print(f"    diff: {rec['diff_note']}")
                print()
            return 0
        if args.persona_cmd == "fit":
            import shutil, subprocess, time

            qa = pick_random_qa(user, seed=args.seed)
            if qa is None:
                print("No conversations under user/conversations/. Run the extractor first.", file=sys.stderr)
                return 1
            persona = build_persona_block(user)
            prompt = (
                "# MASTER PERSONA\n\n" + persona +
                "\n\n# QUESTION\n\n" + qa.question +
                "\n\n# TASK\n\n" + (
                    "Answer this question AS the master would answer it — in their "
                    "voice and priorities. 3-6 lines, their style. This is a persona "
                    "prediction task, not a help-desk task."
                )
            )
            if shutil.which("hermes") is None:
                print("hermes CLI not on PATH", file=sys.stderr)
                return 1

            # Stage 1: butler answers as the master (no ground truth shown).
            t0 = time.time()
            proc1 = subprocess.run(
                ["hermes", "chat", "-q", prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
            )
            if proc1.returncode != 0:
                print(f"hermes stage-1 failed: {proc1.stderr[:200]}", file=sys.stderr)
                return 2
            butler_answer = proc1.stdout.strip()

            # Stage 2: semantic-match scoring against the master's actual answer.
            eval_prompt = (
                "Score semantic match between these two answers.\n\n"
                f"BUTLER (master persona):\n{butler_answer}\n\n"
                f"MASTER ACTUAL HISTORY:\n{qa.answer[:1500]}\n\n"
                'Reply with ONLY JSON: {"score": 0.0-1.0, "note": "one line"}'
            )
            proc2 = subprocess.run(
                ["hermes", "chat", "-q", eval_prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
            )
            elapsed = time.time() - t0
            if proc2.returncode != 0:
                print(f"hermes stage-2 failed: {proc2.stderr[:200]}", file=sys.stderr)
                return 2
            # Parse JSON from eval response.
            import re
            m = re.search(r"\{[^{}]*\"score\"[^{}]*\}", proc2.stdout)
            score, note = 0.5, "(unparsed)"
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    score = float(parsed.get("score", 0.5))
                    note = parsed.get("note", "")
                except Exception:
                    pass

            sample = FitSample(
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                question_id=qa.question_id,
                question=qa.question,
                butler_answer=butler_answer,
                master_answer=qa.answer[:1500],
                semantic_score=score,
                diff_note=note,
                session_id=qa.session_id,
            )
            sample_path = record_fit_sample(user, sample)
            updated = maybe_update_model(user, sample)
            print(json.dumps({
                "question_id": qa.question_id,
                "question": qa.question[:80],
                "semantic_score": score,
                "model_updated": updated,
                "sample_path": str(sample_path),
                "elapsed": round(elapsed, 2),
            }, ensure_ascii=False, indent=2))
            return 0

    if args.cmd == "verify":
        import time as _time
        user = UserLayer(root=paths.root / "user")
        seeded = seed_generated_rules(user)
        rules = load_rules(user)
        if not rules:
            print("No rules under user/rules/. Create one as user/rules/R001.json and re-run.")
            return 4
        print(f"Running {len(rules)} reproduction probe(s)...\n")
        results: list[dict] = []
        passes = 0
        for r in rules:
            t0 = _time.time()
            res = run_one(r)
            record(user, res)
            elapsed = _time.time() - t0
            mark = "PASS" if res.verdict == "PASS" else "FAIL"
            if res.verdict == "PASS":
                passes += 1
            print(f"[{mark}] {r.id} ({elapsed:.1f}s)")
            print(f"  probe:    {res.probe}")
            print(f"  response: {res.agent_response[:160].replace(chr(10), ' ')}{'...' if len(res.agent_response) > 160 else ''}")
            print(f"  detail:   {res.detail}")
            print()
            results.append({"id": r.id, "verdict": res.verdict, "detail": res.detail})
        total = len(rules)
        print(f"summary: {passes}/{total} rules held")
        return 0 if passes == total else 3

    if args.cmd == "ingest":
        user = UserLayer(root=paths.root / "user")
        result = ingest_agent_memories(user, limit_per_source=args.limit)
        if not result:
            print("No conversation memories found in other agents.")
        else:
            for source, count in result.items():
                print(f"{source}: extracted {count} QA pairs -> user/conversations/")
        return 0

    if args.cmd == "task":
        return run_task(args)

    if args.cmd == "inbox":
        return run_inbox(args)

    if args.cmd == "workspace":
        return run_workspace(args)

    if args.cmd == "lock":
        return run_lock(args)

    parser.error(f"unknown command: {args.cmd}")
    return 2