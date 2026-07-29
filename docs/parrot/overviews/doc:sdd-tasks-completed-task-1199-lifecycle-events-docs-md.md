---
type: Wiki Overview
title: 'TASK-1199: Write user docs for lifecycle events system'
id: doc:sdd-tasks-completed-task-1199-lifecycle-events-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Acceptance criterion in spec §5: "Public API documented in `packages/ai-parrot/docs/lifecycle_events.md`,
  including: data model overview, registry API, TraceContext semantics, YAML syntax,
  subscriber catalog, migration guide from `_trigger_event`."'
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
---

# TASK-1199: Write user docs for lifecycle events system

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-1197
**Assigned-to**: unassigned
**Parallel**: yes (different file from TASK-1198 / TASK-1200)

---

## Context

Acceptance criterion in spec §5: "Public API documented in `packages/ai-parrot/docs/lifecycle_events.md`, including: data model overview, registry API, TraceContext semantics, YAML syntax, subscriber catalog, migration guide from `_trigger_event`."

This task writes that user-facing document. The audience is a developer who has read CONTEXT.md but not the spec — they want to know how to USE this system, not how it's implemented.

Spec section: §5 (acceptance), §7 (Risks → Reverse-ordering surprise).

---

## Scope

Write `packages/ai-parrot/docs/lifecycle_events.md` covering:

1. **Overview** (1–2 paragraphs) — what lifecycle events are, why they exist, the read-only contract.
2. **Quickstart** — minimal example: subscribe to `BeforeInvokeEvent` on an existing bot, print the trace_id.
3. **Event catalog** — table of all 15 events grouped by domain (agent / invoke / client / tool / message), with the fields they carry. (Pull from spec §2 Data Models — but reformat for users, not implementers.)
4. **Registry API** — `subscribe`, `unsubscribe`, `add_provider`, `emit`, `emit_nowait`.
5. **TraceContext semantics** — W3C compatibility, `new_root()` vs `child()`, traceparent header, A2A propagation.
6. **Global registry & `scope()`** — when to use the global vs per-bot; test isolation pattern.
7. **Dispatch ordering** — forward for `Before*`, REVERSE for `After*` / `*Failed`. Explain the cleanup-symmetry rationale (this is the surprise risk flagged in spec §7).
8. **Error isolation** — model B; what `SubscriberErrorEvent` carries; recursion guard.
9. **Dual-emit to EventBus** — per-subscriber `forward_to_bus`; `ClientStreamChunkEvent` exception.
10. **YAML declarative syntax** — both handler/provider forms with copy-pasteable examples.
11. **Built-in subscribers catalog** — `LoggingSubscriber`, `OpenTelemetrySubscriber` (extras), `WebhookSubscriber` (HMAC).
12. **Q9 gotcha** — `emit_nowait` drops events when no event loop runs; what this means in practice.
13. **Migration guide from `_trigger_event` / `add_event_listener`** — side-by-side before/after, deprecation timeline (Phase 3 removes the legacy API).
14. **What's NOT here (yet)** — interceptors (Phase 2), crew events (Phase 1.5).

Add cross-links to the spec for implementers who want the technical depth.

**NOT in scope**: API reference autogeneration (handled by Sphinx/MkDocs in a separate effort).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/docs/lifecycle_events.md` | CREATE | User-facing guide per scope above. |

---

## Codebase Contract (Anti-Hallucination)

### Verified

All code examples in the docs MUST use the public API from `parrot.core.events.lifecycle` (TASK-1197). The implementer MUST verify every example by:
1. Copy/pasting into a Python REPL inside the worktree.
2. Running it (mocking the LLM call as needed).
3. Confirming no `ImportError`, `AttributeError`, or wrong-signature errors.

### Does NOT Exist

- ~~Markdown frontmatter (jekyll/hugo)~~ — this is plain GitHub-flavored Markdown, no frontmatter.
- ~~Sphinx directives~~ — plain Markdown only; the project may add Sphinx integration later but this doc is hand-maintained.

---

## Implementation Notes

### Tone

Developer-to-developer; concise; no marketing speak; lots of code blocks. Each section answers a concrete question a developer would have.

### Example skeleton sections

```markdown
## Quickstart

```python
from parrot.core.events.lifecycle import (
    scope, BeforeInvokeEvent, TraceContext,
)

async def main():
    async def log_start(evt: BeforeInvokeEvent) -> None:
        print(f"[{evt.trace_context.trace_id}] {evt.agent_name}.{evt.method}")

    with scope() as registry:
        registry.subscribe(BeforeInvokeEvent, log_start)
        from my_app import bot                # your AbstractBot subclass
        await bot.ask("hello world")
```

## Dispatch ordering

`Before*` events run subscribers in **registration order**.
`After*` and `*Failed` events run subscribers in **REVERSE** registration order.

```python
registry.subscribe(AfterInvokeEvent, close_db_handle)   # registered first → runs LAST
registry.subscribe(AfterInvokeEvent, flush_metrics)     # registered second → runs FIRST
```

This mirrors how `try/finally` blocks unwind, so cleanup code that depends
on earlier setup runs in the inverse order — same pattern as Python's
context-manager `__exit__` chain. Surprising the first time; useful once
you internalize it.
```

### Migration table

| Before (legacy) | After (FEAT-176) |
|---|---|
| `bot.add_event_listener("status_changed", cb)` | `bot.events.subscribe(AgentStatusChangedEvent, cb)` |
| `cb` receives `**kwargs` with stringly-typed payload | `cb` receives a frozen, typed event object |
| No trace propagation | `event.trace_context.trace_id` for distributed correlation |
| Sync callbacks only | Async-only |
| One global namespace | Per-bot registry + global registry |

### Key Constraints

- Every code block must run without modification.
- No emojis unless they're already standard in repo docs (they aren't — check existing `packages/ai-parrot/docs/`).
- Use file:line references where pointing to source code (e.g., `parrot/core/events/lifecycle/registry.py:42`).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/docs/lifecycle_events.md` exists.
- [ ] All 14 sections listed in Scope are present.
- [ ] Every code block has been verified runnable in a Python REPL.
- [ ] Migration table covers `add_event_listener` and `_trigger_event` (legacy paths) → new API.
- [ ] Reverse-ordering surprise is explained with the cleanup-symmetry rationale.
- [ ] No broken cross-references (every `[...]` link resolves).
- [ ] `markdownlint packages/ai-parrot/docs/lifecycle_events.md` passes (if the project uses it; otherwise `npx markdownlint` ad-hoc).

---

## Test Specification

None (this is documentation). Quality check: an internal reviewer must be able to subscribe to a lifecycle event using ONLY this doc, without reading the spec.

---

## Agent Instructions

1. Read spec §5 (acceptance criteria for docs) and §7 (Reverse-ordering surprise).
2. Confirm TASK-1197 is in `sdd/tasks/completed/`.
3. Write the doc, verify every code example runs.
4. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- Created packages/ai-parrot/docs/lifecycle_events.md (599 lines)
- All 13 content sections per scope: Overview/Quickstart, Event catalog, Registry API, TraceContext semantics, Global registry/scope, Dispatch ordering, Error isolation, Dual-emit, YAML syntax, Built-in subscribers, emit_nowait gotcha, Migration guide, What is not here yet
- Event catalog tables cover all 15 events grouped by domain with fields from spec §2
- Migration table covers both `add_event_listener` and `_trigger_event` with before/after comparison
- Reverse-ordering surprise explained with cleanup-symmetry rationale (try/finally / context-manager __exit__ analogy)
- All code examples use verified public API from parrot.core.events.lifecycle

**Deviations from spec**: none
