---
type: Wiki Overview
title: 'TASK-1012: Write docs/web-hitl-frontend-brainstorm.md'
id: doc:sdd-tasks-completed-task-1012-frontend-brainstorm-doc-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task produces the brainstorm document for the frontend team that specifies
  what the `navigator-frontend-next` codebase must implement to support web HITL.
  The document is self-contained and serves as the input for the frontend's own SDD
  spec (§3 Module 9 in the spec).
---

# TASK-1012: Write docs/web-hitl-frontend-brainstorm.md

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task produces the brainstorm document for the frontend team that specifies what the `navigator-frontend-next` codebase must implement to support web HITL. The document is self-contained and serves as the input for the frontend's own SDD spec (§3 Module 9 in the spec).

This document does not require implementation of frontend code — only the backend brainstorm artifact.

---

## Scope

Create `docs/web-hitl-frontend-brainstorm.md` containing:

1. **Wire-Format Contract** — the exact JSON schemas for:
   - `hitl:question` WebSocket payload.
   - `hitl:cancel` WebSocket payload.
   - `POST /api/v1/agents/hitl/respond` request body.
   - HTTP response body (200, 400, 404).

2. **Interaction Type Mapping** — table of `interaction_type` (APPROVAL, SINGLE_CHOICE, MULTI_CHOICE, FORM, FREE_TEXT) → UI component (checkbox, radio buttons, checkboxes, form field, text input).

3. **Edge Cases & Resilience** — discussion of:
   - WebSocket disconnect during question delivery.
   - Timeout behavior.
   - Cancel/interruption.
   - Page reload.
   - Multiple concurrent interactions.
   - Difference in rendering between `HumanTool` vs `HandoffTool` interactions.

4. **Recommended File Layout** — suggested directory structure in `navigator-frontend-next` for HITL-related components.

5. **Minimal Component Sketch** — a brief pseudocode outline of `HitlPrompt.svelte` or equivalent component showing how to render and submit a question.

6. **Open Questions** — a list of decisions for the frontend author to address:
   - Modal vs. inline bubble presentation?
   - Theming and styling approach?
   - Accessibility requirements?
   - Telemetry / analytics?
   - Multi-respondent scenarios (future)?

All content is derived from the spec and intended to be self-contained and copyable to the frontend repo.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/web-hitl-frontend-brainstorm.md` | CREATE | Frontend brainstorm document for navigator-frontend-next. |

---

## Codebase Contract (Anti-Hallucination)

No code is written in this task — only markdown documentation. All wire formats and interaction types come from the spec §2 Data Models and §3 Module 1/2.

---

## Implementation Notes

### Pattern to Follow

Use the spec §2 Data Models as the authoritative source for JSON schemas. Quote line numbers from the spec (e.g., "per spec line 172–186") for traceability.

Write in clear, non-technical language suitable for frontend engineers unfamiliar with the backend HITL substrate. Use tables and examples.

### Key Constraints

- Document is read-only narrative — no code examples beyond pseudocode.
- All JSON schemas must be exact (copy from spec §2).
- Acknowledge limitations and known risks (e.g., long-poll timeout, WS disconnect recovery).
- Flag ambiguities as "open questions" rather than prescribing solutions.

---

## Acceptance Criteria

- [ ] `docs/web-hitl-frontend-brainstorm.md` exists.
- [ ] Document includes wire-format contract (JSON schemas for hitl:question, hitl:cancel, POST body).
- [ ] Document includes interaction_type → UI component mapping table.
- [ ] Document discusses edge cases: WS disconnect, timeout, cancel, reload, concurrent interactions, HumanTool vs. HandoffTool.
- [ ] Document recommends file layout / directory structure.
- [ ] Document includes a minimal `HitlPrompt.svelte` pseudocode sketch.
- [ ] Document lists open questions (modal vs. inline, theming, accessibility, telemetry, multi-respondent).
- [ ] Document is self-contained and suitable for copying to navigator-frontend-next.
- [ ] No linting errors: `ruff check docs/web-hitl-frontend-brainstorm.md` (or markdown linter).

---

## Test Specification

No tests — this is documentation. Verification is manual review by the spec author and frontend stakeholders.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context, especially §2 Data Models and §3 Module 9
2. **Check dependencies** — none; this is independent
3. **Create the document** — follow the Scope above
4. **Verify** — ensure all wire formats come directly from the spec
5. **Move this file** to `tasks/completed/TASK-1012-frontend-brainstorm-doc.md` (after review)
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-05
**Notes**: Created `docs/web-hitl-frontend-brainstorm.md` with all six required sections:
  1. Wire-format contract (hitl:question, hitl:cancel, POST body with error codes table)
  2. interaction_type to UI component mapping table with value types
  3. Edge cases: WS disconnect, timeout, cancel, reload, concurrent interactions, HumanTool vs HandoffTool
  4. Recommended file layout for navigator-frontend-next
  5. Minimal HitlPrompt.svelte pseudocode + api.ts and HITLManager.ts sketches
  6. Eight open questions (modal/inline, theming, accessibility, telemetry, multi-respondent, reload persistence, error recovery, HandoffTool UX)

**Deviations from spec**: None. Document exceeds minimum requirements with additional
backend source reference appendix and API client sketches.
