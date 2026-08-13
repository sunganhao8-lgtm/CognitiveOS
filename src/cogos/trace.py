"""Execution trace — first-class citizen of every ``cogos run``.

Canonical: append-only JSONL under ``user/traces/<YYYY-MM-DD>.jsonl``.
Projection: the Cognitive Store mirrors each record (write-through), and
``cogos reindex`` replays the JSONL to rebuild the projection.

Trace records OBSERVABLE system events only — which memory was retrieved,
which agent ran, what the verdict was. It NEVER records model-internal
chain-of-thought.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .store import Store
from .user import UserLayer


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def date_str(ts: str | None = None) -> str:
    d = datetime.fromisoformat((ts or now_iso()).replace("Z", "+00:00"))
    return d.strftime("%Y-%m-%d")


def trace_file(user: UserLayer, ts: str | None = None) -> str:
    """Path of today's canonical trace file."""
    user.traces.mkdir(parents=True, exist_ok=True)
    return str(user.traces / f"{date_str(ts)}.jsonl")


def new_execution_id(store: Store, ts: str | None = None) -> str:
    """Unique execution id: ``ex-YYYYMMDD-NNNNNN`` (daily sequence)."""
    return new_run_id(store, prefix="ex", ts=ts)


def new_run_id(store: Store, *, prefix: str = "ex", ts: str | None = None) -> str:
    """Unique run id with a daily sequence: ``<prefix>-YYYYMMDD-NNNNNN``.

    Executions use ``ex-``; offline consolidation cycles use ``slp-`` so the
    dashboard can tell "when did CognitiveOS learn" from normal runs.
    """
    ts = ts or now_iso()
    date = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y%m%d")
    count = store.execution_count_on(f"{prefix}-{date}")
    return f"{prefix}-{date}-{count + 1:06d}"


def append_event(
    user: UserLayer,
    store: Store,
    execution_id: str,
    step: str,
    *,
    detail: str = "",
    refs: list | None = None,
    ts: str | None = None,
) -> None:
    """Append one event to the canonical JSONL AND the store projection."""
    ts = ts or now_iso()
    rec = {
        "type": "event",
        "execution_id": execution_id,
        "step": step,
        "detail": detail,
        "refs": refs or [],
        "ts": ts,
    }
    _append_jsonl(trace_file(user, ts), rec)
    store.record_event(execution_id, step, detail, refs, ts)


def append_verification(
    user: UserLayer,
    store: Store,
    execution_id: str,
    rule_id: str,
    verdict: str,
    detail: str,
    ts: str | None = None,
) -> None:
    ts = ts or now_iso()
    rec = {
        "type": "verification",
        "execution_id": execution_id,
        "rule_id": rule_id,
        "verdict": verdict,
        "detail": detail,
        "ts": ts,
    }
    _append_jsonl(trace_file(user, ts), rec)
    store.record_verification(execution_id, rule_id, verdict, detail, ts)


def append_execution(user: UserLayer, store: Store, exec_row: dict) -> None:
    """Append the execution summary record (canonical + projection)."""
    exec_row = {**exec_row, "type": "execution"}
    _append_jsonl(trace_file(user, exec_row.get("started_at")), exec_row)
    refs = exec_row.pop("refs", [])
    payload = {k: v for k, v in exec_row.items() if k != "type"}
    store.record_execution(
        {
            "execution_id": exec_row["execution_id"],
            "task": exec_row.get("task", ""),
            "intent_type": exec_row.get("intent_type", ""),
            "agent_id": exec_row.get("agent_id") or "",
            "status": exec_row.get("status", ""),
            "verdict": exec_row.get("verdict", ""),
            "context_chars": exec_row.get("context_chars") or 0,
            "started_at": exec_row.get("started_at", ""),
            "finished_at": exec_row.get("finished_at", ""),
            "payload": json_dumps(payload, refs),
        }
    )


def json_dumps(payload: dict, refs: list) -> str:
    import json

    payload = {**payload, "refs": refs}
    return json.dumps(payload, ensure_ascii=False)


def _append_jsonl(path: str, rec: dict) -> None:
    import json

    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
