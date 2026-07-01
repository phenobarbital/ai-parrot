# TASK-1680: Document the `app.py` startup wiring for trigger_agent dispatch

**Feature**: FEAT-265 — JiraSpecialist trigger_agent → Orchestrator Dispatch
**Spec**: `sdd/specs/jiraspecialist-trigger-agent-orchestrator.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1678
**Assigned-to**: unassigned

---

## Context

FEAT-265 spec §3 Module 3 (resolved §8): the real dispatch is wired in the
**consuming project's `app.py`**, not in this pure repo (deployment runs a
separate project with `ai-parrot` installed; `agents/` here is gitignored and
is NOT the dispatch host). So this repo ships the API (TASK-1678) + a
copy-paste documentation snippet — NOT an in-repo wiring commit.

This task delivers that documentation so integrators know how to activate
`TRIGGER_AGENT` dispatch.

---

## Scope

- Add a short doc section showing how to wire the dispatcher at startup:
  ```python
  # in the consuming project's app.py, after both objects are constructed
  jira_agent.set_agent_dispatcher(orchestrator.execute_agent)
  ```
- Explain the degrade behaviour (without the call, `TRIGGER_AGENT` logs
  intent and returns `status="skipped"`).
- Note the v1 await-inline latency caveat (spec §8) and the layering rule
  (the wiring lives at the app edge because core cannot import the server).
- Place the doc near the existing Jira webhook docs (find the right file via
  grep; see References). If no suitable doc exists, add a new
  `docs/` page and link it from the webhook spec/doc.

**NOT in scope**: any code change to `parrot/` (handled by TASK-1678/1679);
committing a real `app.py` (lives in the consuming project, outside this repo).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/...jira webhook doc...` | MODIFY/CREATE | Add "Activating TRIGGER_AGENT dispatch" section + snippet |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / API referenced in the snippet
```python
# Public API added by TASK-1678:
jira_agent.set_agent_dispatcher(orchestrator.execute_agent)
# JiraSpecialist.set_agent_dispatcher — created in TASK-1678
# AutonomousOrchestrator.execute_agent — verified:
#   packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:406
```

### Existing references to locate the doc home
```
# search for the existing webhook documentation:
#   grep -ril "JiraWebhookHook\|jiraspecialist" docs/
#   spec: sdd/specs/jiraspecialist-webhooks.spec.md
```

### Does NOT Exist
- ~~an in-repo `app.py` that should host this wiring~~ — the dispatch host is
  the consuming project's `app.py`, outside this repo. Do NOT add the call to
  any file under `agents/` or invent a repo `app.py` wiring commit.
- ~~`status="triggered"`~~ — the documented degrade status is `"skipped"`.

---

## Implementation Notes

### Key Constraints
- Documentation only — no behavioural code.
- Keep the snippet consistent with the final API names from TASK-1678.
- Mention: dispatch is `await`ed inline in v1; verify latency vs Jira webhook
  timeout after rollout (spec §8).

### References in Codebase
- `sdd/specs/jiraspecialist-webhooks.spec.md` — sibling webhook feature
- `packages/ai-parrot/src/parrot/core/hooks/jira_webhook.py` — hook receiver

---

## Acceptance Criteria

- [ ] A doc section documents `set_agent_dispatcher(orchestrator.execute_agent)`
      placement in the consuming `app.py`.
- [ ] Degrade behaviour (`status="skipped"` when unwired) is documented.
- [ ] Layering rationale + await-inline latency caveat are noted.
- [ ] Snippet uses the exact API names shipped in TASK-1678.

---

## Test Specification

> Documentation task — no automated test. Verification = doc review:
> the snippet imports/calls resolve against the TASK-1678 API and the
> placement guidance is accurate.

---

## Agent Instructions

1. Confirm TASK-1678 is complete so the API names are final.
2. Locate the existing Jira webhook doc (grep); add the section there.
3. Keep it short and copy-pasteable.
4. Move this file to `sdd/tasks/completed/`; update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
