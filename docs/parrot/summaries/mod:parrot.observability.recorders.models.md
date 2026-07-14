---
type: Wiki Summary
title: parrot.observability.recorders.models
id: mod:parrot.observability.recorders.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UsageRecord — the normalized, PII-free record shared by all usage recorders.
relates_to:
- concept: class:parrot.observability.recorders.models.UsageRecord
  rel: defines
---

# `parrot.observability.recorders.models`

UsageRecord — the normalized, PII-free record shared by all usage recorders.

A single ``UsageRecord`` is built per successful LLM call by
``UsageRecordingSubscriber`` from an ``AfterClientCallEvent`` plus an optional
``CostCalculator`` result, then fanned out to every configured
``AbstractLogger`` backend.

Privacy: this record carries NO prompt/completion content and NO
``user_id``/``session_id`` — only provider/model identifiers, token counts,
cost, timing, and a correlation ``trace_id``. This preserves the observability
PII contract (see ``observability/README.md``).

## Classes

- **`UsageRecord(BaseModel)`** — Normalized usage/token/cost record for one LLM API call.
