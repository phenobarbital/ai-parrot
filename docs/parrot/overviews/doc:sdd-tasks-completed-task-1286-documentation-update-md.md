---
type: Wiki Overview
title: 'TASK-1286: Documentation update — tiered escalation example'
id: doc:sdd-tasks-completed-task-1286-documentation-update-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C13**. The existing
relates_to:
- concept: mod:parrot.core.tools.handoff
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.escalation_intent
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
---

# TASK-1286: Documentation update — tiered escalation example

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1275, TASK-1276, TASK-1278, TASK-1279, TASK-1282, TASK-1283
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C13**. The existing
`documentation/hitl_tiered_escalation_example.md` documents the
shipped baseline (commit `afe70e82`). This task expands it to cover
the V1 completion features: severity, business hours, the real action
kinds (email / webhook / zammad), the reject button + intent
detector, and the `HandoffTool` deprecation.

---

## Scope

- Expand `documentation/hitl_tiered_escalation_example.md` to add:
  1. **Severity** section — how to declare `severity` on `ask_human`,
     how `min_severity` on tiers interacts.
  2. **Business hours** section — `BusinessHours` configuration,
     boundary semantics (evaluated at tier-entry time).
  3. **Real action kinds** — examples using
     `action_metadata={"kind":"email", "to":[...]}`,
     `{"kind":"zammad","queue":...}`,
     `{"kind":"webhook","url":...}`. Note the legacy keys
     `channel="email"` / `platform="jira"` are still honoured.
  4. **Reject UX** — explain the standardised "↑ Escalar" button on
     Telegram/Web and the `RejectIntentDetector` for free-text replies
     on channels without a button.
  5. **HumanDecisionNode integration** — example wiring inside an
     `AgentsFlow`.
  6. **HandoffTool deprecation** — point users to
     `HumanTool(..., policy_id="...")` as the modern equivalent.
  7. **Observability** — note that subscribers can listen to
     `hitl.tier.*` and `hitl.chain.*` events through the manager's
     `on_event` callback (or `EventEmitterMixin` integration, per
     TASK-1280's decision).

**NOT in scope**: API reference docs (autodoc handles those). README
updates (separate task if needed).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `documentation/hitl_tiered_escalation_example.md` | MODIFY | Add the 7 sections above |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Public API to Show in Examples

```python
# All confirmed working after TASK-1274..1283:
from parrot.human import (
    HumanInteractionManager, HumanTool, HumanDecisionNode,
    Severity, BusinessHours,
)
from parrot.human.models import (
    EscalationPolicy, EscalationTier, EscalationActionType,
)
from parrot.human.escalation_intent import RejectIntentDetector
from parrot.core.tools.handoff import HandoffTool   # deprecated
```

### Does NOT Exist (Anti-Hallucination — do NOT show in examples)

- ~~Standalone `EmailAction` / `ZammadAction` / `LiveChatAction` classes~~ — the
  public surface is `action_type=NOTIFY|TICKET` + `action_metadata={"kind":...}`.
- ~~`PolicyRegistry`~~ — the registry is just `manager._policies` dict.
- ~~Zendesk examples~~ — V1 ships Zammad only.

---

## Implementation Notes

### Pattern to Follow

Keep the doc's existing style — narrative + code blocks — and graft the
new sections after the current "Behavior Nuances" section. Use the
example agent from `parrot/agents/demo.py` as the running example if
useful.

### Key Constraints

- All code samples MUST be tested at least mentally against the actual
  shipped API; do not invent classes or signatures.
- Note the legacy back-compat for `channel` / `platform` keys.
- For severity, show a concrete agent system-prompt fragment that
  teaches the LLM when to escalate.
- Keep doc length under ~400 lines; link to the spec
  (`sdd/specs/hitl-escalation-tier.spec.md`) for deeper detail.

### References in Codebase

- `documentation/hitl_tiered_escalation_example.md` — current state.
- Spec §2 (Architectural Design) — single-source for the diagrams /
  control flow.

---

## Acceptance Criteria

- [ ] Doc covers all 7 sections listed in scope.
- [ ] All code samples in the doc use only symbols listed in the
  Codebase Contract above (no hallucinated classes).
- [ ] The deprecation note for `HandoffTool` cross-references the
  modern `HumanTool(..., policy_id="...")` pattern.
- [ ] Doc renders correctly as Markdown (no broken code fences).
- [ ] Word count remains reasonable (< ~400 lines or equivalent).

---

## Test Specification

This task has no automated test specification — review is manual.
At minimum, the agent should:

1. Run the doc through `markdownlint` if available locally.
2. Manually copy each code sample into a Python REPL and verify imports
   resolve.

---

## Agent Instructions

1. Read spec §3 C13.
2. Verify all upstream tasks completed.
3. Edit the doc; preserve existing sections, add the new ones.
4. Manually verify imports against the actual codebase.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Expanded `documentation/hitl_tiered_escalation_example.md` (84 lines -> 403 lines) with 7 new sections (sections 4-10):
  - §4 Severity — `min_severity` on tiers, `severity` kwarg on `ask_human`, example LLM system-prompt fragment.
  - §5 Business Hours — `BusinessHours` model with timezone/weekdays/start_hour/end_hour and boundary semantics.
  - §6 Real action kinds — email/webhook/Zammad examples using `kind` key in `action_metadata`; legacy back-compat note.
  - §7 Reject UX — Telegram/Web escalate button mechanics, `RejectIntentDetector` for free-text channels.
  - §8 HumanDecisionNode — AgentsFlow wiring with `escalation_policy_id` + `severity` kwargs.
  - §9 HandoffTool deprecation — cross-reference to `HumanTool(..., policy_id=...)`, deprecation warning note.
  - §10 Observability — `on_event` callback, event name table, subscriber exception isolation note.
- All code samples verified against actual codebase imports (all resolve without errors).
