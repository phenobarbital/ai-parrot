---
type: Wiki Summary
title: parrot.flows.dev_loop
id: mod:parrot.flows.dev_loop
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dev-loop orchestration flow (FEAT-129).
relates_to:
- concept: mod:parrot.flows.dev_loop.config
  rel: references
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: references
- concept: mod:parrot.flows.dev_loop.flow
  rel: references
- concept: mod:parrot.flows.dev_loop.models
  rel: references
- concept: mod:parrot.flows.dev_loop.nodes.intent_classifier
  rel: references
- concept: mod:parrot.flows.dev_loop.runner
  rel: references
- concept: mod:parrot.flows.dev_loop.streaming
  rel: references
- concept: mod:parrot.flows.dev_loop.webhook
  rel: references
---

# `parrot.flows.dev_loop`

Dev-loop orchestration flow (FEAT-129).

An eight-node ``AgentsFlow`` (IntentClassifier → [BugIntake] → Research →
Development → QA → DeploymentHandoff → Close, with FailureHandler as the
failure/on-error terminal path) that takes a work brief and produces a PR
plus a Jira ticket transitioned to "Ready to
Deploy". See ``sdd/specs/dev-loop-orchestration.spec.md`` for the full
spec. Runs are hosted by :class:`DevLoopRunner`, which enforces the
``FLOW_MAX_CONCURRENT_RUNS`` cap.
