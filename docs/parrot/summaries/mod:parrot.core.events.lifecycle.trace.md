---
type: Wiki Summary
title: parrot.core.events.lifecycle.trace
id: mod:parrot.core.events.lifecycle.trace
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: W3C Trace Context dataclass for lifecycle event propagation.
relates_to:
- concept: class:parrot.core.events.lifecycle.trace.TraceContext
  rel: defines
---

# `parrot.core.events.lifecycle.trace`

W3C Trace Context dataclass for lifecycle event propagation.

FEAT-176 — Lifecycle Events System.

This module implements the W3C Trace Context specification
(https://www.w3.org/TR/trace-context/) for distributed tracing across
agent, client, tool, and sub-agent (A2A) boundaries.

## Classes

- **`TraceContext`** — W3C Trace Context for OpenTelemetry-compatible distributed tracing.
