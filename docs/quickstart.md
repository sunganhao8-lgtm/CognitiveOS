# CognitiveOS v0.1 — Quick Start

This walks you through the first end-to-end run.

## Prerequisites

- Python 3.10+
- At least one of: Hermes, Claude Code, Codex, OpenClaw installed locally

## Install

```bash
git clone <repo>
cd CognitiveOS
pip install -e .
```

## Bootstrap

```bash
cogos bootstrap
```

Expected output (truncated):

```json
{
  "started_at": "...",
  "discovered": [{"agent_id": "hermes", ...}],
  "bootstrap_agent": "hermes",
  "harvested_files": 1603,
  "wiki_pages": 2,
  "dashboard": "D:\\...\\CognitiveOS\\dashboard\\index.html"
}
```

After it finishes, your default browser opens the dashboard.

## Where things go

| Path                            | What it contains                            |
|---------------------------------|---------------------------------------------|
| `knowledge/sources/<agent>/`    | Raw files harvested from each agent         |
| `knowledge/normalized/`         | Cross-agent index                           |
| `knowledge/wiki/`               | Human-readable Markdown wiki                |
| `dashboard/index.html`          | Self-contained HTML dashboard               |
| `.cogos/last_report.json`       | Machine-readable report of the last run     |

## Re-running

`cogos bootstrap` is idempotent. The sources tree is refreshed in
place, normalized and wiki layers are recomputed, and the dashboard is
re-rendered.

## Inspecting what was harvested

```bash
ls knowledge/sources/hermes/
ls knowledge/sources/hermes/profiles/
```

## Status without bootstrapping

```bash
cogos status
```

Prints the JSON of the most recent bootstrap run.

## Next steps

- Add more adapters (Claude Code, Codex, OpenClaw)
- Extend the normalizer to parse each agent's memory file format
- Wire the Kernel DESIGN into a runtime loop
- Replace the dashboard template with a richer one when v0.2 lands