"""Wiki generator.

Each wiki page is a single Markdown file under ``knowledge/wiki/`` with
YAML frontmatter that records where the knowledge came from. The pages
themselves are short on prose for v0.1 — the goal is to give the user a
navigable, source-traceable view of *what CognitiveOS now knows*.
"""

from __future__ import annotations

from pathlib import Path

from .paths import Paths


INDEX_PAGE = """---
title: CognitiveOS Wiki
type: index
updated_at: {updated_at}
---

# CognitiveOS Wiki

This wiki is generated from the raw sources under
[`knowledge/sources/`](../sources/). Every page below traces back to
one or more source files.

## Agents discovered in this run

{agent_list}
"""


AGENT_PAGE = """---
title: {agent_id}
type: agent
source_dir: sources/{agent_id}/
file_count: {file_count}
updated_at: {updated_at}
---

# {agent_title}

Files harvested from this agent into `sources/{agent_id}/`:

{file_list}
"""


def build_wiki(paths: Paths) -> int:
    """(Re)build the wiki; return the number of pages written."""
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