"""管家入职。

当你装上新的 AI Agent（「管家」）或换到新电脑，管家需要被告知
你是谁、你在意什么、什么是禁地。

``brief`` 读取与协议无关的 ``user/manifest.md``，把它渲染成*当前*
Agent 能直接消化的格式：

* ``--agent hermes``    -> 一行可粘到终端的 shell 命令（建会话并把 manifest 灌进去）
* ``--agent codex``     -> Codex 可以 ``cat`` 的项目文档
* ``--agent claude``    -> Claude Code 的 system prompt 前缀
* ``--agent raw``       -> 纯 manifest 文本，方便手动粘贴

各 Agent 的包装故意写得很少。智能全在 manifest 里，包装只是管子。
"""

from __future__ import annotations

from pathlib import Path

from .user import UserLayer


HEADER = (
    "[入职：你正被装为主人的 AI 管家。读完全文视作接受入职培训。"
    "主人不会再重复一遍。]"
)


def render_brief(user: UserLayer, agent: str) -> str:
    manifest = (user.root / "manifest.md").read_text(encoding="utf-8")
    preferences = (user.preferences).read_text(encoding="utf-8") if user.preferences.exists() else ""
    style = (user.style).read_text(encoding="utf-8") if user.style.exists() else ""

    body = "\n\n---\n\n## 偏好\n\n" + preferences + "\n\n---\n\n## 风格\n\n" + style + "\n\n---\n\n## 主人档案\n\n" + manifest

    agent = agent.lower()
    if agent == "raw":
        return HEADER + "\n\n" + body + "\n"

    if agent == "hermes":
        # Hermes 通过 `hermes chat -q "..."` 接收 prompt。我们把整段 brief
        # 压成一行、转义换行，这样主人可以原样把整条命令粘到任何终端。
        one_line = body.replace("\n", " \\n ").replace('"', '\\"')
        return (
            "# 把下面这条命令整条粘到你的终端，让 Hermes 完成入职：\n"
            "\n"
            f'hermes chat -q "{HEADER} {one_line}"\n'
        )

    if agent == "codex":
        target = user.root.parent / "AGENTS.md"
        return (
            f"# Codex 从 {target} 读项目文档。\n"
            f"# 把 brief 追加到该文件：\n\n"
            f"cat >> {target} <<'COGOS_BRIEF_EOF'\n"
            f"{HEADER}\n\n{body}\nCOGOS_BRIEF_EOF\n"
        )

    if agent == "claude":
        target = user.root.parent / "CLAUDE.md"
        return (
            f"# Claude Code 从 {target} 读取。\n"
            f"# 追加 brief：\n\n"
            f"cat >> {target} <<'COGOS_BRIEF_EOF'\n"
            f"{HEADER}\n\n{body}\nCOGOS_BRIEF_EOF\n"
        )

    raise ValueError(f"未知 agent：{agent!r}；可选：raw、hermes、codex、claude")