# CognitiveOS

A Cognitive Runtime Layer for AI Agents.

[中文](README.md) | [English](README.en.md)

> **The real differentiation**: CognitiveOS builds an Agent's *cognition of its master*, and separates that cognition from the Agent. "Cross-agent / cross-device / plain text" is the natural by-product of that separation (any import/export would do it). What's NOT replaceable is **actively observing the Agent's behaviour toward the master, distilling repeated feedback into structured rules, and updating the master profile over time** — the Agent cannot do this for itself (it cannot see itself).

## Have you felt these pains?

### Pain 1: Want to try a new AI agent, but afraid to switch 😰

You've accumulated a lot of memory in your current agent: your habits,
your preferences, the pitfalls you've hit, the context of hundreds of
projects.

Switching to a new agent = **starting from zero**. You'd have to
re-teach it "who you are, what you care about, what's off-limits".

The migration cost stops you from trying new products. **You're locked
in by your memory.**

### Pain 2: New computer = amnesia 🧠

You install the agent on a new machine. It doesn't know you.

It doesn't remember your projects, your decisions, the experience you
gained from months of trial and error.

Your "cognition" stays on the old machine. **New computer = amnesia.**

### Pain 3: The agent's memory is "its", not "yours" 🔒

Everything you accumulate in this agent stays with the agent.

When you stop using it, **that accumulation is gone** — like changing
butlers: what the butler remembers is the butler's business, not the
master's.

---

**CognitiveOS's answer: take "your cognition" out of the agent, and put
it in your own hands.**

## Vision

Current AI agents are powerful but isolated:

- Claude Code understands coding
- OpenClaw understands automation
- Codex understands engineering
- Hermes understands orchestration

Yet they lack: **shared memory, unified identity, experience accumulation,
cognitive coordination**.

CognitiveOS aims to provide a cognitive layer for AI agents — and that
layer belongs to the **user**, not to any agent.

## Core Idea

> AI agents are butlers; the user is the master. Previously, changing
> butlers or moving to a new machine meant re-explaining everything.
> CognitiveOS preserves the master's most valuable data — habits,
> thinking patterns, experience, preferences — so cognition migrates
> seamlessly when the master changes butlers, machines, or products.

CognitiveOS is not another AI agent. It is infrastructure that enables
agents to **remember, reason, collaborate, and improve**.

## What v0.1 Does

```bash
pip install -e .
cogos bootstrap        # discover agents → harvest → wiki → dashboard
cogos brief --agent X  # give a new butler the master's handoff packet
cogos persona fit      # train butler fit against real past Q&A
cogos export-user      # export the user/ layer (cross-device migration)
cogos import-user      # import the user/ layer
```

Open the generated `index.html` to see a clickable **cognitive map**
(brain-region diagram) plus your active projects, recent Q&A, and
available commands.

## Architecture

```
cogos/
  discovery.py      find installed AI agents
  adapters/         uniform Agent interface (Hermes first)
  kernel.py         Kernel orchestration loop (implements DESIGN.md)
  persona_fit.py    persona-fitting training (semantic-match scoring)
  conversations.py  extract real Q&A from Hermes session store
  portability.py    export/import of the user/ layer
  dashboard.py      generate index.html cognitive map
```

Data flow is always:

```
Raw Source → Normalized Document → Wiki Page
```

## The user/ Layer (core asset)

```
user/
  manifest.md       master handoff packet (first file a new butler reads)
  preferences.md    communication / output / tooling preferences
  style.md          decision style
  projects/         per-project tacit knowledge
  experience/       specific experiences worth remembering
  conversations/    historical Q&A pairs (extracted from agent stores)
  cognitive/        cross-device, cross-agent cognitive state
```

**These files belong to you, not to any agent.** Move machines or
switch agents — `user/` travels with you.

## Design Principles

- **Local-first** — your data stays on your machine
- **Agent-agnostic** — belongs to no single agent
- **Source-preserving** — every piece of knowledge traces to a file
- **Human-readable** — knowledge is plain Markdown
- **Machine-readable** — frontmatter keeps it queryable
- **Modular** — discovery, adapters, dashboard are swappable
- **Progressive** — first run does the minimum; later runs extend it
- **Open ecosystem** — third-party agents/adapters can plug in

## Roadmap

- **v0.1 Foundation**: architecture, agent discovery, user/ layer, cognitive map ✅
- **v0.2 Agent Integration**: more agents (Codex / Claude Code / OpenClaw)
- **v0.3 Reflection**: self-improvement loop (sleep cycle)
- **v1.0 Cognitive Runtime**: stable open ecosystem

## Status

Experimental / Research Project.

## Contributing

Welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).
