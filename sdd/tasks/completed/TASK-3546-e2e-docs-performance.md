# TASK-3546: Document operations and measure opt-in full profile

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3545, TASK-3544
**Assigned-to**: unassigned
**Module**: M9
**Spec acceptance criteria**: AC15, AC16

---

## Context

Implement the M9 deliverable **Document operations and measure opt-in full profile** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

**Research completion rule:** record a concrete verified contract, not a proposed assumption. Missing executable/service access keeps dependent implementation gated. Full-profile measurement alone may finish with an explicit BLOCKED/opt-in disposition as AC16 permits. No paid model request is required for this research.

## Scope

- Document install/preflight, fixture Redis/session limits, live cost semantics, browser setup, ownership/lease recovery and evidence reuse.
- Run three full-profile warm starts/stops only with authorized configured services; record versions, commands, readiness and SIGTERM timing.
- All measurements must meet 15s/10s for automatic eligibility; otherwise retain opt-in. Missing infrastructure is an explicit BLOCKED report, never invented timing.
- Verify documented file-scoped examples against current CLI and plans; no new runtime code or dependency install.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/testing/agentic-e2e.md` | CREATE | Targeted test coverage |
| `sdd/state/FEAT-581/research/full-profile.md` | CREATE | Task-owned deliverable |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `docker/integrations/server.py:22` — Builds an aiohttp app, /healthz and BotManager().setup(app); session storage is not configured. Signature: `def build_app() -> web.Application`. Source SHA-256: `c580501988bc7a82b8ba884bb8f1ded9542083f7e86cf5c0bb9a71e983ebc302`.
- `packages/ai-parrot-server/src/parrot/manager/manager.py:188` — Explicitly disable discovery/database/crews in the minimal profile; production setup is not modified by fixture auth. Signature: `def __init__(self, enable_database_bots: bool = ENABLE_DATABASE_BOTS, enable_crews: bool = ENABLE_CREWS, enable_registry_bots: bool = ENABLE_REGISTRY_BOTS, enable_swagger_api: bool = ENABLE_SWAGGER) -> None`. Source SHA-256: `4a02c5feb76658ddd89a63649ae28bd13f1cdd39e9feeab51343048851c80844`.
- `.github/workflows/ci.yml:1` — Existing CI has push/PR triggers and uv setup. New E2E workflow adds scheduled/manual lanes; do not alter existing workflow. Source SHA-256: `4916a147e2886dca6abfa60602197998e099c7477a78d6c05139111b0e502ca6`.

```python
from parrot.manager.manager import BotManager
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3545 (`sdd/tasks/active/TASK-3545-e2e-ci.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3544 (`sdd/tasks/active/TASK-3544-e2e-exploration.md`) must be done; consume its declared interfaces and re-read its completion evidence.

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### Modify-Target Freshness

All task targets are CREATE; check for collisions before writing them.

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
      "path": "docs/testing/agentic-e2e.md",
      "action": "CREATE"
    },
    {
      "path": "sdd/state/FEAT-581/research/full-profile.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:docker/integrations/server.py#build_app",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager.__init__"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3546 owns its declared files for M9. TASK-3545 supplies add deterministic nightly and explicit live ci plans; TASK-3544 supplies add optional api ui exploration and owner-scoped teardown hooks. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Document install/preflight, fixture Redis/session limits, live cost semantics, browser setup, ownership/lease recovery and evidence reuse.
2. Run three full-profile warm starts/stops only with authorized configured services; record versions, commands, readiness and SIGTERM timing.
3. All measurements must meet 15s/10s for automatic eligibility; otherwise retain opt-in. Missing infrastructure is an explicit BLOCKED report, never invented timing.
4. Verify documented file-scoped examples against current CLI and plans; no new runtime code or dependency install.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `docs/testing/agentic-e2e.md` (CREATE)

Write reproducible research evidence: baseline/version and source anchors, exact commands, sanitized observations, selected contract, rejected assumptions, and PASS/BLOCKED for every required question. Store bulky logs in artifacts/logs/. A blocked question cannot unlock dependent implementation.
### `sdd/state/FEAT-581/research/full-profile.md` (CREATE)

Write reproducible research evidence: baseline/version and source anchors, exact commands, sanitized observations, selected contract, rejected assumptions, and PASS/BLOCKED for every required question. Store bulky logs in artifacts/logs/. A blocked question cannot unlock dependent implementation.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Document install/preflight, fixture Redis/session limits, live cost semantics, browser setup, ownership/lease recovery and evidence reuse.
- [ ] Run three full-profile warm starts/stops only with authorized configured services; record versions, commands, readiness and SIGTERM timing.
- [ ] All measurements must meet 15s/10s for automatic eligibility; otherwise retain opt-in. Missing infrastructure is an explicit BLOCKED report, never invented timing.
- [ ] Verify documented file-scoped examples against current CLI and plans; no new runtime code or dependency install.
- [ ] Relevant spec criteria AC15, AC16 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_check_task_graph.py -q`

## Test Specification

Research tasks additionally require the concrete experiments in Scope; existing file-level tests are compatibility checks, not proof the spike succeeded.

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

Completed 2026-09-24. Implemented via a manual worktree + native sonnet `sdd-coder`
dispatch (the `parrot-sdd-coder` MCP engine was unresponsive at the time) and
merged by hand (`git merge --no-ff`) after verifying real delivery (exactly the
2 declared files, single commit).

Created `docs/testing/agentic-e2e.md` (install/preflight, fixture Redis/session
limits, live cost semantics, browser setup, ownership/lease recovery, evidence
reuse — verified live against the real CLI: `parrot e2e --help`, `parrot e2e
status`, `parrot e2e verify --plan .../deterministic.md` → exit 4
`evidence_pointer_missing`, matching the spec's exit-code table) and
`sdd/state/FEAT-581/research/full-profile.md`.

**AC16 (full-profile measurement) disposition: BLOCKED**, for two disclosed,
verified reasons (no invented timings): (1) no shipped target adapter
implements a "full" application profile — `botmanager` `profile='full'`
constructs at the schema layer but its real `prepare()` raises
`E2EConfigError(reason_code="botmanager_full_profile_unsupported")`, matching
TASK-3530's own completion note; (2) measuring the bare application directly
is also blocked in this sandbox — no `app/` module for `run.py` to import, no
`redis-server`/Postgres tooling, no standing containers. Environment findings
recorded for a future full-profile follow-up: redis-server missing, pnpm/node
v20.20.2 present, obscura v0.2.2 present, playwright 1.52.0 present, docker
daemon reachable but idle, Postgres tooling absent. This BLOCKED disposition
does not promote/demote full-profile eligibility (remains nightly/opt-in) and
does not affect any other module's evidence — an explicit, spec-permitted
(AC16) outcome, not a gap.

Tests: `pytest tests/sdd_scripts/test_check_task_graph.py -q` → 14 passed
(re-run verified). `ruff check` / `black --check` clean on no Python files
changed (both deliverables are markdown). No STOP conditions; no unauthorized
deviations.
