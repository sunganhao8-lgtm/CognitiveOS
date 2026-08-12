"""命令行入口。

``pyproject.toml`` 里 ``cogos`` 指向本模块。要保持精简：解析命令、
分发到函数、打印结果。
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
    parser.add_argument("--root", type=Path, default=None, help="项目根（默认：当前目录）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="运行引导流程")
    p_bootstrap.add_argument("--no-browser", action="store_true", help="不要打开仪表盘")

    p_status = sub.add_parser("status", help="显示上一次的引导报告")

    p_export = sub.add_parser("export-user", help="把 user/ 层打包为 tar.gz")
    p_export.add_argument("--to", type=Path, required=True, help="目标 .tar.gz 路径")

    p_import = sub.add_parser("import-user", help="从 tar.gz 恢复 user/ 层")
    p_import.add_argument("--from", dest="src", type=Path, required=True, help="源 .tar.gz 路径")

    p_brief = sub.add_parser("brief", help="为指定 Agent 渲染管家入职 brief")
    p_brief.add_argument(
        "--agent",
        choices=["hermes", "codex", "claude", "raw"],
        default="raw",
        help="目标 Agent 格式（默认：raw markdown）",
    )

    p_persona = sub.add_parser("persona", help="训练 / 查看主人人格模型")
    persona_sub = p_persona.add_subparsers(dest="persona_cmd", required=True)

    p_ptrain = persona_sub.add_parser("fit", help="跑一轮 persona 拟合（与主人历史答案做语义匹配打分）")
    p_ptrain.add_argument("--seed", type=int, default=None, help="随机种子，便于复现")

    p_plist = persona_sub.add_parser("list", help="列出可用的经验")

    p_pshow = persona_sub.add_parser("show", help="显示当前 persona 模型")

    p_plog = persona_sub.add_parser("log", help="查看最近的训练样本")
    p_plog.add_argument("--last", type=int, default=5)

    p_verify = sub.add_parser("verify", help="跑复刻校验：把铁律抛给当前 Agent 并报告违反情况")
    p_verify.add_argument("--seed", type=int, default=None, help="可选种子，便于复现")

    p_ingest = sub.add_parser("ingest", help="从其他 Agent（Codex / Claude Code）抽取对话记忆到 user/conversations/")
    p_ingest.add_argument("--limit", type=int, default=None, help="每个数据源最多抽取多少对")

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
            print("暂无上一次的 bootstrap 记录。", file=sys.stderr)
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
            print(mp.read_text(encoding="utf-8") if mp.exists() else "（model.md 还不存在——先跑 `cogos persona fit`）")
            return 0
        if args.persona_cmd == "log":
            log = user.root / "persona" / "drivel.jsonl"
            if not log.exists():
                print("（暂无样本）")
                return 0
            lines = log.read_text(encoding="utf-8").splitlines()[-args.last:]
            for line in lines:
                rec = json.loads(line)
                print(f"[{rec['timestamp']}] q{rec['question_id']} score={rec.get('semantic_score', '?')}")
                print(f"    问：{rec['question'][:100].replace(chr(10), ' ')}")
                print(f"    管家：{rec['butler_answer'][:100].replace(chr(10), ' ')}")
                print(f"    主人：{rec['master_answer'][:100].replace(chr(10), ' ')}")
                if rec.get("diff_note"):
                    print(f"    差异：{rec['diff_note']}")
                print()
            return 0
        if args.persona_cmd == "fit":
            import shutil, subprocess, time

            qa = pick_random_qa(user, seed=args.seed)
            if qa is None:
                print("user/conversations/ 下还没有对话。先跑抽取器。", file=sys.stderr)
                return 1
            persona = build_persona_block(user)
            prompt = (
                "# 主人人格\n\n" + persona +
                "\n\n# 问题\n\n" + qa.question +
                "\n\n# 任务\n\n" + (
                    "请以主人自己的口吻和优先级回答这个问题——3-6 行、符合主人风格。"
                    "这是人格预测任务，不是客服任务。"
                )
            )
            if shutil.which("hermes") is None:
                print("hermes CLI 不在 PATH 上", file=sys.stderr)
                return 1

            # 第一阶段：管家以主人身份回答（不展示 ground truth）。
            t0 = time.time()
            proc1 = subprocess.run(
                ["hermes", "chat", "-q", prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
            )
            if proc1.returncode != 0:
                print(f"hermes 第一阶段失败：{proc1.stderr[:200]}", file=sys.stderr)
                return 2
            butler_answer = proc1.stdout.strip()

            # 第二阶段：与主人真实答案做语义匹配打分。
            eval_prompt = (
                "给下面两段答案的语义匹配程度打分。\n\n"
                f"管家（主人人格）：\n{butler_answer}\n\n"
                f"主人真实历史：\n{qa.answer[:1500]}\n\n"
                '只回 JSON：{"score": 0.0-1.0, "note": "一句话"}'
            )
            proc2 = subprocess.run(
                ["hermes", "chat", "-q", eval_prompt, "-t", "terminal,file", "--max-turns", "1", "-Q"],
                capture_output=True, text=True, timeout=120, encoding="utf-8",
            )
            elapsed = time.time() - t0
            if proc2.returncode != 0:
                print(f"hermes 第二阶段失败：{proc2.stderr[:200]}", file=sys.stderr)
                return 2
            # 从 eval 响应里抠 JSON。
            import re
            m = re.search(r"\{[^{}]*\"score\"[^{}]*\}", proc2.stdout)
            score, note = 0.5, "（未能解析）"
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
            print("user/rules/ 下还没有规则。请先创建 user/rules/R001.json 再跑。")
            return 4
        print(f"正在跑 {len(rules)} 条复刻探针...\n")
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
            print(f"  探针：    {res.probe}")
            print(f"  回应：    {res.agent_response[:160].replace(chr(10), ' ')}{'...' if len(res.agent_response) > 160 else ''}")
            print(f"  详情：    {res.detail}")
            print()
            results.append({"id": r.id, "verdict": res.verdict, "detail": res.detail})
        total = len(rules)
        print(f"汇总：{passes}/{total} 条规则通过")
        return 0 if passes == total else 3

    if args.cmd == "ingest":
        user = UserLayer(root=paths.root / "user")
        result = ingest_agent_memories(user, limit_per_source=args.limit)
        if not result:
            print("其他 Agent 里没找到对话记忆。")
        else:
            for source, count in result.items():
                print(f"{source}：抽到 {count} 对问答 -> user/conversations/")
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