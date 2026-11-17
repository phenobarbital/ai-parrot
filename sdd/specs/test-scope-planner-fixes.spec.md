---
type: feature
base_branch: dev
feature_id: FEAT-829
projects: [ai-parrot, dev-loop, sdd-tooling]
tags: [test-scope, merge-tier, validation-contract, runners, parrot-e2e, bugfix, ledger]
discovered_from: issue:a3aebc40ef48
---
# FEAT-829 — Test-scope planner: contract runner settings reach the invocation

**Status**: approved · **Parent**: FEAT-709 (multi-runner Validation Contract, closed 2026-10-20) ·
**Issue**: `issue:a3aebc40ef48` (bug, major)

> **Ownership note.** FEAT-709 shipped the schema-2 `runners[]` contract and the `parrot-e2e`
> adapter but closed on 2026-10-20 with every task `done`; the planner's `/sdd-fix` group
> `fixgroup:6e3402315bb7` has no open parent, so a new spec is provisioned. The slug
> `test-scope-planner-fixes` is the planner's `suggested_slug`, used verbatim.

## Problem

A spec that declares the documented multi-runner block (`sdd/templates/spec.md` §4):

```
runners:
- kind: pytest
  tests:
  - packages/ai-parrot/tests/...
- kind: parrot-e2e
  plan: sdd/state/FEAT-<NNN>/e2e-plan.md
```

makes `parrot sdd tests select --tier merge|feature` exit 2 with `error: 'plan'`. Re-checked
against `origin/dev` @ `fa06da14ad`:

1. `_normalize_runner()` (`contract.py:290-317`) keeps the block's own keys in
   `RunnerContract.settings` and validates them merged over the registry
   (`effective_settings = {**registry.settings_for(kind), **normalized_settings}`,
   `contract.py:317`), so the parsed contract *knows* the plan.
2. `plan_tests()` (`select.py:160-194`) also uses `block.settings` / `runner.settings` when it
   classifies contract operands and mirror targets, so the `TestTarget`s are built fine
   (`distribution_of()` names the distribution after the plan's parent directory,
   `parrot_e2e.py:135-137`).
3. `build_plan()` (`planner.py:102`) then rebuilds the per-runner settings from
   `registry.settings_for(runner)` **only** — the `.parrot/test_runners.toml` table — and hands
   that to `adapter.invocation()`. The contract block's settings are dropped one call after
   they were used. `ParrotE2EAdapter.invocation()` reads `settings["plan"]`
   (`parrot_e2e.py:151`) and raises `KeyError('plan')`; the CLI prints it as `error: 'plan'`.

Because the exception escapes `build_plan`, the **whole** plan fails — pytest targets included —
so the sdd-worker merge-tier gate (`coder_run_validation(tier="merge")` and the fallback sweep)
and the `/sdd-done` feature tier are unusable for any feature that declares the runner. Putting
`plan` under `[runners.parrot-e2e]` in `test_runners.toml` makes the invocation build, but that
is one repo-global plan, not the per-feature plan the template documents.

`green_cache.rebuild()` (`green_cache.py:202`) re-enters `build_plan(..., contract=contract)` on
the survivors and inherits the same defect.

A sibling defect — a task-declared `parrot e2e run` Validation Command yields no target because
`ParrotE2EAdapter.operands()` returns `[]` — is `issue:3ae0b2ae0ef4` and is **not** in scope.

## Design

- **M1 — `build_plan` merges the contract block's settings over the registry's.**
  A private helper in `planner.py`:

  ```python
  def _runner_settings(
      registry: RunnerRegistry,
      contract: TestContract | None,
      *,
      runner: str,
      distribution: str,
      adapter: RunnerAdapter,
  ) -> dict[str, str]:
      """Registry settings for ``runner`` with the matching contract block's settings merged on top."""
  ```

  Rules (deterministic, no I/O):
  - base = `dict(registry.settings_for(runner))` — unchanged when `contract is None` or the
    contract has no block of that kind (fallback mode keeps today's behaviour byte-for-byte).
  - candidates = the contract blocks with `block.kind == runner`, in document order.
  - the chosen block is the first candidate whose merged settings name this group's
    distribution — `adapter.distribution_of("", settings={**base, **block.settings}) ==
    distribution` (`ValueError`/`KeyError` from the adapter count as "no match") — else the
    first candidate. Two `parrot-e2e` blocks with different plans therefore each keep their own
    plan (the planner already groups them apart, since the distribution *is* the plan's parent
    directory); for `pytest`, whose `distribution_of` ignores settings, the first block wins and
    the pytest adapter ignores `settings` anyway (`runners/pytest.py:47-66` builds the
    byte-identical `_invocation`).
  - result = `{**base, **chosen.settings}` — the same precedence `_normalize_runner` already
    validates against (`contract.py:317`), so a contract that passed parsing cannot fail here.

  `build_plan` calls it once per `(runner, distribution)` group in place of `planner.py:102` and
  passes the result to `adapter.invocation()` for every runner kind. `green_cache.rebuild()`
  needs no change: it already forwards `contract=`.

- **M2 — `ParrotE2EAdapter` fails with a readable error, never `KeyError`.**
  `distribution_of()` and `invocation()` go through one private module helper
  `_plan_setting(settings) -> str` that raises
  `ValueError("parrot-e2e runner has no 'plan' setting — declare `plan:` in the spec's runner block or under [runners.parrot-e2e] in .parrot/test_runners.toml")`
  when the key is absent or empty. Behaviour with a `plan` present is unchanged (the existing
  `test_matches_and_argv` argv stays byte-identical).

- **M3 — regression tests.** `test_planner.py` gains tests that drive the real
  `parrot-e2e` adapter through `plan_tests(tier="merge", contract=…)` with an empty-settings
  registry (the exact failing shape), a registry-vs-contract precedence case, a
  two-blocks-same-kind case and a fallback-mode guard; `test_runner_parrot_e2e.py` asserts the
  M2 `ValueError`.

## Acceptance Criteria

- [ ] AC-1 `plan_tests(worktree, changed_files=[], tier="merge", contract=C, registry=RunnerRegistry({}, {}))`,
  where `C` holds a `pytest` block and a `parrot-e2e` block with `settings={"plan": "sdd/state/FEAT-581/e2e-plan.md"}`
  and `tiers=("merge", "feature")`, returns a plan whose `parrot-e2e` invocation has
  `argv == ("parrot", "e2e", "run", "--plan", "sdd/state/FEAT-581/e2e-plan.md", "--owner-id", "sdd-coder")`
  and `distribution == "FEAT-581"`, alongside the pytest invocation. No exception is raised.
- [ ] AC-2 With registry settings `{"parrot-e2e": {"plan": "sdd/state/OLD/e2e-plan.md", "owner_id": "toml-owner"}}`
  and a contract block that sets only `plan`, the invocation uses the contract's plan and the
  registry's `owner_id` (`--owner-id toml-owner`).
- [ ] AC-3 Two `parrot-e2e` blocks (plans under `sdd/state/FEAT-581/` and `sdd/state/FEAT-815/`) produce
  two invocations, each carrying its own `--plan`.
- [ ] AC-4 `contract=None` (fallback mode) and a `contract` without a block of the group's kind use
  exactly `registry.settings_for(runner)` — the existing `test_planner.py` / `test_select*.py`
  suites stay green and pytest `argv` tuples are unchanged.
- [ ] AC-5 `ParrotE2EAdapter.distribution_of("", settings={})` and
  `ParrotE2EAdapter.invocation([], …, settings={}, …)` raise `ValueError` whose message contains
  `'plan'` and `test_runners.toml`; `settings={"plan": ""}` raises the same; a present plan behaves as today.
- [ ] AC-6 `ruff check` clean on the changed files; `packages/ai-parrot/tests/flows/dev_loop/test_scope/`
  stays green.

## Out of scope

- `issue:3ae0b2ae0ef4` — task-declared `parrot e2e run` Validation Commands dropped by `_declared_targets`
  (`ParrotE2EAdapter.operands()` returns `[]`). Separate issue, separate claim.
- Changing how `.parrot/test_runners.toml` is loaded, or the `RunnerRegistry` API.
- The contract parser (`contract.py`) — it already carries and validates the block settings.
- Any other adapter (`cargo`, `vitest`) — they are already correct when the TOML table carries
  their settings and benefit from M1 without changes.

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-829-test-scope-planner-fixes`, off `origin/dev`.
- **Module dependency graph**: M3 → M1, M2 (tests assert on both). M1 and M2 touch different files
  but M3's tests cover both in one module, so the work is one task.
- **Shared files**: `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` (M1, M3).
- **Exclusive resources**: none.

## Validation

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
markers: none

## Codebase Contract

Verified against `origin/dev` @ `fa06da14ad`.

**Verified Imports**
- `from parrot.flows.dev_loop.test_scope import TestContract, TestTarget`
- `from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunnerContract`
- `from parrot.flows.dev_loop.test_scope.planner import build_plan`
- `from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry, load_registry`
- `from parrot.flows.dev_loop.test_scope.runners.base import RunnerAdapter` (Protocol; `distribution_of` at `base.py:80`, `invocation` at `base.py:82`)
- `from parrot.flows.dev_loop.test_scope.runners.parrot_e2e import ADAPTER` (used by `test_runner_parrot_e2e.py`)
- `from parrot.flows.dev_loop.test_scope.select import plan_tests`

**Existing Signatures**
- `build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(), cap_hits=None, cap_impacted=None, notes=(), contract: TestContract | None = None, mode="fallback", registry: RunnerRegistry | None = None) -> ScopePlan` (`planner.py:71-86`); the per-group loop is `planner.py:99-112` with `adapter = registry.adapter_for_kind(runner)` (`:101`) and `settings = registry.settings_for(runner)` (`:102`).
- `RunnerRegistry.__init__(adapters: Mapping[str, RunnerAdapter], settings: Mapping[str, Mapping[str, str]])` (`registry.py:26`); `settings_for(kind) -> Mapping[str, str]` returns a **copy** (`registry.py:66-68`); `adapter_for_kind` lazily imports built-ins (`registry.py:30-44`), so `RunnerRegistry({}, {})` resolves `"parrot-e2e"` and `"pytest"`.
- `RunnerContract(kind: str, targets: tuple[str, ...], settings: Mapping[str, str] = {}, tiers: tuple[str, ...] = ("task", "merge", "feature"))` — frozen dataclass, settings frozen to a `MappingProxyType` (`datatypes.py:71-85`).
- `TestContract(schema: int, runners: tuple[RunnerContract, ...] | None = None, digest: str = "", *, …)` (`datatypes.py:87-96`); `contract.runners` is the ordered tuple.
- `ParrotE2EAdapter.distribution_of(self, target, *, settings) -> str` returns `Path(settings["plan"]).parent.name or "e2e"` (`parrot_e2e.py:135-137`); `invocation(...)` builds `("parrot", "e2e", "run", "--plan", settings["plan"], "--owner-id", settings.get("owner_id", "sdd-coder"))` (`parrot_e2e.py:139-160`); `default_tiers = {"merge", "feature"}` (`:118`).
- `PytestAdapter.invocation` ignores `settings` and returns `_invocation(...)` with runner metadata (`runners/pytest.py:47-66`).
- `plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None, registry=None) -> ScopePlan` (`select.py:140-148`); for `tier != "task"` it appends one `"contract"`-reason `TestTarget` per operand, or one with `path=""` when the block has no targets (`select.py:176-194`), then calls `build_plan(..., contract=contract, registry=registry)` (`select.py:247-257`).
- `green_cache.rebuild` → `build_plan(..., contract=contract, mode=plan.mode)` without `registry=` (`green_cache.py:202-215`); `build_plan` then calls `load_registry(worktree)`.
- Test fixture `FakeAdapter` (`test_planner.py:51-87`, `kind = "fake"`, `distribution_of` → `"root"`, `invocation` argv `("fake-test", *paths)`).

**Does NOT Exist**
- Any contract-aware settings lookup in `planner.py` — `TestContract`/`RunnerContract` are only
  used there for `marker_expression_for` and the permissive/override split.
- A `plan` default in `ParrotE2EAdapter` or in `BUILTIN_MODULES` settings; `RunnerRegistry({}, {}).settings_for("parrot-e2e") == {}`.
- A `settings` parameter on `Invocation`.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:aeb469de39f8eca7d8f569073c4160e72ef620a0d38676fb1acc17e9d7689027 evaluation_digest=sha256:1c66d2c8a36a5b5c15beb72bc557ac66f181544df68411574d1afac12cff05a6 rules_version=1 status=pass -->

## Consequences

<!-- decision-audit: input_digest=sha256:aeb469de39f8eca7d8f569073c4160e72ef620a0d38676fb1acc17e9d7689027 evaluation_digest=sha256:1c66d2c8a36a5b5c15beb72bc557ac66f181544df68411574d1afac12cff05a6 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/e372b12e-453e-40d3-b10e-8ad15a64607e/scratchpad/dev-clone/sdd/specs/test-scope-planner-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, dev-loop, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: bugfix, ledger, merge-tier, parrot-e2e, runners, test-scope, validation-contract
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
      "validation-contract"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/e372b12e-453e-40d3-b10e-8ad15a64607e/scratchpad/dev-clone/sdd/specs/test-scope-planner-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:1c66d2c8a36a5b5c15beb72bc557ac66f181544df68411574d1afac12cff05a6",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:aeb469de39f8eca7d8f569073c4160e72ef620a0d38676fb1acc17e9d7689027",
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
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```
