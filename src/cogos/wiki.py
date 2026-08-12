"""Wiki generator.

每个 wiki page 是 a single Markdown 文件 under ``knowledge/wiki/`` 使用
YAML frontmatter that records where 该 knowledge came 来自. 该 pages
themselves 是 short 在 prose 用于 v0.1 — 该 goal 是 到 give 用户 a
navigable, 来源-traceable view 的 *what CognitiveOS now knows*.
"""

from __future__ import annotations

from pathlib import Path

from .paths import Paths


INDEX_PAGE = """---
标题: CognitiveOS Wiki
type: index
updated_at: {updated_at}
---

# CognitiveOS Wiki

This wiki 是 generated 来自 该 raw 来源们 under
[`knowledge/来源们/`](../来源们/). 每个 page below traces back 到
one 或 more 来源 文件们.

## Agents discovered 在本 运行

{agent_list}
"""


AGENT_PAGE = """---
标题: {agent_id}
type: Agent
source_dir: 来源们/{agent_id}/
file_count: {file_count}
updated_at: {updated_at}
---

# {agent_title}

文件们 harvested 来自 this Agent into `来源们/{agent_id}/`:

{file_list}
"""


def build_wiki(paths: Paths) -> int:
    """(Re)build 该 wiki; 返回 该 number 的 pages written."""
    wiki_root = paths.wiki
    wiki_root.mkdir(parents=True, exist_ok=True)

    sources_root = paths.sources
    agents = (
        sorted(p for p in sources_root.iterdir() if p.is_dir())
        if sources_root.exists()
        else []
    )

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    agent_lines: list[str] = []
    page_count = 0

    for agent_dir in agents:
        agent_id = agent_dir.name
        files = sorted(p for p in agent_dir.rglob("*") if p.is_file())
        rel_files = [str(p.relative_to(sources_root)) for p in files]

        page = AGENT_PAGE.format(
            agent_id=agent_id,
            agent_title=agent_id.title(),
            file_count=len(files),
            file_list="\n".join(f"- `{f}`" for f in rel_files) or "_(no files)_",
            updated_at=now,
        )
        (wiki_root / f"{agent_id}.md").write_text(page, encoding="utf-8")
        agent_lines.append(f"- [{agent_id}]({agent_id}.md) — {len(files)} files")
        page_count += 1

    index_page = INDEX_PAGE.format(
        updated_at=now,
        agent_list="\n".join(agent_lines) if agent_lines else "_No agents harvested yet._",
    )
    (wiki_root / "index.md").write_text(index_page, encoding="utf-8")
    page_count += 1

    return page_count