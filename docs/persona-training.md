# CognitiveOS Scheduled Persona Training

Trains the user persona model on idle time. Runs every 6 hours by
default. Each tick:

1. Picks one random experience from ``user/experience/``.
2. Asks Hermes to predict what the user would say/decide.
3. Logs prediction + reward + diff to ``user/persona/``.
4. If reward < 0.7, appends a candidate delta to ``user/persona/model.md``.

You can pause, replay, or inspect any run:

```bash
cogos persona list              # see available experiences
cogos persona train [--seed N]  # run one round now
cogos persona log --last 5     # see recent samples
cogos persona show             # see the current model
```

The model is hand-readable Markdown. Edit, revert, or delete entries
freely.

## Why this is not real RL

This pipeline records self-evaluations from the same LLM that
generated the predictions. That is a known unreliable signal (the
"self-rewarding" failure mode). The pipeline is structured so that
**real human ratings can be layered on top** — once you record a few
`reward = high/low` judgements yourself, those override the LLM's
self-reward and become the actual training signal.

For now, treat ``model.md`` as a journal of observations, not as a
ground-truth model.