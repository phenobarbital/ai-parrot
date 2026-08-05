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

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**:

**README.md** — file tree now lists `server_dev.py` / `static/dev.html`, plus a
two-consoles comparison table right after it (audience, port, intake,
CloudWatch, Jira, HITL) so a reader picks the right pair before reading
further. New **Development console** section covering: quickstart and the
"Redis is the only hard requirement" point (no `CLOUDWATCH_*`, no `JIRA_*`),
side-by-side operation, the topology diagram, the three intents with the exact
document each writes (light `.proposal.md` vs full `.brainstorm.md`), the
resume/extend policy and its collision behaviour, the full endpoint table, both
run payload shapes with curls, the normative `open_questions` protocol as 5
numbered steps, approve **and** reject curls, every status code (incl.
`400 answers_required` and `409 already_resolved`), the per-run plan-approval
override semantics, and the two new conf keys with a note that nothing else is
forked from `DEV_LOOP_*`. Explicitly records that revision mode stays unexposed.

**GUIA.md** — kept Spanish and in its "cómo lo arranco" register. Extended the
file tree, the script-comparison table (with a callout that the two consoles
coexist on 8080/8081) and the closing "qué ejecutar" table, plus a new **§9**
covering arranque, intent choice, and — the part a newcomer actually needs —
how to answer the Open Questions: partial answers are valid, bounded rounds,
what happens when the budget runs out (does **not** block), the run parking so
you can take hours, reject-aborts, fail-closed expiry ("el silencio no es un
'sí'"), and reload-mid-gate. Includes curl equivalents for both resolve
directions and for starting a run.

**Verification** — rather than writing from memory (the task's explicit
warning), I ran a cross-check script against the loaded `server_dev.py`:

- every mounted `/api/*` route is documented, and every documented route is
  mounted (7/7, incl. the gate-resolution route);
- every `/api/config` key the docs promise is actually emitted by
  `handle_config` (`ideation_max_rounds`, `gate_ttl_questions`,
  `require_plan_approval`, `qa_max_retries`, `development_pool_max`,
  `max_concurrent_runs`, `document_kinds`, `nl_kinds`,
  `gate_resolve_url_template`);
- the keys the docs claim are **absent** (`log_group`, `time_window_minutes`,
  `jira_project`) really are absent from the dev config;
- the documented NL payload is accepted verbatim by
  `_build_dev_brief_from_form`;
- the defaults quoted in the docs (`2` rounds, `86400` s) match `conf`.

All checks passed.

**Deviations from spec**: none. No code was touched; `documentation/` site
pages and docstrings were left alone as instructed.
