---
type: Wiki Summary
title: parrot.eval.rollout
id: mod:parrot.eval.rollout
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Rollout strategies and user simulators for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.rollout.ConversationalRollout
  rel: defines
- concept: class:parrot.eval.rollout.LLMUserSimulator
  rel: defines
- concept: class:parrot.eval.rollout.RolloutStrategy
  rel: defines
- concept: class:parrot.eval.rollout.SingleTurnRollout
  rel: defines
- concept: class:parrot.eval.rollout.UserSimulator
  rel: defines
- concept: mod:parrot.bots.abstract
  rel: references
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.eval.models
  rel: references
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.rollout`

Rollout strategies and user simulators for the Generic Agent Evaluation Harness.

FEAT-217 — Module 5.

Rollout strategies drive an agent against a task inside a sandbox and
return a ``Trajectory``.  User simulators generate user-side turns for
conversational (τ-bench style) evaluations.

Provided implementations:
- ``SingleTurnRollout`` — one ``bot.ask()`` call; suitable for
  single-shot toolkit agents.
- ``ConversationalRollout`` — iterative ``bot.conversation()`` loop driven
  by a ``UserSimulator``; suitable for multi-turn agents.
- ``LLMUserSimulator`` — calls ``client.ask()`` to generate synthetic user
  turns (τ-bench style, temperature = 0 for reproducibility).

## Classes

- **`UserSimulator(ABC)`** — Abstract user-side simulator for conversational rollouts.
- **`LLMUserSimulator(UserSimulator)`** — User simulator backed by an LLM (``AbstractClient.ask()``).
- **`RolloutStrategy(ABC)`** — Abstract strategy for driving an agent through a task.
- **`SingleTurnRollout(RolloutStrategy)`** — One-shot rollout: a single ``bot.ask()`` call.
- **`ConversationalRollout(RolloutStrategy)`** — Multi-turn rollout that loops ``bot.conversation()`` against a simulator.
