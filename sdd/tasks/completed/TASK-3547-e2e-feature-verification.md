# TASK-3547: Freeze feature plan and integrated evidence regression scenarios

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3545, TASK-3546, TASK-3548
**Assigned-to**: unassigned
**Module**: M5/M9
**Spec acceptance criteria**: AC7, AC8, AC9, AC17

---

## Context

Implement the M5/M9 deliverable **Freeze feature plan and integrated evidence regression scenarios** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Adopt the decomposition-generated canonical plan embedded below; validate all frozen node IDs against integrated collection before committing it. Add matching e2e: required metadata and frozen scenario IDs to this feature spec in the same implementation commit. This activates the already-approved required scenario intent; without that metadata the compatibility default is optional and the generated plan is not yet runnable.
- Add real runner/verify rejection scenarios for source/log tampering, required skips and cleanup failures; keep evidence writer independent of exploration.
- Execute the canonical plan on the integrated revision after the plan commit; retain immutable evidence outside source identity exclusions only.
- Confirm both closeout paths and no-server/no-E2E compatibility; do not stamp success for absent live/browser prerequisites.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/e2e/test_evidence.py` | CREATE | Targeted test coverage |
| `sdd/state/FEAT-581/e2e-plan.md` | CREATE | Task-owned deliverable |
| `sdd/specs/agentic-e2e-testing.spec.md` | MODIFY | Task-owned deliverable |
| `tests/sdd_scripts/test_feat581_plan.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

This module is new. No existing project symbol is required beyond standard library and already-declared Pydantic/YAML/pytest dependencies. Its field and outcome contracts come from spec §2.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3545 (`sdd/tasks/active/TASK-3545-e2e-ci.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3546 (`sdd/tasks/active/TASK-3546-e2e-docs-performance.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3548 (`sdd/tasks/active/TASK-3548-e2e-browser-scenarios.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

- `sdd/specs/agentic-e2e-testing.spec.md` current SHA-256: `4c939de5d780c3ca57f2ccae88650e5600ffe8dbf85e91fc5ea36ff2e9ade9c4`; re-read at execution because other features may change it.

### Does NOT Exist

- The new E2E harness and run/verify machinery do not exist at decomposition time;
  dependent task outputs are not pre-existing imports.
- No `E2ECriterion`, universal agent `/mcp/info`, reliable cookie session backend,
  or automatic provider-wide request budget may be assumed.
- Eligibility annotations are not Delegation Contracts. This task follows normal
  implementation routing until a complete validated code packet is authored.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/e2e/test_evidence.py",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-581/e2e-plan.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/specs/agentic-e2e-testing.spec.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_feat581_plan.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3547 owns its declared files for M5/M9. TASK-3545 supplies add deterministic nightly and explicit live ci plans; TASK-3546 supplies document operations and measure opt-in full profile; TASK-3548 supplies exercise owned browser navigation console and network behavior. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Adopt the decomposition-generated canonical plan embedded below; validate all frozen node IDs against integrated collection before committing it. Add matching e2e: required metadata and frozen scenario IDs to this feature spec in the same implementation commit. This activates the already-approved required scenario intent; without that metadata the compatibility default is optional and the generated plan is not yet runnable.
2. Add real runner/verify rejection scenarios for source/log tampering, required skips and cleanup failures; keep evidence writer independent of exploration.
3. Execute the canonical plan on the integrated revision after the plan commit; retain immutable evidence outside source identity exclusions only.
4. Confirm both closeout paths and no-server/no-E2E compatibility; do not stamp success for absent live/browser prerequisites.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `packages/ai-parrot-server/tests/e2e/test_evidence.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.
### `sdd/state/FEAT-581/e2e-plan.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Adopt the decomposition-generated canonical plan embedded below; validate all frozen node IDs against integrated collection before committing it. Add matching e2e: required metadata and frozen scenario IDs to this feature spec in the same implementation commit. This activates the already-approved required scenario intent; without that metadata the compatibility default is optional and the generated plan is not yet runnable.

2. Add real runner/verify rejection scenarios for source/log tampering, required skips and cleanup failures; keep evidence writer independent of exploration.

3. Execute the canonical plan on the integrated revision after the plan commit; retain immutable evidence outside source identity exclusions only.

4. Confirm both closeout paths and no-server/no-E2E compatibility; do not stamp success for absent live/browser prerequisites.
### `sdd/specs/agentic-e2e-testing.spec.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Adopt the decomposition-generated canonical plan embedded below; validate all frozen node IDs against integrated collection before committing it. Add matching e2e: required metadata and frozen scenario IDs to this feature spec in the same implementation commit. This activates the already-approved required scenario intent; without that metadata the compatibility default is optional and the generated plan is not yet runnable.

2. Add real runner/verify rejection scenarios for source/log tampering, required skips and cleanup failures; keep evidence writer independent of exploration.

3. Execute the canonical plan on the integrated revision after the plan commit; retain immutable evidence outside source identity exclusions only.

4. Confirm both closeout paths and no-server/no-E2E compatibility; do not stamp success for absent live/browser prerequisites.
### `tests/sdd_scripts/test_feat581_plan.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Adopt the decomposition-generated canonical plan embedded below; validate all frozen node IDs against integrated collection before committing it. Add matching e2e: required metadata and frozen scenario IDs to this feature spec in the same implementation commit. This activates the already-approved required scenario intent; without that metadata the compatibility default is optional and the generated plan is not yet runnable.
- [ ] Add real runner/verify rejection scenarios for source/log tampering, required skips and cleanup failures; keep evidence writer independent of exploration.
- [ ] Execute the canonical plan on the integrated revision after the plan commit; retain immutable evidence outside source identity exclusions only.
- [ ] Confirm both closeout paths and no-server/no-E2E compatibility; do not stamp success for absent live/browser prerequisites.
- [ ] Relevant spec criteria AC7, AC8, AC9, AC17 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_feat581_plan.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

- `packages/ai-parrot-server/tests/e2e/test_evidence.py::test_required_evidence_rejections` — frozen integration node ID; no renaming without updating all plans.

**Runtime E2E validation:** ordinary SDD test selection intentionally excludes E2E.
After the required harness dependencies exist, run declared scenario node IDs via
`parrot e2e run --plan` with `PARROT_TEST_E2E=1`. Live execution additionally needs
`PARROT_TEST_REAL_LLM=1` and the provider key. These are separate from the file-level
pytest contract above. This task cannot claim E2E success solely from agent-tier tests.

## Agent Instructions

1. Read the approved spec and confirm every Depends-on task is done in the per-spec index.
2. For research-gated work, read the completed research contract; BLOCKED research
   does not authorize guessing its unresolved interface.
3. Update `sdd/tasks/index/agentic-e2e-testing.json` to in-progress with assignment/time.
4. Verify imports/signatures, then implement this task's bounded blueprint.
5. Run Validation Commands and applicable runtime probes; retain useful logs.
6. Commit scoped code and SDD state, move this task to `sdd/tasks/completed/`,
   update its index file path/status/timestamps and fill the Completion Note.
7. Never update the historical monolithic task index.

## Completion Note

Completed 2026-09-24 — final task of FEAT-581. Implemented via a manual
worktree + native sonnet `sdd-coder` dispatch (the `parrot-sdd-coder` MCP
engine was unresponsive throughout this session) and merged by hand
(`git merge --no-ff`) after verifying real delivery (exactly the 4 declared
files, single commit).

Materialized `sdd/state/FEAT-581/e2e-plan.md` from the embedded canonical
plan, added `e2e: policy: required` + the 9 frozen `scenario_ids` to
`sdd/specs/agentic-e2e-testing.spec.md` frontmatter (pre-edit SHA-256
re-verified as `4c939de5d780c3ca57f2ccae88650e5600ffe8dbf85e91fc5ea36ff2e9ade9c4`,
matching the task's declared anchor), created
`packages/ai-parrot-server/tests/e2e/test_evidence.py` (frozen node
`test_required_evidence_rejections`, real runner/verify rejection scenarios
for tampering/required-skips/cleanup-failure), and
`tests/sdd_scripts/test_feat581_plan.py` (20 tests).

**One disclosed, narrow schema-mandated deviation**: the embedded plan's
`prerequisites: [redis-server]` on the two botmanager scenarios failed
Pydantic validation (`ScenarioSpec.prerequisites` is a scenario-ID
cross-reference field, not an environment-prerequisite declaration — the
redis dependency is already enforced at the target-adapter level per
TASK-3536's completion note). Changed those two fields to `prerequisites:
[]`; no scenario ID, node ID, tier, target_ids, required flag, or timeout
was touched.

Tests: `pytest tests/sdd_scripts/test_feat581_plan.py -q` → 20 passed
(re-run verified). `PARROT_TEST_E2E=1 pytest
packages/ai-parrot-server/tests/e2e/test_evidence.py -q` → 1 passed
(re-run verified); skips honestly without the opt-in env var.

**Real full-plan execution attempt** (`PARROT_TEST_E2E=1 parrot e2e run
--plan sdd/state/FEAT-581/e2e-plan.md`): 7/9 scenarios' pytest subprocesses
genuinely ran and passed; the 2 botmanager scenarios legitimately BLOCKED
on `redis_server_missing` (matching TASK-3546's own research finding — not
stamped as a pass). However, the runner's own persisted verdict reported
all 7 passing scenarios as `outcome: missing`/`node_not_collected` and the
aggregate as `FAIL`/`exit_code 4`/`gate_satisfied: false` — traced to two
confirmed, pre-existing defects in already-completed M2/M3 modules, neither
in this task's file scope, both verified directly by me before filing:
1. **`runner.py:_bridge_results` node-ID rootdir mismatch** — plan node IDs
   are repo-root-relative but the pytest subprocess (rootdir =
   `packages/ai-parrot-server`) records bridge results package-relative, so
   `observed.get(node_id)` never matches even on a genuine pass. Filed as
   `issue:bf98b8ae2ae7` (major).
2. **`sdd/state/e2e/` (target-agnostic supervisor bookkeeping) missing from
   both `.gitignore` and `evidence.py`'s `_EXCLUDED_PREFIXES`** (only the
   feature-scoped `sdd/state/<feature_id>/e2e/` is excluded, confirmed at
   `evidence.py:324`) — already tracked as `issue:64ea6d91b811` (from
   TASK-3537's completion note); every real target start/stop breaks the
   before/after source-identity match, forcing `exit_code 4` regardless of
   test outcomes.

Honest disposition today: **BLOCKED (redis-server) for 2/9 scenarios;
aggregate FAIL for the other 7/9 due to the two runner/evidence defects
above, despite every individual pytest run genuinely passing.** This is
disclosed, not silently claimed as green, per the task's own instruction
("do not stamp success for absent live/browser prerequisites"). All
evidence/state artifacts the real attempt generated were cleaned up before
commit; `git status` is clean. No STOP conditions; the one deviation above
was schema-mandated and disclosed, not a silent redesign.

Materialize this exact frontmatter/body at the task-owned state path, then validate
against the implemented schema and collection. Changes to the plan require new
evidence; no execution is claimed by this planning artifact.

```markdown
---
schema_version: 1
feature_id: FEAT-581
spec_path: sdd/specs/agentic-e2e-testing.spec.md
policy: required
targets:
  http:
    kind: mcp-toolkit
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
  stdio:
    kind: mcp-stdio
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
  app:
    kind: botmanager
    profile: minimal
    startup_timeout_s: 60
    shutdown_timeout_s: 10
    options: {}
budget:
  model: google:gemini-2.5-flash-lite
  max_calls: 4
  max_output_tokens: 512
  max_request_bytes: 16384
  timeout_s: 60
run_timeout_s: 600
scenarios:
- id: http-cli-stays-alive-and-stops
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_mcp_http.py::test_http_cli_stays_alive_and_stops
  timeout_s: 60
  prerequisites: []
  assertions:
  - Create suite-local opt-in fixtures before any spawn; use existing markers and
    explicit supervisor context.
  - Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF
    behavior.
- id: stdio-tool-roundtrip-and-eof
  tier: deterministic
  target_ids:
  - stdio
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_mcp_stdio.py::test_stdio_tool_roundtrip_and_eof
  timeout_s: 60
  prerequisites: []
  assertions:
  - Create suite-local opt-in fixtures before any spawn; use existing markers and
    explicit supervisor context.
  - Add real HTTP initialize/list/tool-effect checks and persistent stdio JSON purity/EOF
    behavior.
- id: authenticated-minimal-profile
  tier: deterministic
  target_ids:
  - app
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_authenticated_minimal_profile
  timeout_s: 60
  prerequisites:
  - redis-server
  assertions:
  - Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected
    real API assertion.
  - Test minimal boot with a controlled empty tokenizer cache and outbound network
    disabled except fixture loopback.
- id: botmanager-offline-boot
  tier: deterministic
  target_ids:
  - app
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_botmanager.py::test_botmanager_offline_boot
  timeout_s: 60
  prerequisites:
  - redis-server
  assertions:
  - Add private-Redis bootstrap cookie round-trip, anonymous/invalid denial and selected
    real API assertion.
  - Test minimal boot with a controlled empty tokenizer cache and outbound network
    disabled except fixture loopback.
- id: controller-and-supervisor-death
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_controller_and_supervisor_death
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: timeout-and-grandchild-teardown
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_timeout_and_grandchild_teardown
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: two-worktrees-independent
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_two_worktrees_independent
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: wrong-checkout-cannot-pass
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_supervisor.py::test_wrong_checkout_cannot_pass
  timeout_s: 90
  prerequisites: []
  assertions:
  - Kill controller and supervisor separately at deterministic registration barriers
    and after readiness; verify watchdog cleanup.
  - Exercise hung grandchild trees, forced teardown, stale/reused PIDs and retained
    unresolved cleanup failure.
- id: required-evidence-rejections
  tier: deterministic
  target_ids:
  - http
  required: true
  node_ids:
  - packages/ai-parrot-server/tests/e2e/test_evidence.py::test_required_evidence_rejections
  timeout_s: 60
  prerequisites: []
  assertions:
  - 'Adopt the decomposition-generated canonical plan embedded below; validate all
    frozen node IDs against integrated collection before committing it. Add matching
    e2e: required metadata and frozen scenario IDs to this feature spec in the same
    implementation commit. This activates the already-approved required scenario intent;
    without that metadata the compatibility default is optional and the generated
    plan is not yet runnable.'
  - Add real runner/verify rejection scenarios for source/log tampering, required
    skips and cleanup failures; keep evidence writer independent of exploration.
---

# FEAT-581 canonical deterministic plan

Generated during decomposition. Node IDs are frozen task contracts; runtime
validation and successful execution remain pending implementation. Live/browser
lanes are selected separately and are not claimed as executed by this plan.
```
