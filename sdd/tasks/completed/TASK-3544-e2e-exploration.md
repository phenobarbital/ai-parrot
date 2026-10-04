# TASK-3544: Add optional API UI exploration and owner-scoped teardown hooks

**Feature**: FEAT-581 - Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3534, TASK-3531, TASK-3541
**Assigned-to**: unassigned
**Module**: M8
**Spec acceptance criteria**: AC12, AC13

---

## Context

Implement the M8 deliverable **Add optional API UI exploration and owner-scoped teardown hooks** from approved FEAT-581.
This task is one bounded step in the deterministic process gate / optional live
checks / separate exploration design. It does not authorize adjacent refactors.

## Scope

- Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.
- Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.
- Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.
- Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.

**NOT in scope**: other modules, changes to `clients/base.py`, new dependencies,
provider fallback, production authentication changes, task auto-promotion or
claiming unexecuted E2E evidence. Runtime code is implemented only when this task
is started, not during task decomposition.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/e2e-api-tester.md` | CREATE | Task-owned deliverable |
| `.claude/agents/e2e-ui-tester.md` | CREATE | Task-owned deliverable |
| `.claude/skills/e2e/SKILL.md` | CREATE | Task-owned deliverable |
| `.agents/skills/e2e/SKILL.md` | CREATE | Task-owned deliverable |
| `.claude/hooks/e2e-teardown.sh` | CREATE | Task-owned deliverable |
| `tests/sdd_scripts/test_e2e_teardown_hook.py` | CREATE | Targeted test coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports and Existing Signatures

- `.claude/hooks/sdd-worker-format.sh:18` — Existing hook validates cwd/agent_type. E2E teardown must also validate owner; do not copy global kill behavior. Source SHA-256: `d6bb454f748c8249c25ca8a846b897c4aec66a216ecdc59950a44a55c7eea861`.
- `.claude/agents/qa-runner.md:61` — Feature selector excludes E2E; retain verdict: PASS|FAIL at line 85 and read-only verifier behavior. Source SHA-256: `ba948986bc520c1cdedeb05f041f56a65516f9fe4de8eeedff1e968011425678`.
- `packages/ai-parrot-server/src/parrot/mcp/obscura.py:66` — Freshness: manager now has context-manager, atexit and signal hooks (lines 97-168), start at 222 and stop at 343. Preserve these newer ownership semantics. Signature: `ObscuraProcessManager(config: ObscuraProcessConfig, logger: Optional[logging.Logger] = None); async start() -> str; async stop() -> None`. Source SHA-256: `03b2cc237b705144230dc7b2907ba9e38b826faec20d167f099926ef059ddb73`.

```python
from parrot.mcp.obscura import ObscuraProcessManager
```

### Dependency Interfaces (new, not existing)

- **Future dependency, not existing code:** TASK-3534 (`sdd/tasks/active/TASK-3534-e2e-cli.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3531 (`sdd/tasks/active/TASK-3531-e2e-ui-browser-targets.md`) must be done; consume its declared interfaces and re-read its completion evidence.
- **Future dependency, not existing code:** TASK-3541 (`sdd/tasks/active/TASK-3541-e2e-spec-surfaces.md`) must be done; consume its declared interfaces and re-read its completion evidence.

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
      "path": ".claude/agents/e2e-api-tester.md",
      "action": "CREATE"
    },
    {
      "path": ".claude/agents/e2e-ui-tester.md",
      "action": "CREATE"
    },
    {
      "path": ".claude/skills/e2e/SKILL.md",
      "action": "CREATE"
    },
    {
      "path": ".agents/skills/e2e/SKILL.md",
      "action": "CREATE"
    },
    {
      "path": ".claude/hooks/e2e-teardown.sh",
      "action": "CREATE"
    },
    {
      "path": "tests/sdd_scripts/test_e2e_teardown_hook.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/mcp/obscura.py#ObscuraProcessManager"
  ]
}
```

## Implementation Notes

- Follow the spec's exact policy, exit-code, lifecycle and identity semantics.
- Use Pydantic v2, async subprocess/aiohttp operations and logger diagnostics;
  no requests/httpx or direct provider SDK calls outside the existing provider.
- Work only in the feature worktree and only on the files listed above. You are
  not alone in the codebase: preserve others' changes and refresh stale contracts.
- **Parallelism:** TASK-3544 owns its declared files for M8. TASK-3534 supplies expose lazy e2e run verify and lifecycle commands; TASK-3531 supplies add isolated ui and owned obscura browser targets; TASK-3541 supplies generate e2e plans consistently in claude and codex specs. After dependencies pass, disjoint files may run concurrently; no shared-file edits outside this ownership.
- Required skips, xfails, zero collection or unresolved teardown never count as PASS.
- The server conftest marks any e2e directory, including harness unit tests, as E2E.
  Run this task's explicit file-level Validation Commands directly; the ordinary
  feature selector can deselect them and is not sufficient validation evidence.
- Keep logs under `artifacts/logs/`; no secrets or full environments in reports.

## Implementation Blueprint

### Steps (in order)

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.
2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.
3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.
4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.

### Fixed interfaces

No new cross-task public signature beyond the approved spec. Internal helpers remain task-local.

### `.claude/agents/e2e-api-tester.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.

2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.

3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.

4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
### `.claude/agents/e2e-ui-tester.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.

2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.

3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.

4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
### `.claude/skills/e2e/SKILL.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.

2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.

3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.

4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
### `.agents/skills/e2e/SKILL.md` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.

2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.

3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.

4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
### `.claude/hooks/e2e-teardown.sh` (CREATE)

Apply the task-specific scope below in order. Preserve all public interfaces fixed by the spec; dependency APIs are consumed only after their owning task lands. Use the current source anchors above for MODIFY targets and update the task contract first if those anchors drift.

1. Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.

2. Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.

3. Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.

4. Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
### `tests/sdd_scripts/test_e2e_teardown_hook.py` (CREATE)

Implement the test cases below using synthetic inputs and explicit expected outcomes. Unit collaborators may be faked; any process-boundary acceptance test must use real subprocesses. Assert failure/cleanup behavior, not only construction or mirrored constants.

### Completion checklist

- [ ] Re-read existing references and dependency completion outputs.
- [ ] Implement the exact file scope and failure semantics above.
- [ ] Verify outcomes with the explicit validation commands and runtime probes.
- [ ] Keep unresolved prerequisites visible; do not weaken tests to obtain green.

## Acceptance Criteria

- [ ] Define plan-driven API/UI agent instructions and portable manual skill with owner identity and bounded CLI lifecycle.
- [ ] Use allocated CDP endpoint; verify host MCP/agent capability before dispatch; missing exploration never substitutes for gate evidence.
- [ ] Write e2e-exploration.json without gate passed field and candidates outside pytest discovery; human-only promotion.
- [ ] Implement/test malformed-hook payload handling and owner/worktree-scoped immediate down; never global stale kill or machine-local settings overwrite.
- [ ] Relevant spec criteria AC12, AC13 are demonstrated by tests or bounded research evidence.
- [ ] File-scoped validation passes; formatting/lint is clean for changed Python.
- [ ] No source files or APIs outside the declared ownership were changed.

## Validation Commands

- `pytest tests/sdd_scripts/test_e2e_teardown_hook.py -q`

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

Completed 2026-09-24 by native seat sonnet, attempt_uid
`020ef497681145578946a5902c6c39f8`. Delivered cleanly first attempt.

Created `.claude/agents/e2e-api-tester.md` / `.claude/agents/e2e-ui-tester.md`
(plan-driven API/UI exploration agent instructions), the `.claude/skills/e2e/`
and `.agents/skills/e2e/` portable manual-skill twins, `.claude/hooks/e2e-teardown.sh`
(owner/worktree-scoped immediate `down`, never a global stale kill), and
`tests/sdd_scripts/test_e2e_teardown_hook.py`.

Design decisions (disclosed, reasoned, none out of scope):
- Both exploration subagents use a fixed per-role owner identity
  (`explore-e2e-api-tester` / `explore-e2e-ui-tester`), independently
  re-derived by the teardown hook from the hook payload's `agent_type`
  alone — no dependency on an undocumented `session_id` field, matching
  spec §2's "portable correctness never depends on a host-specific hook
  ... or a promise that a shell process survives a sub-agent's return."
- `e2e-exploration.json` is written to
  `sdd/state/<FEAT-ID>/e2e/exploration/<run-id>/e2e-exploration.json` — a
  sibling of, never inside, the deterministic gate's own evidence tree;
  schema has no `passed`/`status`/`gate_satisfied` field anywhere (spec
  §3 M8), and candidates live under `.../candidates/`, outside pytest
  discovery, human-promotion only.
- `.claude/agents/*.md`/`.claude/skills/e2e/*`/`.claude/hooks/*` are
  covered by this checkout's local `.git/info/exclude` (not `.gitignore`);
  used `git add -f` for those 4 paths.

Tests:
- `pytest tests/sdd_scripts/test_e2e_teardown_hook.py -q` → 15 passed
  (success + exact scoped argv/cwd for both agent types, never-`--stale`,
  two-worktree isolation, exit-0 even on inner `down` failure, malformed/
  empty stdin, missing fields, non-git cwd, unrelated agent_type no-op,
  `PARROT_SKIP_E2E_TEARDOWN=1` skip, missing-`parrot`-on-PATH prerequisite
  failure with/without a leaked `CLAUDE_PROJECT_DIR`).
- `ruff check` clean; `black --check` clean; `bash -n` syntax OK.

Only the 6 declared files touched (1114 insertions); nothing under `sdd/`
touched.

Note for future M9/docs work (not a defect): `chrome-devtools-mcp` is
declared in the repo root `package.json` but not yet registered in
`.mcp.json`, so `e2e-ui-tester`'s host-capability precondition reports
`unavailable` in this environment — exactly the spec-required behavior
("unavailable exploration is reported as unavailable and cannot
invalidate valid deterministic evidence").

No unresolved limitations. AC12/AC13 demonstrated by the new test suite.
