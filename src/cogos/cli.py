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

    p_run = sub.add_parser("run", help="Run the full cognitive loop: classify → remember/retrieve → context → execute → verify → learn → trace")
    p_run.add_argument("text", nargs="?", default=None, help="User input (a task or a rule statement)")
    p_run.add_argument("--list", dest="list_runs", action="store_true", help="List recent executions instead of running")
    p_run.add_argument("--no-llm", action="store_true", help="Skip LLM calls (keyword classification + pattern extraction only)")
    p_run.add_argument("--budget", type=int, default=None, help="Context budget in characters (default 4000)")

    p_reindex = sub.add_parser("reindex", help="Rebuild the Cognitive Store (SQLite index) from canonical user/ data")

    p_sleep = sub.add_parser("sleep", help="Offline cognitive consolidation: pattern detection → candidates → promotion (idempotent)")
    p_sleep.add_argument("--with-llm", action="store_true", help="Optionally polish candidate descriptions with an LLM (promotion decisions stay deterministic)")
    p_sleep.add_argument("--list", dest="list_sleeps", action="store_true", help="List past sleep cycles instead of running")

    p_memory = sub.add_parser("memory", help="Inspect cognitive memory (Phase 3B: version history, supersede chains, conflicts)")
    mem_sub = p_memory.add_subparsers(dest="memory_cmd", required=True)
    p_mem_show = mem_sub.add_parser("show", help="Show one cognition: current state, version history, evidence, scope")
    p_mem_show.add_argument("ent_id", help="Memory id (e.g. R-SQL-001, P-SQL-001)")

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

    if args.cmd == "run":
        return _run_command(paths, args)

    if args.cmd == "reindex":
        from .store import Store

        store = Store(paths.cache / "cognitive.db")
        try:
            report = store.reindex(paths)
        finally:
            store.close()
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "sleep":
        return _sleep_command(paths, args)

    if args.cmd == "memory":
        return _memory_show(paths, args.ent_id)

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


# ---------------------------------------------------------------------------
# run / reindex helpers
# ---------------------------------------------------------------------------


def _hermes_llm(prompt: str, *, timeout: int = 120, profile: str = "cogos-test") -> str | None:
    """Single-shot Hermes call used for semantic classification / rule
    extraction / semantic judging. Sessions are quarantined in the
    ``cogos-test`` profile so probes never pollute the master's history."""
    import shutil
    import subprocess

    if shutil.which("hermes") is None:
        return None
    try:
        proc = subprocess.run(
            ["hermes", "--profile", profile, "chat", "-q", prompt,
             "-t", "terminal,file",
             "--max-turns", "1", "-Q",
             "--reasoning", "none"],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8",
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return _clean_hermes_stdout(proc.stdout)


def _clean_hermes_stdout(stdout: str) -> str | None:
    """Hermes v0.20 emits a leading ``session_id: ...`` line in -Q mode;
    strip it (and any blank leading lines) so callers get the answer text.

    Also strips ANSI escape sequences and any residual reasoning panel —
    we must never record model-internal chain-of-thought (trace policy)."""
    import re

    text = stdout or ""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # ANSI colors/styles
    text = re.sub(r"[┌└┐┘│─]+\s*Reasoning[^\n]*", "", text)  # reasoning panel open
    lines = [
        ln for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("session_id:")
    ]
    return "\n".join(lines).strip() or None


def _run_command(paths, args) -> int:
    """``cogos run`` — the full cognitive loop."""
    from .adapters import load_adapter
    from .discovery import discover as discover_agents
    from .kernel import kernel_from_paths

    if args.list_runs:
        from .store import Store

        store = Store(paths.cache / "cognitive.db")
        try:
            runs = store.recent_executions(limit=10)
        finally:
            store.close()
        if not runs:
            print("(no executions recorded yet — run `cogos run \"<text>\"` first)")
            return 0
        for r in runs:
            print(
                f"{r['execution_id']}  {r['status']:<8} verdict={r['verdict'] or '-'}"
                f"  agent={r['agent_id'] or '-'}  {r['task'][:60]}"
            )
        return 0

    if not args.text:
        print("usage: cogos run \"<task or rule statement>\"", file=sys.stderr)
        return 2

    handles = discover_agents(paths)
    adapters = [load_adapter(h) for h in handles]
    adapters = [a for a in adapters if a is not None]
    if not adapters:
        print("no agent adapters available (Hermes not found?)", file=sys.stderr)
        return 1

    llm_fn = None if args.no_llm else _hermes_llm
    kernel = kernel_from_paths(
        paths,
        adapters,
        llm_fn=llm_fn,
        context_budget=args.budget if args.budget else None,
        allow_semantic=not args.no_llm,
    )

    result = kernel.run_input(args.text)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status in ("success", "learned") else 3


def _sleep_command(paths, args) -> int:
    """``cogos sleep`` — one offline cognitive-consolidation cycle."""
    from .growth import run_sleep
    from .store import Store
    from .user import UserLayer

    if args.list_sleeps:
        store = Store(paths.cache / "cognitive.db")
        try:
            runs = [
                r for r in store.recent_executions(limit=20)
                if r.get("intent_type") == "sleep"
            ]
        finally:
            store.close()
        if not runs:
            print("(no sleep cycles recorded yet — run `cogos sleep` first)")
            return 0
        for r in runs:
            promoted = ", ".join(r.get("payload", {}).get("memory_written", [])) or "-"
            print(f"{r['execution_id']}  {r['started_at']}  promoted=[{promoted}]")
        return 0

    user = UserLayer(root=paths.root / "user")
    user.ensure()
    store = Store(paths.cache / "cognitive.db")
    try:
        llm_fn = _hermes_llm if args.with_llm else None
        report = run_sleep(user, store, llm_fn=llm_fn)
    finally:
        store.close()
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _memory_show(paths, ent_id: str) -> int:
    """``cogos memory show <id>`` — full version history of one cognition.

    Shows Current / Version / History / Evidence / Supersedes / Superseded-by /
    Conflicts / Scope — the data behind "why did you think this?" (§21/22).
    """
    from .conflict import detect_conflicts
    from .store import Store

    store = Store(paths.cache / "cognitive.db")
    try:
        chain = store.version_chain(ent_id)
        if not chain:
            print(f"(no memory with id {ent_id!r})")
            return 1
        out: dict = {
            "id": ent_id,
            "domain": chain[-1]["domain"],
            "subtype": chain[-1]["subtype"],
            "scope": chain[-1]["scope"],
            "scope_id": chain[-1]["scope_id"],
            "status": chain[-1]["status"],
            "current_content": chain[-1]["content"],
            "confidence": chain[-1]["confidence"],
            "evidence_count": chain[-1]["evidence_count"],
            "verify_pass_count": chain[-1]["verify_pass_count"],
            "user_confirmed": bool(chain[-1]["user_confirmed"]),
            "version_history": [
                {
                    "id": e["id"],
                    "version": e["version"],
                    "status": e["status"],
                    "content": e["content"][:200],
                    "confidence": e["confidence"],
                    "created_at": e["created_at"],
                    "superseded_at": e["superseded_at"],
                    "superseded_by": e["superseded_by"],
                    "superseded_reason": e["superseded_reason"],
                }
                for e in chain
            ],
            "source_executions": (chain[-1].get("payload") or {}).get("source_executions", []),
            "conflicts": [
                c.to_dict()
                for c in detect_conflicts(store, chain[-1]["domain"])
                if ent_id in (c.a_id, c.b_id) or ent_id in (c.winner,)
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        store.close()