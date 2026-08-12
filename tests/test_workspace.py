"""测试 用于 该 shared-工作区 P0: 任务 registry, 收件箱, 文件 锁们, CLI.

Covers docs/shared-工作区-design.md P0 scope:
  - 工作区 init / 扫描 + root resolution
  - 任务 创建 / 更新 / 列出 / 显示 (registry 作为 .cogos/任务们/*.json)
  - 收件箱 发送 / 检查 (persistent mailbox 文件们, 读取 state)
  - 文件 锁 获取 / 释放 / conflict handling
  - end-到-end CLI wiring (所有 commands support --json)
"""

import json
from datetime import datetime, timezone

import pytest

from cogos.cli import main
from cogos.inbox import InboxError, check_inbox, send_message
from cogos.tasks import (
    TaskError,
    TaskExists,
    TaskNotFound,
    create_task,
    list_tasks,
    show_task,
    update_task,
)
from cogos.workspace import (
    DEFAULT_WORKSPACE_ROOT,
    LockConflict,
    LockError,
    Workspace,
    acquire_lock,
    init_workspace,
    list_locks,
    release_lock,
    resolve_root,
    scan_workspace,
)


@pytest.fixture
def ws(tmp_path):
    w = Workspace(root=tmp_path / "ws")
    init_workspace(w)
    return w


# --- 工作区 init / root resolution --------------------------------------


def test_init_creates_skeleton(ws):
    assert ws.tasks_dir.is_dir()
    assert ws.locks_dir.is_dir()
    assert ws.messages_dir.is_dir()


def test_init_is_idempotent(ws):
    init_workspace(ws)
    assert ws.tasks_dir.is_dir()


def test_resolve_root_prefers_flag_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COGOS_WORKSPACE", str(tmp_path / "env_root"))
    assert resolve_root(tmp_path / "flag_root") == (tmp_path / "flag_root").resolve()


def test_resolve_root_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COGOS_WORKSPACE", str(tmp_path / "env_root"))
    assert resolve_root(None) == (tmp_path / "env_root").resolve()


def test_resolve_root_defaults_to_constant(monkeypatch):
    monkeypatch.delenv("COGOS_WORKSPACE", raising=False)
    assert resolve_root(None) == DEFAULT_WORKSPACE_ROOT.resolve()


def test_resolve_target_rejects_traversal(ws):
    from cogos.workspace import Workspace as W

    w = W(root=ws.root)
    with pytest.raises(ValueError):
        w.resolve_target("../escape.txt")
    with pytest.raises(ValueError):
        w.resolve_target("C:/Windows/system32")
    with pytest.raises(ValueError):
        w.resolve_target("/abs/path")


# --- 任务 registry ----------------------------------------------------------


def test_task_create_roundtrip(ws):
    t = create_task(
        ws, title="修改首页布局效果", assignee="claude_code",
        progress=10, current_file="src/index.html", branch="feature/homepage-fix",
        note="开始任务", actor="claude_code",
    )
    assert t.id == "TASK-001"
    assert t.status == "pending"
    assert t.progress == 10
    assert len(t.history) == 1
    assert t.history[0]["msg"] == "claude_code: 开始任务"
    # persisted 在 disk 作为 one JSON 文件
    f = ws.tasks_dir / "TASK-001.json"
    assert f.exists()
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["title"] == "修改首页布局效果"
    assert data["branch"] == "feature/homepage-fix"


def test_task_auto_id_increments(ws):
    a = create_task(ws, title="one")
    b = create_task(ws, title="two")
    assert (a.id, b.id) == ("TASK-001", "TASK-002")


def test_task_explicit_id_and_duplicate_rejected(ws):
    t = create_task(ws, title="x", task_id="TASK-042")
    assert t.id == "TASK-042"
    with pytest.raises(TaskExists):
        create_task(ws, title="y", task_id="TASK-042")


def test_task_invalid_id_and_status_rejected(ws):
    with pytest.raises(TaskError):
        create_task(ws, title="x", task_id="bad id!")
    with pytest.raises(TaskError):
        create_task(ws, title="x", status="bogus")


def test_task_update_fields_history_and_clamp(ws):
    t = create_task(ws, title="t", actor="hermes")
    updated = update_task(
        ws, t.id, progress=150, status="in_progress", current_file="src/app.py",
        note="布局重构完成", actor="claude_code",
    )
    assert updated.progress == 100  # clamped
    assert updated.status == "in_progress"
    assert updated.current_file == "src/app.py"
    assert len(updated.history) == 1  # create had no note; update added one
    assert updated.history[-1]["msg"] == "claude_code: 布局重构完成"
    assert updated.updated_at >= t.created_at


def test_task_update_noop_keeps_history(ws):
    t = create_task(ws, title="t")
    updated = update_task(ws, t.id, progress=50)
    assert len(updated.history) == 1  # auto entry for the progress change
    updated2 = update_task(ws, t.id, progress=50)
    assert len(updated2.history) == 1  # identical update -> nothing appended


def test_task_update_missing_raises(ws):
    with pytest.raises(TaskNotFound):
        update_task(ws, "TASK-999", progress=10)


def test_task_show_missing_raises(ws):
    with pytest.raises(TaskNotFound):
        show_task(ws, "TASK-999")


def test_task_list_filters(ws):
    create_task(ws, title="a", assignee="hermes", status="pending")
    create_task(ws, title="b", assignee="claude_code", status="in_progress")
    create_task(ws, title="c", assignee="claude_code", status="done")
    assert len(list_tasks(ws)) == 3
    assert [t.id for t in list_tasks(ws, status="in_progress")] == ["TASK-002"]
    assert [t.id for t in list_tasks(ws, assignee="claude_code")] == ["TASK-002", "TASK-003"]


# --- 收件箱 ------------------------------------------------------------------


def test_inbox_send_check_roundtrip(ws):
    msg = send_message(
        ws, to="claude_code", from_="hermes", type="review_request",
        task_id="TASK-001", content="请查看 src/index.html 的改动",
        attachments=["git diff --stat"],
    )
    assert msg.to == "claude_code"
    assert msg.from_ == "hermes"
    box = ws.messages_dir / "TO_claude_code"
    assert box.is_dir()
    assert len(list(box.glob("*.json"))) == 1
    got = check_inbox(ws, to="claude_code")
    assert len(got) == 1
    assert got[0].type == "review_request"
    assert got[0].task_id == "TASK-001"
    assert got[0].attachments == ["git diff --stat"]
    assert got[0].read is False


def test_inbox_check_all_mailboxes(ws):
    send_message(ws, to="hermes", from_="codex", content="hi hermes")
    send_message(ws, to="claude_code", from_="hermes", content="hi claude")
    msgs = check_inbox(ws)
    assert len(msgs) == 2
    assert sorted({m.to for m in msgs}) == ["claude_code", "hermes"]


def test_inbox_unread_only_and_mark_read(ws):
    send_message(ws, to="hermes", from_="codex", content="one")
    send_message(ws, to="hermes", from_="codex", content="two")
    assert len(check_inbox(ws, to="hermes", unread_only=True)) == 2
    checked = check_inbox(ws, to="hermes", mark_read=True)
    assert all(m.read for m in checked)
    assert check_inbox(ws, to="hermes", unread_only=True) == []
    # 该 读取 flag 是 persisted 在 disk
    data = json.loads(next((ws.messages_dir / "TO_hermes").glob("*.json")).read_text(encoding="utf-8"))
    assert data["read"] is True


def test_inbox_rejects_bad_agent_ids(ws):
    with pytest.raises(InboxError):
        send_message(ws, to="../escape", content="x")
    with pytest.raises(InboxError):
        send_message(ws, to="has space", content="x")
    with pytest.raises(InboxError):
        send_message(ws, to="", content="x")


def test_inbox_rejects_unknown_type(ws):
    with pytest.raises(InboxError):
        send_message(ws, to="hermes", content="x", type="carrier_pigeon")


# --- 文件 锁们 -------------------------------------------------------------


def test_lock_acquire_release(ws):
    payload = acquire_lock(ws, "repo1/src/index.html", holder="hermes", note="refactor")
    assert payload["holder"] == "hermes"
    lock_file = ws.locks_dir / "repo1" / "src" / "index.html.lock"
    assert lock_file.exists()
    locks = list_locks(ws)
    assert len(locks) == 1
    assert locks[0]["target"] == "repo1/src/index.html"
    release_lock(ws, "repo1/src/index.html", holder="hermes")
    assert not lock_file.exists()
    assert list_locks(ws) == []


def test_lock_conflict_on_second_acquire(ws):
    acquire_lock(ws, "repo1/f.py", holder="hermes")
    with pytest.raises(LockConflict):
        acquire_lock(ws, "repo1/f.py", holder="claude_code")


def test_lock_force_breaks_existing(ws):
    acquire_lock(ws, "repo1/f.py", holder="hermes")
    payload = acquire_lock(ws, "repo1/f.py", holder="claude_code", force=True)
    assert payload["holder"] == "claude_code"


def test_lock_release_requires_holder(ws):
    acquire_lock(ws, "repo1/f.py", holder="hermes")
    with pytest.raises(LockError):
        release_lock(ws, "repo1/f.py", holder="claude_code")
    release_lock(ws, "repo1/f.py", holder="claude_code", force=True)


def test_lock_release_missing_raises(ws):
    with pytest.raises(LockError):
        release_lock(ws, "repo1/f.py", holder="hermes")


def test_lock_rejects_absolute_target(ws):
    with pytest.raises(ValueError):
        acquire_lock(ws, "C:/Windows/system32", holder="hermes")


# --- 工作区 扫描 (P1 simple) ---------------------------------------------


def test_scan_empty_workspace(ws):
    assert scan_workspace(ws)["repos"] == []


def test_scan_detects_repo_and_recent_files(tmp_path):
    w = Workspace(root=tmp_path / "ws")
    init_workspace(w)
    repo = w.root / "repo1"
    (repo / ".git").mkdir(parents=True)
    (repo / "readme.md").write_text("hello", encoding="utf-8")
    result = scan_workspace(w)
    assert len(result["repos"]) == 1
    r = result["repos"][0]
    assert r["repo"] == "repo1"
    assert "readme.md" in r["recent_files"]
    assert r["dirty_files"] == 0  # no real git: tolerated, not fatal


def test_scan_skips_cogos_and_hidden_dirs(tmp_path):
    w = Workspace(root=tmp_path / "ws")
    init_workspace(w)
    (w.root / ".hidden" / ".git").mkdir(parents=True)
    assert scan_workspace(w)["repos"] == []


# --- CLI end-到-end ---------------------------------------------------------


def _out(capsys) -> str:
    return capsys.readouterr().out


def test_cli_workspace_init(tmp_path, capsys):
    root = tmp_path / "ws"
    assert main(["workspace", "init", "--root", str(root), "--json"]) == 0
    payload = json.loads(_out(capsys))
    assert payload["root"] == str(root)
    assert (root / ".cogos" / "tasks").is_dir()


def test_cli_task_flow(tmp_path, capsys):
    root = tmp_path / "ws"
    rc = main([
        "task", "create", "--root", str(root), "--title", "fix homepage",
        "--assignee", "claude_code", "--note", "kickoff", "--json",
    ])
    assert rc == 0
    created = json.loads(_out(capsys))
    assert created["id"] == "TASK-001"
    assert created["status"] == "pending"

    rc = main([
        "task", "update", "TASK-001", "--root", str(root),
        "--progress", "60", "--status", "in_progress", "--note", "layout done", "--json",
    ])
    assert rc == 0
    updated = json.loads(_out(capsys))
    assert updated["progress"] == 60
    assert updated["status"] == "in_progress"
    assert len(updated["history"]) == 2

    rc = main(["task", "list", "--root", str(root), "--json"])
    assert rc == 0
    items = json.loads(_out(capsys))
    assert [t["id"] for t in items] == ["TASK-001"]
    assert items[0]["assignee"] == "claude_code"

    rc = main(["task", "show", "TASK-001", "--root", str(root), "--json"])
    assert rc == 0
    shown = json.loads(_out(capsys))
    assert shown["title"] == "fix homepage"
    assert shown["current_file"] == ""


def test_cli_task_list_filter_and_missing(tmp_path, capsys):
    root = tmp_path / "ws"
    assert main(["task", "create", "--root", str(root), "--title", "a", "--assignee", "x"]) == 0
    assert main(["task", "create", "--root", str(root), "--title", "b", "--assignee", "y", "--status", "done"]) == 0
    _out(capsys)  # discard human-readable output
    assert main(["task", "list", "--root", str(root), "--status", "done", "--json"]) == 0
    assert [t["id"] for t in json.loads(_out(capsys))] == ["TASK-002"]
    assert main(["task", "show", "TASK-999", "--root", str(root)]) == 1
    assert "找不到任务" in capsys.readouterr().err


def test_cli_inbox_flow(tmp_path, capsys):
    root = tmp_path / "ws"
    rc = main([
        "inbox", "send", "--root", str(root), "--to", "claude_code",
        "--content", "please review src/index.html", "--type", "review_request",
        "--task-id", "TASK-001", "--from", "hermes", "--json",
    ])
    assert rc == 0
    sent = json.loads(_out(capsys))
    assert sent["to"] == "claude_code"
    assert sent["type"] == "review_request"
    assert sent["from"] == "hermes"

    rc = main(["inbox", "check", "--root", str(root), "--to", "claude_code", "--json"])
    assert rc == 0
    msgs = json.loads(_out(capsys))
    assert len(msgs) == 1
    assert msgs[0]["task_id"] == "TASK-001"
    assert msgs[0]["read"] is False

    # mark-读取 + unread-only roundtrip
    assert main(["inbox", "check", "--root", str(root), "--to", "claude_code", "--mark-read"]) == 0
    _out(capsys)  # discard human-readable output
    assert main(["inbox", "check", "--root", str(root), "--to", "claude_code", "--unread-only", "--json"]) == 0
    assert json.loads(_out(capsys)) == []


def test_cli_inbox_rejects_bad_recipient(tmp_path, capsys):
    root = tmp_path / "ws"
    assert main(["inbox", "send", "--root", str(root), "--to", "bad/id", "--content", "x"]) == 1
    assert "无效的 Agent id" in capsys.readouterr().err


def test_cli_lock_flow(tmp_path, capsys):
    root = tmp_path / "ws"
    rc = main(["lock", "acquire", "repo1/src/index.html", "--root", str(root),
               "--holder", "hermes", "--note", "refactor", "--json"])
    assert rc == 0
    lock = json.loads(_out(capsys))
    assert lock["holder"] == "hermes"
    assert lock["target"] == "repo1/src/index.html"

    assert main(["lock", "acquire", "repo1/src/index.html", "--root", str(root),
                 "--holder", "claude_code"]) == 1  # conflict
    assert "已被" in capsys.readouterr().err

    assert main(["lock", "status", "--root", str(root), "--json"]) == 0
    assert json.loads(_out(capsys))[0]["holder"] == "hermes"

    assert main(["lock", "release", "repo1/src/index.html", "--root", str(root),
                 "--holder", "hermes", "--json"]) == 0
    assert json.loads(_out(capsys))["released"] is True


def test_cli_lock_conflict_notifies_inbox(tmp_path, capsys):
    root = tmp_path / "ws"
    assert main(["lock", "acquire", "repo1/f.py", "--root", str(root), "--holder", "hermes"]) == 0
    rc = main(["lock", "acquire", "repo1/f.py", "--root", str(root),
               "--holder", "claude_code", "--notify", "claude_code"])
    assert rc == 1
    msgs = check_inbox(Workspace(root=root), to="claude_code")
    assert len(msgs) == 1
    assert msgs[0].type == "lock_conflict"
    assert "LOCK_CONFLICT" in msgs[0].content


def test_cli_scan(tmp_path, capsys):
    root = tmp_path / "ws"
    (root / ".cogos").mkdir(parents=True)
    (root / "repo1" / ".git").mkdir(parents=True)
    (root / "repo1" / "a.py").write_text("x", encoding="utf-8")
    assert main(["workspace", "scan", "--root", str(root), "--json"]) == 0
    payload = json.loads(_out(capsys))
    assert payload["repos"][0]["repo"] == "repo1"
