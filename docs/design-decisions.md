# Architecture Decisions

This file records key design decisions for CognitiveOS.

Each decision should describe:

- Context
- Options considered
- Decision
- Consequences

---

## DEC-001 — Package layout: `src/cogos/`

**Context.** We needed a clear namespace for CognitiveOS code that is
distinct from the project's directory name.

**Decision.** All runtime code lives under `src/cogos/`. The CLI entry
point `cogos` is exposed via `pyproject.toml` `[project.scripts]`.

**Consequences.** Tests can import `cogos` cleanly, and `pip install -e .`
makes the command available system-wide.

---

## DEC-002 — Agent discovery is a list of probes, not a switch statement

**Context.** Adding a new agent (Codex, Claude Code, OpenClaw, …) must
not require editing a central dispatcher.

**Decision.** Each agent is discovered by a small `Probe` function in
`cogos.probes`. `discovery.discover()` runs every probe and unions the
results.

**Consequences.** Adding a new adapter = one new probe + one adapter
module. No central code is touched.

---

## DEC-003 — Adapters are the only place that knows agent internals

**Context.** Agents store their state in wildly different ways.

**Decision.** A single `Adapter` protocol (`describe / harvest /
bootstrap_query`) hides every implementation detail.

**Consequences.** Discovery, normalization, and the dashboard never
import an agent-specific module. Replacing the Hermes adapter with a
Codex adapter requires no changes outside `cogos/adapters/<agent>/`.

---

## DEC-004 — Three-layer knowledge base (sources / normalized / wiki)

**Context.** The user explicitly required raw data to remain traceable
and the structure itself to convey meaning.

**Decision.** Every harvested file is stored verbatim under
`knowledge/sources/<agent>/`. A normalizer produces
`knowledge/normalized/index.json`. A wiki renderer produces one Markdown
page per agent under `knowledge/wiki/`.

**Consequences.** Any wiki page can be traced back to a source file by
following the path recorded in its frontmatter. No piece of knowledge
exists without provenance.

---

## DEC-005 — Hermes whitelist in v0.1 (no caches, no auth, no sessions)

**Context.** A naive "copy everything" harvest picked up `state.db`,
`auth.json`, session JSONLs, cache directories, and the profiles
`.git/` history. These are runtime state and credentials, not knowledge.

**Decision.** `HermesAdapter.SAFE_TOP_LEVEL` and
`SAFE_PROFILE_FILES` are explicit whitelists. Cache, auth, sessions,
state.db, logs, and `.git/` are never copied.

**Consequences.** Bootstrap reports `~1600` skill files plus a handful
of `*.md` / `config.yaml`. The user can audit the harvested set
quickly, and no credentials ever leave the Hermes install.

---

## DEC-006 — Dashboard is local HTML, no framework

**Context.** The user asked for a self-contained, local-first interface
that an AI agent can rewrite easily.

**Decision.** `dashboard/index.html` is rendered from a Jinja2 template
plus a single embedded `<style>` block. No React, no Vue, no CDN.

**Consequences.** The dashboard works offline, is one file, and can be
regenerated or hand-edited without a build step.

---

## DEC-007 — Single-process v0.1

**Context.** Distributed and multi-process concerns are out of scope.

**Decision.** v0.1 is single-process. The bootstrap pipeline runs top to
bottom in one Python invocation.

**Consequences.** Simpler debugging, simpler reasoning about state, and
zero infrastructure dependencies. Multi-process is a v1.x concern.