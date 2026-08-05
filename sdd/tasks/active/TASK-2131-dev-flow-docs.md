# TASK-2131: Documentation — README/GUIA for the dev console + gate protocol

**Feature**: FEAT-412 — Dev-Flow: SDD-Oriented AgentsFlow for Feature Development
**Spec**: `sdd/specs/sdd-dev-flow.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2129, TASK-2130
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. The examples folder now ships TWO server/UI pairs; the
docs must say when to use which, how the `open_questions` HITL protocol
works, and which conf keys are new.

---

## Scope

- Update `examples/dev_loop/README.md`:
  - New section for `server_dev.py` + `dev.html`: purpose (development
    console vs operations console), endpoints incl. the gate-resolve route
    and its request body (`resolution`, `resolved_by`, `comment`,
    `answers`), the three intents, the ideation stage and its
    document outputs (`.brainstorm.md` vs light `.proposal.md`),
    resume/extend policy, the dev-flow topology diagram, default port 8081.
  - Conf table additions: `DEV_FLOW_IDEATION_MAX_ROUNDS`,
    `DEV_FLOW_GATE_TTL_QUESTIONS`; note the per-run `require_plan_approval`
    override.
- Update `examples/dev_loop/GUIA.md` (Spanish, "cómo lo arranco" style):
  add the dev-console quickstart (run side-by-side with server.py, answer
  Open Questions in the browser, end with a draft PR) and update the
  folder-contents listing (server_dev.py, static/dev.html).

**NOT in scope**: code changes; `documentation/` site pages; docstrings
(owned by their tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/README.md` | MODIFY | Dev console section + conf keys |
| `examples/dev_loop/GUIA.md` | MODIFY | Spanish quickstart + file listing |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```
# examples/dev_loop/README.md — full endpoint/payload reference style
# examples/dev_loop/GUIA.md — verified 2026-08-05: sections
#   "1. Qué hay en esta carpeta" (file tree to extend),
#   "2. Setup común" (uv sync + venv), per-script run options table.
# Document EXACTLY what TASK-2129/2130 shipped — read server_dev.py's
# routes and /api/config keys before writing; do not document from memory.
```

### Does NOT Exist
- ~~revision-mode exposure in either server~~ — do not document it as a
  server feature (it remains library/e2e_demo only).
- ~~LLM intent classification~~ — the docs must present the intent as a
  user choice in the UI.

---

## Implementation Notes

### Key Constraints
- GUIA.md stays in Spanish and keeps its pragmatic tone; README.md is the
  exhaustive reference (existing division of labor stated in GUIA.md's
  header).
- Include a copy-pasteable `curl` example for resolving an
  `open_questions` gate.

---

## Acceptance Criteria

- [ ] README documents server_dev endpoints, gate protocol (with curl example), intents, conf keys, port 8081
- [ ] GUIA has the Spanish quickstart + updated file tree
- [ ] Every documented route/payload verified against the shipped server_dev.py

---

## Test Specification

> Docs task — verification is the acceptance checklist above (cross-check
> against `server_dev.py` routes and `/api/config` output).

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2129, TASK-2130 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/sdd-dev-flow.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`,
   update index → `"done"`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
