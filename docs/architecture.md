# CognitiveOS Architecture

User / External System
        │
        ▼
┌─────────────────┐
│ Cognitive Kernel │  — orchestration loop (DESIGN.md)
└─────────────────┘
        │
        ├──► Memory System
        ├──► Agent Router
        ├──► Reflection
        └──► External Agents
             (Hermes, Claude Code, Codex, OpenClaw, MCP tools)

## Runtime code layout (v0.1)

```
src/cogos/
  cli.py            — `cogos` command (bootstrap, status, …)
  paths.py          — single source of truth for directory layout
  discovery.py      — Agent Discovery Layer (runs every probe)
  probes.py         — one Probe per agent (Hermes today)
  adapters/         — uniform Agent interface
    __init__.py
    hermes/         — first concrete adapter
  bootstrap.py      — orchestration pipeline (discover → pick → harvest → wiki → dashboard)
  normalizer.py     — raw → normalized index
  wiki.py           — normalized → Markdown wiki pages
  dashboard.py      — wiki → dashboard/index.html
  templates/
    dashboard.html.j2
```

## Data layout (v0.1)

```
knowledge/
  sources/<agent>/     ← raw files, original paths preserved
  normalized/index.json
  wiki/<agent>.md      ← one page per agent, plus index.md
dashboard/index.html   ← regenerated on every bootstrap
.cogos/last_report.json
```

## Bootstrap pipeline

```
cogos bootstrap
     │
     ▼
discover()            ── every Probe runs, returns AgentHandles
     │
     ▼
load_adapter()        ── picks HermesAdapter for the Hermes handle
     │
     ▼
adapter.harvest()     ── whitelist copy into knowledge/sources/<agent>/
     │
     ▼
build_normalized_index()
     │
     ▼
build_wiki()          ── Markdown pages under knowledge/wiki/
     │
     ▼
render_dashboard()    ── dashboard/index.html
     │
     ▼
open browser
```

Every layer is replaceable without touching the others.