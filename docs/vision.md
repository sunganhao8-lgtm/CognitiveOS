# CognitiveOS Vision

## Problem

Today's AI agents:

- Have fragmented memory
- Lack long-term identity
- Cannot share experiences
- Repeat similar mistakes

## Hypothesis

Future AI systems may require:

not only larger models,

but better cognitive architectures.

## Inspiration

Human intelligence contains:

- memory system
- planning system
- specialized abilities
- reflection mechanism

CognitiveOS explores similar software abstractions.

## What CognitiveOS Is

CognitiveOS is **local-first infrastructure** that:

1. Discovers AI agents already installed on the user's machine.
2. Lets one of them act as the **Bootstrap Agent** to interpret the local environment.
3. Builds a **source-preserving, wiki-style knowledge base** with three layers:
   `sources/ → normalized/ → wiki/`.
4. Exposes the result through a self-contained **HTML Dashboard**.

## What CognitiveOS Is Not

- Not another AI agent.
- Not a cloud service.
- Not a single-agent plugin.
- Not a paper-only research prototype.
- Not a forced 1:1 brain-anatomy mapping.

## Status

Experimental / Research Project · v0.1 ships with a working Hermes
adapter and bootstrap pipeline; other adapters are designed but not
implemented yet.