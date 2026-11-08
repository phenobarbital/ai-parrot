---
type: feature
base_branch: dev
feature_id: FEAT-833
projects: [ai-parrot, dev-loop, sdd-tooling]
tags: [test-scope, merge-tier, validation-commands, runners, parrot-e2e, bugfix, ledger]
discovered_from: issue:3ae0b2ae0ef4
---
# FEAT-833 — Test-scope selector: a task-declared `parrot e2e run` is planned, or visibly dropped

**Status**: approved · **Parent**: FEAT-709 (multi-runner Validation Contract, closed 2026-10-20) ·
**Issue**: `issue:3ae0b2ae0ef4` (bug, minor) · **Depends on**: FEAT-829 (PR #2009 — `_plan_setting`,
`planner._runner_settings`)

> **Ownership note.** The planner grouped `issue:3ae0b2ae0ef4` with `issue:dee91130fa06` (FEAT-633 v1.1
> foreign-repo validation phase) under `fixgroup:9dec3f19cb4a`, lane SDD, both parents closed. The
> second issue is a deferred design item with no owner direction and was released by `/sdd-fix`; this
> spec covers the first only. The slug `test-scope-select-fixes` is the planner's `suggested_slug`.

## Problem

A task whose `## Validation Commands` lists `parrot e2e run --plan sdd/state/FEAT-<NNN>/e2e-plan.md`
passes `check_task_graph` (the `parrot-e2e` adapter matches the argv and the path checks apply to pytest
only, `check_task_graph.py:383-384`), but the selector plans nothing for it and says nothing.
Re-checked against `origin/dev` @ `8e45e381e1` and `origin/feat-FEAT-829-test-scope-planner-fixes`:

1. `ParrotE2EAdapter.operands()` returns `[]` for every matching argv (`parrot_e2e.py:134-136` on the
   FEAT-829 branch) — the `--plan` argument is never surfaced as an operand.
2. `_declared_targets()` emits one `TestTarget` per operand (`for operand in adapter.operands(argv) or ()`,
   `select.py:115`), so the command yields zero targets; the only notes it can emit are *not eligible for
   tier*, *over-broad* and *does not map to a distribution* (`select.py:110-121`) — none fires here.
3. Consequence in the sdd-worker orchestrated lane (`coder_run_validation`, plan = task Validation
   Commands + spec `test_contract`): the E2E run a task declares never executes while the validation
   reports green. A `required` policy is still caught later by the `/sdd-done` E2E closeout gate as
   `MISSING`, so the cost is a late, confusing failure rather than a false pass at closeout.

Repro (plan-only): a task file with `parrot e2e run --plan sdd/state/FEAT-581/e2e-plan.md` and
`pytest packages/ai-parrot-server/tests/unit/e2e/test_plan.py -q` as Validation Commands →
`parrot sdd tests select --tier merge --base origin/dev --task-file <task> --no-baseline` plans only the
pytest invocation, exit 0, no mention of the e2e command.

## Design

- **M1 — the plan is the operand (`runners/parrot_e2e.py`).**
  - `operands(argv)`: for a matching argv return `[<plan>]` where `<plan>` is the value of `--plan <path>`
    or `--plan=<path>`; `[]` when the argv carries no `--plan`; `None` when it does not match (unchanged).
    A declared `parrot e2e verify --plan X` surfaces the same operand — the selector's job is to *run*
    the plan; verification of the evidence stays with the closeout gate.
  - `distribution_of(target, *, settings)`: `Path(target or _plan_setting(settings)).parent.name or "e2e"`
    — a non-empty target names the distribution; the `plan` setting is the fallback for target-less
    contract groups (unchanged behaviour when `target == ""`).
  - `invocation(targets, …, settings, …)`: the plan is the first non-empty `target.path`, else
    `_plan_setting(settings)`. Within one `(runner, distribution)` group every target is the same plan
    (the distribution *is* its parent directory), so "first" is deterministic; a declared plan therefore
    wins over a contract block whose distribution differs, which is exactly the case
    `planner._runner_settings` cannot resolve from settings alone.
- **M2 — an empty operand list is reported (`select.py`).** In `_declared_targets()`, when
  `adapter.operands(argv)` returns an **empty list** (matched, nothing to plan) append
  `f"declared command has no operands, dropped: {' '.join(argv)}"` to `notes` and continue. pytest never
  reaches this branch (no operands ⇒ `is_broad` already dropped it); for every other runner an
  operand-less declared command was already silently dropped — the note makes that visible. Existing notes
  and their order are unchanged.
- **M3 — regression tests.** `test_runner_parrot_e2e.py`: `operands` for `run`/`verify` with
  `--plan X` / `--plan=X`, without `--plan`, non-matching; `distribution_of` prefers the target;
  `invocation` prefers the target path over `settings["plan"]` and falls back to it. `test_planner.py`
  (where the existing `plan_tests` declared-command tests live): a declared `parrot e2e run --plan …`
  at merge tier produces the `parrot-e2e` invocation with that plan (empty registry, no contract); at
  task tier it is dropped with the existing *not eligible* note; `parrot e2e run` without `--plan` is
  dropped with the new M2 note; a declared plan next to a contract block of a different plan yields two
  invocations, each with its own `--plan`.

## Acceptance Criteria

- [ ] AC-1 `ADAPTER.operands(["parrot", "e2e", "run", "--plan", "sdd/state/FEAT-581/e2e-plan.md"]) == ["sdd/state/FEAT-581/e2e-plan.md"]`;
  the `--plan=…` form and `verify` give the same; `["parrot", "e2e", "run"]` → `[]`; `["pytest"]` → `None`.
- [ ] AC-2 `ADAPTER.distribution_of("sdd/state/FEAT-815/e2e-plan.md", settings={"plan": "sdd/state/FEAT-581/e2e-plan.md"}) == "FEAT-815"`;
  `distribution_of("", settings={"plan": …})` is unchanged; `distribution_of("", settings={})` still raises `ValueError`.
- [ ] AC-3 `invocation([TestTarget("sdd/state/FEAT-815/e2e-plan.md", "FEAT-815", "declared", runner="parrot-e2e")], …, settings={"plan": "sdd/state/FEAT-581/e2e-plan.md"}, …)`
  builds `--plan sdd/state/FEAT-815/e2e-plan.md`; with `targets=[]` or a `path=""` target it builds the settings plan; with neither it raises `ValueError`.
- [ ] AC-4 `plan_tests(worktree, changed_files=[], tier="merge", declared=(("parrot", "e2e", "run", "--plan", "sdd/state/FEAT-581/e2e-plan.md"),), registry=RunnerRegistry({}, {}))`
  returns one `parrot-e2e` invocation with `argv == ("parrot", "e2e", "run", "--plan", "sdd/state/FEAT-581/e2e-plan.md", "--owner-id", "sdd-coder")`,
  `distribution == "FEAT-581"` and a `"declared"`-reason target; at `tier="task"` no `parrot-e2e` invocation and the note `parrot-e2e: not eligible for tier task`.
- [ ] AC-5 `declared=(("parrot", "e2e", "run"),)` at merge tier plans no `parrot-e2e` invocation and `plan.notes` contains `declared command has no operands, dropped: parrot e2e run`.
- [ ] AC-6 A declared `--plan sdd/state/FEAT-815/e2e-plan.md` plus a contract `parrot-e2e` block with `plan: sdd/state/FEAT-581/e2e-plan.md` (merge tier) yields two invocations, `FEAT-815` and `FEAT-581`, each with its own `--plan`.
- [ ] AC-7 `ruff check` clean on the changed files; `packages/ai-parrot/tests/flows/dev_loop/test_scope/` stays green, including the FEAT-829 tests.

## Out of scope

- `issue:dee91130fa06` (FEAT-633 v1.1 foreign-repo validation phase, `report.py` zero-test gate) — released, needs its own design.
- `check_task_graph` — it already accepts the command and deliberately path-checks pytest only.
- Any other adapter's `operands()` semantics; the `cargo`/`vitest` adapters are untouched (M2 only adds a note on a path that already dropped their operand-less commands).
- Changing `_runner_settings` (FEAT-829): a declared plan is resolved from the target, not from settings.

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-833-test-scope-select-fixes`, off `origin/dev` **with
  `origin/feat-FEAT-829-test-scope-planner-fixes` merged in first** (M1 edits `_plan_setting`-based code and the
  tests exercise `planner._runner_settings`); until PR #2009 merges, this feature's PR diff also shows FEAT-829's commits.
- **Module dependency graph**: M3 → M1, M2; M1 and M2 touch different files but share the tests — one task.
- **Shared files**: `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` (also touched by FEAT-829).
- **Exclusive resources**: none.

## Validation

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py
markers: none

## Codebase Contract

Verified against `origin/dev` @ `8e45e381e1` (`select.py`, unchanged by FEAT-829) and
`origin/feat-FEAT-829-test-scope-planner-fixes` @ `8b77d1761d` (`runners/parrot_e2e.py`, `planner.py`).

**Verified Imports**
- `from parrot.flows.dev_loop.test_scope import TestContract, TestTarget`
- `from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunnerContract`
- `from parrot.flows.dev_loop.test_scope.runners.parrot_e2e import ADAPTER, parse_e2e_verdict`
- `from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry`
- `from parrot.flows.dev_loop.test_scope.select import plan_tests`

**Existing Signatures**
- `ParrotE2EAdapter.matches(argv) -> bool`: `len(argv) >= 3 and Path(argv[0]).name == "parrot" and argv[1] == "e2e" and argv[2] in {"run", "verify"}` (`parrot_e2e.py:130-132`).
- `ParrotE2EAdapter.operands(argv) -> list[str] | None`: `return [] if self.matches(argv) else None` (`parrot_e2e.py:134-136`).
- `ParrotE2EAdapter.distribution_of(self, target, *, settings) -> str`: `return Path(_plan_setting(settings)).parent.name or "e2e"` (`parrot_e2e.py:146-148`).
- `ParrotE2EAdapter.invocation(...)`: `owner = settings.get("owner_id", "sdd-coder"); argv = ("parrot", "e2e", "run", "--plan", _plan_setting(settings), "--owner-id", owner)` (`parrot_e2e.py:160-162`).
- `_plan_setting(settings: Mapping[str, str]) -> str` raises `ValueError` for an absent/empty plan (`parrot_e2e.py:111-119`).
- `RunnerAdapter` Protocol: `operands(self, argv) -> list[str] | None` (`runners/base.py:80`).
- `_declared_targets(declared, notes, *, worktree, registry=None, tier="task") -> list[TestTarget]` (`select.py:91-124`): `argv = registry.normalize(command)`; `adapter = registry.adapter_for_argv(argv)`; tier check with note (`:109-111`); `is_broad` check with note (`:112-114`); `for operand in adapter.operands(argv) or ():` (`:115`) → `adapter.distribution_of(operand.split("::", 1)[0], settings=registry.settings_for(adapter.kind))` (`:117-119`), `ValueError` → note (`:120-122`), else `TestTarget(operand, distribution, "declared", runner=adapter.kind)` (`:123`).
- `plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None, registry=None) -> ScopePlan` (`select.py:140-148`); `ScopePlan.notes` carries the notes.
- `planner.build_plan` groups targets by `(runner, distribution)` and calls `adapter.invocation(group, …, settings=_runner_settings(...))` (FEAT-829).
- `TestTarget(path, distribution, reason, runner=...)`; `Invocation.argv`, `.distribution`, `.runner`, `.targets`.
- Existing tests: `test_matches_and_argv` (`test_runner_parrot_e2e.py`), `test_non_pytest_declared_command_produces_runner_target` (`test_planner.py:230-247`, pattern for `declared=`), FEAT-829's `_e2e_block` / `_e2e_invocations` helpers in `test_planner.py`.

**Does NOT Exist**
- Any `--plan` parsing in `parrot_e2e.py`; any note for an operand-less declared command in `select.py`.
- A `plan` attribute on `Invocation` or `TestTarget`.
- `check_task_graph` path checks for non-pytest runners.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:6f8cc17362c606979f17c1b0e66a110d0ec198176f086ebeeb80166fb25ed942 evaluation_digest=sha256:c2fed8ea553f2d5d96e54b1672ddbc4c93fcb591c984ff58bd94360815e70707 rules_version=1 status=pass -->

## Consequences

<!-- decision-audit: input_digest=sha256:6f8cc17362c606979f17c1b0e66a110d0ec198176f086ebeeb80166fb25ed942 evaluation_digest=sha256:c2fed8ea553f2d5d96e54b1672ddbc4c93fcb591c984ff58bd94360815e70707 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/e372b12e-453e-40d3-b10e-8ad15a64607e/scratchpad/dev-clone/sdd/specs/test-scope-select-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: bugfix, ledger, merge-tier, parrot-e2e, runners, test-scope, validation-commands
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "dev-loop",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "bugfix",
      "ledger",
      "merge-tier",
      "parrot-e2e",
      "runners",
      "test-scope",
      "validation-commands"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/e372b12e-453e-40d3-b10e-8ad15a64607e/scratchpad/dev-clone/sdd/specs/test-scope-select-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:c2fed8ea553f2d5d96e54b1672ddbc4c93fcb591c984ff58bd94360815e70707",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:6f8cc17362c606979f17c1b0e66a110d0ec198176f086ebeeb80166fb25ed942",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```
