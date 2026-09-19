# TASK-3541: Generate E2E plans consistently in Claude and Codex specs

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3521, TASK-3523
**Assigned-to**: unassigned
**Module**: M7
**Spec acceptance criteria**: AC2, AC7, AC9

---

## Context

Implement the M7 deliverable **Generate E2E plans consistently in Claude and Codex specs** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.
- Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.
- Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.
- Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/templates/spec.md` | MODIFY | Task-owned deliverable |
| `.claude/commands/sdd-spec.md` | MODIFY | Task-owned deliverable |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | Task-owned deliverable |
| `tests/sdd_scripts/test_e2e_spec_contract.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `sdd/templates/spec.md:1` — Existing YAML flow/taxonomy and numbered sections must remain intact. Source SHA-256: `d5c1dde880ca6e7dc4b5175452c7a113ba231fda8d28cb6871d1ef88d326abdf`.
- `.claude/commands/sdd-spec.md:446` — Scaffold step preserves frontmatter; insert equivalent E2E plan generation rules. Source SHA-256: `dd3e292b66b4e3d14523c012c3724c1bbd0d6e050499943ac2792b3db348a84a`.
- `.agents/skills/sdd-spec/SKILL.md:91` — Spec generation preserves metadata and template; add machine-readable E2E plan contract. Source SHA-256: `5c05008c2856483516837ebb40ada53bcd0356c6f0b011743e991f3edf6ce290`.

No unverified project import is prescribed.

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3521 (`sdd/tasks/active/TASK-3521-e2e-plan-loader.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3523 (`sdd/tasks/active/TASK-3523-e2e-evidence-verifier.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

- `sdd/templates/spec.md` current SHA-256: `d5c1dde880ca6e7dc4b5175452c7a113ba231fda8d28cb6871d1ef88d326abdf`; re-read at execution because other features may change it.
- `.claude/commands/sdd-spec.md` current SHA-256: `dd3e292b66b4e3d14523c012c3724c1bbd0d6e050499943ac2792b3db348a84a`; re-read at execution because other features may change it.
- `.agents/skills/sdd-spec/SKILL.md` current SHA-256: `5c05008c2856483516837ebb40ada53bcd0356c6f0b011743e991f3edf6ce290`; re-read at execution because other features may change it.

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
      "path": "sdd/templates/spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-spec.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-spec/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_e2e_spec_contract.py",
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
- **Parallelism:** TASK-3541 owns its declared files for M7. TASK-3521 supplies load contained feature plans and enforce spec consistency; TASK-3523 supplies evaluate exact coverage and validate immutable evidence. Exclusive prerequisite/shared-orchestration edit; do not co-schedule.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.
2. Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.
3. Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.
4. Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `sdd/templates/spec.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.

2. Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.

3. Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.

4. Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.
### `.claude/commands/sdd-spec.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.

2. Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.

3. Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.

4. Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.
### `.agents/skills/sdd-spec/SKILL.md` (MODIFY)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.

2. Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.

3. Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.

4. Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.
### `tests/sdd_scripts/test_e2e_spec_contract.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Add policy metadata and E2E Scenarios template while preserving existing flow/taxonomy sections.
- [ ] Specify complete E2EPlan frontmatter generation, stable scenario IDs, required node enumeration and separate exploration.
- [ ] Default optional for old specs/no plan, reject invalid values and required empty plans; never label live generations deterministic.
- [ ] Add a behavioral plan-schema example/round-trip contract test, not string-only assertions that mirror prose.
- [ ] Relevant spec criteria AC2, AC7, AC9 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_spec_contract.py -q`

## Test Specification

Use focused tests covering success, invalid input, prerequisite failure and cleanup. Assert the outcomes named in Scope; construction-only tests are insufficient.

Test the boundary and negative cases from Scope using the exact task-owned test file(s).

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

To be filled by the implementing agent with actual completion date, tests,
observations, limitations and any explicitly authorized deviations.
