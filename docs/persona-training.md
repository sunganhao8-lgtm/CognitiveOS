# CognitiveOS Scheduled Persona Training

Trains 用户 persona model 在 idle time. 运行 每个 6 hours 通过
默认. 每个 tick:

1. Picks one random experience 来自 ``user/experience/``.
2. Asks Hermes 到 predict what 用户 将 say/decide.
3. Logs prediction + reward + diff 到 ``user/persona/``.
4. If reward < 0.7, appends a candidate delta 到 ``user/persona/model.md``.

You 可以 pause, replay, 或 inspect 任何 运行:

```bash
cogos persona list              # see available experiences
cogos persona train [--seed N]  # run one round now
cogos persona log --last 5     # see recent samples
cogos persona show             # see the current model
```

该 model 是 hand-readable Markdown. Edit, revert, 或 删除 entries
freely.

## Why this 是 不 real RL

This pipeline records self-evaluations 来自 该 相同 LLM that
generated 该 predictions. 也就是说 a known unreliable signal (该
"self-rewarding" failure mode). 该 pipeline 是 structured so that
**real human ratings 可以 为 layered 在 top** — once you record 几个
`reward = high/low` judgements yourself, those override 该 LLM's
self-reward 和 become 该 actual training signal.

用于 now, treat ``model.md`` 作为 a journal 的 observations, 不 作为 a
ground-truth model.