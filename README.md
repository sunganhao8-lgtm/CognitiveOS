# CognitiveOS

A Cognitive Runtime Layer for AI Agents.

[English](README.md) | [简体中文](README.zh-CN.md)

## Vision

Current AI agents are powerful but isolated.

Claude Code understands coding.
OpenClaw understands automation.
Codex understands engineering.
Hermes understands orchestration.

However, they lack:

- Shared memory
- Unified identity
- Experience accumulation
- Cognitive coordination

CognitiveOS aims to provide a cognitive layer for AI agents.

## Core Idea

CognitiveOS is not another AI agent.

It is local-first infrastructure that:

1. Discovers the AI agents already installed on your machine
2. Lets one of them (the **Bootstrap Agent**) help understand your environment
3. Builds a source-preserving, wiki-style knowledge base
4. Exposes the result through a local HTML Dashboard

## What v0.1 Does

```
$ pip install -e .
$ cogos bootstrap
```

This will:

1. Scan for installed agents (Hermes today; Claude Code / Codex / OpenClaw next).
2. Pick an available one as the **Bootstrap Agent**.
3. Let that agent analyze the local environment.
4. Copy raw data into `knowledge/sources/<agent>/`.
5. Normalize it into `knowledge/normalized/`.
6. Build a human-readable wiki in `knowledge/wiki/`.
7. Render `dashboard/index.html` and open it.

## Architecture

```
cogos/
  discovery/        find agents on this machine
  adapters/         uniform Agent interface (one impl per agent)
    hermes/         first adapter
  sources/           raw-source writers (preserve original layout)
  normalized/       cross-agent normal form
  knowledge/        wiki-style knowledge base
  dashboard/        HTML template + renderer
  bootstrap.py      orchestration pipeline
  cli.py            `cogos` entry point
```

Each layer has a single responsibility and can be replaced independently.
The data flow is always:

```
Raw Source → Normalized Document → Wiki Page
```

and every wiki page can be traced back to its source file.

## Principles

- **Local-first** — your data stays on your machine.
- **Agent-agnostic** — CognitiveOS does not belong to any agent.
- **Source-preserving** — every piece of knowledge traces back to a file.
- **Human-readable** — knowledge files are plain Markdown.
- **Machine-readable** — frontmatter keeps them queryable.
- **Modular** — discovery, adapter, dashboard are all swappable.
- **Progressive** — first bootstrap does the minimum; later runs extend it.
- **Open ecosystem** — third parties can register new adapters.

## Status

Experimental / Research Project.

Hermes adapter ships in v0.1. Other adapters are designed but not implemented.