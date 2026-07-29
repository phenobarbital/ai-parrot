---
type: Wiki Overview
title: 'TASK-1078: End-to-end test + YAML fixture for the team_work_in_progress driving
  use case'
id: doc:sdd-tasks-completed-task-1078-e2e-team-work-in-progress-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 8, §5 Acceptance Criteria. This is the proof that the bundled
  feature actually delivers the driving use case: a user query *"¿en qué está trabajando
  el equipo de Jesús?"* lands an `EnrichedContext` whose `tool_result["in_progress_issues"]`
  contains the asking user'''
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.merger
  rel: mentions
- concept: mod:parrot.knowledge.ontology.mixin
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# TASK-1078: End-to-end test + YAML fixture for the team_work_in_progress driving use case

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1076, TASK-1077
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, §5 Acceptance Criteria. This is the proof that the bundled feature actually delivers the driving use case: a user query *"¿en qué está trabajando el equipo de Jesús?"* lands an `EnrichedContext` whose `tool_result["in_progress_issues"]` contains the asking user's OAuth-scoped Jira issues.

The test exercises every component end-to-end against an ArangoDB sandbox and a spied `JiraToolkit`. It is the regression net for the entire feature.

---

## Scope

- Create a YAML fixture pattern at `packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml` with the full `entity_extraction` + `authorization` + `tool_call` shape from the brainstorm's example YAML.
- Create the test file `packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py` with at least these scenarios:
  - `test_e2e_team_work_in_progress_happy_path` — full pipeline returns `ContextEnvelope.state="ok"` with `tool_result["in_progress_issues"]` populated by a spied `JiraToolkit.jira_search_issues`. Assert the spy received `_permission_context.user_id == "alice"` (NOT a service-account credential).
  - `test_e2e_ambiguous_name_returns_clarification` — fixture has two `Jesús` employees; `ambiguity_strategy=ask_user` → `ContextEnvelope(state="ambiguous", clarification.candidates=[...two...])`.
  - `test_e2e_denied_cross_department` — caller without `hr_manager` role queries another department's manager → `ContextEnvelope(state="denied", denial_reason=...)`.
  - `test_e2e_auth_required_deep_link` — spied `CredentialResolver` returns `None`; the toolkit raises `AuthorizationRequired(auth_url=...)`. Result is `ContextEnvelope(state="auth_required", auth_prompt.auth_url=...)`.
  - `test_e2e_cache_isolates_targets` — two users query the same pattern with different target IDs; the second call does NOT receive the first call's cached result.
- Use the existing ArangoDB test harness (check `tests/knowledge/test_ontology_integration.py` for the fixture pattern).
- Use a `JiraToolkit` mock/spy that records `_permission_context` kwargs.

**NOT in scope**:
- Any production code change — this task is tests + fixture only.
- Live Jira API calls — `JiraToolkit` is mocked.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml` | CREATE | YAML pattern with all three new sections. |
| `packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py` | CREATE | The 5 scenarios above + a 3-employee Employee graph fixture. |
| `packages/ai-parrot/tests/knowledge/conftest.py` | MODIFY (if exists) | Add reusable spied-toolkit fixture if it's reused elsewhere. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import ContextEnvelope         # NEW
from parrot.knowledge.ontology.merger import OntologyMerger          # merger.py:26
from parrot.knowledge.ontology.mixin import OntologyRAGMixin         # mixin.py:27
from parrot.auth.exceptions import AuthorizationRequired             # auth/exceptions.py:12
from parrot_tools.jiratoolkit import JiraToolkit                     # package: parrot-ai-tools
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/merger.py:26
class OntologyMerger:
    def merge(self, yaml_paths) -> MergedOntology: ...        # line 51

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
class JiraToolkit:
    async def jira_search_issues(                              # line 2291
        self, jql: str, start_at: int = 0,
        max_results: Optional[int] = 100,
        # ...
    ) -> JiraToolEnvelope: ...

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:    # line 866
        # Reads kwargs.get("_permission_context")  (line 878)
        # Reads perm_ctx.user_id, perm_ctx.channel  (lines 891-892)
        # Calls self.credential_resolver.resolve(channel, user_id)  (line 902)
```

### Does NOT Exist
- ~~`JiraToolkit.search_issues_jql`~~ — use `jira_search_issues`.
- ~~A built-in ArangoDB test fixture that auto-seeds employees~~ — verify the existing pattern in `test_ontology_integration.py` first; reuse or extend.

---

## Implementation Notes

### Pattern to Follow — YAML fixture

```yaml
# packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml
team_work_in_progress:
  description: In-progress Jira issues owned by direct reports of a named employee.
  trigger_intents:
    - en qué está trabajando el equipo de
    - qué hace el equipo de
    - issues in progress for the team of

  entity_extraction:
    target_employee:
      type: Employee
      resolver: fuzzy_name_match
      scope: same_tenant
      ambiguity_strategy: ask_user
      required: true

  authorization:
    rules:
      - rule: target_is_self
      - rule: target_in_management_chain
      - rule: has_role
        role: hr_manager

  query_template: |
    LET target = DOCUMENT(@target_employee_id)
    FOR teammate IN 1..1 INBOUND target._id @@reports_to
      RETURN {
        employee_id:     teammate.employee_id,
        name:            teammate.name,
        jira_account_id: teammate.jira_account_id,
        manager_name:    target.name
      }

  post_action: tool_call
  tool_call:
    toolkit: JiraToolkit
    method: jira_search_issues
    credential_mode: requesting_user
    parameters:
      jql: |
        project = TROC
        AND status = "In Progress"
        AND assignee in ({{ graph.team | jira_accounts }})
      fields: [summary, status, assignee, components, updated, priority]
      max_results: 50
    result_binding: in_progress_issues
    empty_team_behavior: short_circuit
```

### Pattern to Follow — happy path test

```python
async def test_e2e_team_work_in_progress_happy_path(
    arango_seeded_employees, jira_toolkit_spy, agent_with_full_pipeline,
):
    env = await agent_with_full_pipeline.ontology_process(
        query="¿en qué está trabajando el equipo de Jesús Lara?",
        user_context={"user_id": "alice", "channel": "telegram", "roles": ["hr_manager"]},
        tenant_id="acme",
    )
    assert env.state == "ok"
    assert "in_progress_issues" in (env.tool_result or {})
    # Confirm per-user OAuth path was used:
    perm_ctx = jira_toolkit_spy.last_permission_context
    assert perm_ctx.user_id == "alice"
    assert perm_ctx.channel == "telegram"
```

### Key Constraints

- Use the existing ArangoDB test harness/marker — do not invent a new one.
- The `JiraToolkit` mock MUST inherit from `JiraToolkit` (or `AbstractToolkit`) so `_pre_execute` is reachable; alternatively, register the mock under the same name in `ToolManager`.
- Cache-isolation test: the second user MUST hit the graph store again. Use a counter on the spied `OntologyGraphStore.execute_traversal` to assert call counts.
- Each scenario gets its own `tenant_id` to avoid Arango fixture leakage; or tear down between tests.

### References in Codebase

- `packages/ai-parrot/tests/knowledge/test_ontology_integration.py` — for the ArangoDB harness pattern.
- `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py` — for Mixin test patterns.

---

## Acceptance Criteria

- [ ] All 5 scenarios pass: `pytest packages/ai-parrot/tests/knowledge/test_entity_extraction_e2e.py -v`.
- [ ] `test_e2e_team_work_in_progress_happy_path` asserts `env.tool_result["in_progress_issues"]` AND `_permission_context.user_id == "alice"`.
- [ ] `test_e2e_auth_required_deep_link` asserts `env.auth_prompt["auth_url"]` is the deep-link URL the mocked `CredentialResolver.get_auth_url` returns.
- [ ] `test_e2e_cache_isolates_targets` asserts `graph_store.execute_traversal` call count grew between the two queries.
- [ ] No live network calls — the Jira spy intercepts every invocation.

---

## Test Specification

See "Pattern to Follow — happy path test" above. The 4 remaining scenarios mirror the same structure with different fixture state and assertions on `env.state` + the corresponding state field (`clarification`, `denial_reason`, `auth_prompt`).

---

## Agent Instructions

1. Read the spec.
2. Read `test_ontology_integration.py` to confirm the ArangoDB harness shape and reuse it.
3. Identify a viable `JiraToolkit` spy strategy (subclass + override OR `ToolManager` registration with a mock). Document the choice inline.
4. Implement the YAML fixture and the 5 scenarios.
5. Verify all acceptance criteria — run the full suite once with `-v`.
6. Move this file to `sdd/tasks/completed/`.
7. Update the per-spec index → `"done"` and set `completed_at` on the header.

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-05-11
**Notes**: Created YAML fixture at `packages/ai-parrot/tests/knowledge/fixtures/team_work_in_progress.yaml`
with entity_extraction + authorization + tool_call sections. Created 6 E2E tests in
`test_entity_extraction_e2e.py` covering: fixture loading, happy path with permission_context
verification, ambiguity clarification, cross-department denial, auth_required deep link, and
cache isolation. Spy strategy: lightweight `_ToolCallSpy` registered in a fake ToolManager
(avoids JiraToolkit import complexity). All 272 knowledge tests pass.
**Deviations from spec**: Used a `_ToolCallSpy` class instead of importing `JiraToolkit` —
this avoids credentials/env-var deps while still validating the full pipeline including
`_permission_context` forwarding. Documented in test inline comment.
