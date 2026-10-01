---
type: feature
base_branch: dev
projects: [parrot-formdesigner, ai-parrot, ai-parrot-embeddings, dev-loop, sdd-tooling, ci]
tags: [test-scope, merge-tier, pytest, conftest, formdesigner, tech-debt, ledger]
---

# Feature Specification: Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair

**Feature ID**: FEAT-618
**Date**: 2026-10-01
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.7

> **Slug note.** The slug `tests-test-wheel-layout-tech-debt` is inherited
> verbatim from `wikitoolkit ledger plan-fix`'s `suggested_slug` for
> `fixgroup:3d65aa0b3ffd` (the planner derives it from the first `about`
> anchor). It under-describes the feature; it is kept unchanged because
> `/sdd-fix` forbids re-deriving a planner-supplied slug.

**Resolves**: `issue:181bd0c01bb4` — *FEAT-598 merge-tier validation
blast-radius pulls in ~2800 unrelated tests with pre-existing failures*
(kind `tech_debt`, severity `major`, `discovered_from: spec:FEAT-598`).

---

## 1. Motivation & Business Requirements

### Problem Statement

`coder_run_validation(tier="merge")` is the gate that decides whether an
`sdd-coder` task may merge. For FEAT-598 it was **structurally incapable of
going green**: every task in the feature failed it for reasons no task's diff
could affect. Three independent causes compound, all reproduced on
`origin/dev` at `8d2cf8510` with no feature changes applied.

**Cause A — `parrot-formdesigner` has a red baseline on `dev`: 40 failures.**

```
$ python -m pytest packages/parrot-formdesigner/tests -q -p no:randomly
40 failed, 2982 passed, 31 skipped, 3 xfailed in 37.03s
```

The ledger issue named two of these. There are forty. They cluster into five
distinct root causes (§2 *Failure taxonomy*), the largest of which — 18 of the
40 — is a **knowingly deferred** test double. `test_api_feat300.py:173`
documents the deferral in its own docstring:

> `_make_request()` predates FEAT-421 and only stubs the legacy
> session-derived `programs` list; `FormAPIHandler._get_tenant()` now resolves
> via `declared_tenant(request)`, which reads `request.get("tenant")` … a
> `MagicMock(spec=web.Request)`'s inherited `.get()` returns a fresh (truthy)
> `MagicMock` for any key, so every handler call silently resolves to a
> nonsense tenant instead of `"t1"`. **Scoped to the FEAT-433 tests that need a
> real round-trip through the registry — not applied to the shared
> `_make_request()` used by pre-existing tests elsewhere in this file (out of
> scope).**

That deferral is why twelve handler tests assert `404 == 200` / `404 == 409` /
`404 == 204` and three more die on
`ValueError: Invalid tenant: "<MagicMock name='mock.get()' …>"`.

**Cause B — every `packages/*/tests/` tree is the same top-level module `tests`.**

24 of the 28 package test roots carry a `tests/__init__.py`, so each resolves
to the import name `tests`. Collecting any two in one pytest session collides:

```
$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py \
                   packages/parrot-formdesigner/tests/unit/test_version_and_docs.py --co
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '…/packages/ai-parrot-embeddings/tests/conftest.py',
  PosixPath('…/packages/parrot-formdesigner/tests/conftest.py'))
```

`test_wheel_layout.py` passes 15/15 standalone. **`--import-mode=importlib`
alone does NOT fix this** — verified: pytest still derives `tests.conftest`
from the `__init__.py` chain and fails one layer later with
`ValueError: Plugin already registered under a different name: …/parrot-formdesigner/tests/conftest.py=<module 'tests.conftest' from '…/ai-parrot-embeddings/tests/conftest.py'>`.
The `__init__.py` files themselves are the defect; the import mode is at most
half the remedy.

**Cause C — a cap-exceeded impact set escalates to the *whole distribution suite*.**

`test_scope/select.py:186` turns "this distribution has more impacted tests
than `impact_cap`" into "run that distribution's entire suite". So a change
confined to `parrot/outputs/a2ui/linked/*` escalates outward until the merge
gate is collecting ~2800 tests across every distribution — and therefore
inherits Cause A's 40 reds. The gate reports a red that no task caused, for
every task, which makes it useless as a per-task signal. FEAT-604 reduced the
*cost* of this escalation (ledger-backed skipping); it did not stop an
escalation from importing a foreign red baseline.

### Goals

1. `packages/parrot-formdesigner/tests` is **green on `dev`** — 0 failures, 0 errors.
2. Any two package test trees can be collected in **one** pytest session with
   no `ImportPathMismatchError` and no pluggy double-registration.
3. A merge-tier escalation cannot silently import another distribution's
   unrelated red baseline; when it would, the gate says so explicitly.
4. Regressions of 1–3 are caught by tests, not by the next feature's gate.

### Non-Goals (explicitly out of scope)

- Re-architecting impact analysis (`impact.py`) or the escalation ledger
  (`context.py`) — FEAT-604 owns that; this feature only changes what an
  escalation is *allowed to pull in*.
- The xdist flakiness in `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/*`
  (`KeyError: OutputMode.STRUCTURED_CHART`). The ledger issue itself records it
  as "reproduced once, then passed … confirmed flaky, not diff-caused". It is
  not reproducible on demand and is tracked separately.
- Changing `parrot-formdesigner`'s public API, routes, or `FieldType` members.
  Where a test and the product disagree, §2 states per cluster which side moves;
  **product behaviour is never changed to satisfy a stale test**.
- Any change to the 4 packages that already have no `tests/__init__.py`
  (`ai-parrot-advisors`, `ai-parrot-openlit-bridge`, `navrules`) beyond what
  M2's uniform rule requires.

---

## 2. Architectural Design

### Overview

Three independent workstreams, no shared code:

```
M1 ── pytest collection identity ──→ packages/*/tests/__init__.py  (+ root pyproject.toml)
M2 ── merge-tier escalation guard ──→ test_scope/{select,policy}.py
M3..M7 ── formdesigner baseline repair ──→ packages/parrot-formdesigner/{src,tests}
```

M1 and M2 both touch the gate but not the same files. M3–M7 are independent of
each other and of M1/M2; they partition the 40 failures by root cause with no
overlap, so they parallelise cleanly.

### Failure taxonomy — all 40, partitioned

Counts are from the §1 run at `8d2cf8510`. Every failure appears in exactly one
cluster. **Re-triaged per file at spec time**: each failing file was also run
standalone, which splits the 40 into **32 genuine** failures that reproduce in
isolation and **8 pollution-only** failures that appear solely in a shared
session.

```
$ for f in <each failing file>; do pytest "$f" -q -p no:randomly; done
→ 32 failures standalone
$ pytest packages/parrot-formdesigner/tests -q -p no:randomly
→ 40 failures
```

The 8-failure delta is entirely `tests/unit/controls/test_control_registry_capabilities.py`,
which **passes 21/21 standalone**.

| Cluster | n | Files | Root cause | Which side moves |
|---|---|---|---|---|
| **F1 tenant double** | 18 | `tests/unit/test_api_feat300.py` (9), `tests/unit/test_feat300_review_fixes.py` (6), `tests/test_form_uid_integration.py` (3) | `_make_request()` (`test_api_feat300.py:125`) never stubs `request.get("tenant")`; `MagicMock(spec=web.Request).get()` returns a truthy MagicMock, so `_get_tenant()` resolves garbage → handler 404s. `_tenant_request()` (`:173`) already fixes it for 6 of 31 call sites. `test_form_uid_integration.py:43` is a second, independent double with the same gap. | **test** — fold the patch into `_make_request`, delete the wrapper |
| **F2 registry pollution + contract drift** | 8 + 3 | `tests/integration/test_form_controls_contract.py` (2 own), `tests/unit/api/test_form_controls_endpoint.py` (1 own) | Both fixtures call `_REGISTRY.clear()` (`registry.py:91`) and never restore it, so every later test in the session sees an empty/partial control registry — the sole cause of the 8 `KeyError: 'text' / 'number' / …` and `assert 'text' in {'cap_test', 'compat_test'}` failures. Their own 3 failures are separate: `form_controls_response_schema.json` forbids fields the endpoint now returns (`Additional properties are not allowed ('supported_effects', …)`). | **test fixture** — snapshot/restore `_REGISTRY`; regenerate the schema from the endpoint |
| **F3 coverage gaps** | 2 | `tests/unit/test_field_helpers.py` (1), `tests/unit/test_controls_registry.py` (1) | `_FIELD_SCHEMA_SNIPPETS` (`field_helpers.py:15`) lacks entries for newer `FieldType` members (`audio`, `search`, `masked`, `ai_capture`, `tree_select`, …). **Verified**: with `controls.builtin` imported, all 45 `FieldType` values DO register — so this is a snippets gap, not a registry gap. | **product** — add the missing snippets |
| **F4 pinned-constant drift** | 6 | `tests/unit/test_version_and_docs.py` (1), `tests/unit/test_init_imports_metadata_only.py` (1), `tests/unit/test_core_models.py` (1), `tests/test_edit_toolkit.py` (2), `tests/integration/test_msteams_import_compat.py` (1) | Tests assert literals the product grew past: `'1.0.6' == '0.9.0'`, `'1.0.6' == '0.3.0'`, `45 == 32`, `22 == 15`, `60 < 50`. | **test** — derive from the source of truth, never re-pin a new literal |
| **F5 isolation & harness** | 3 | `tests/unit/ui/test_ui_imports.py` (1), `tests/unit/test_venue_service.py` (1), `tests/unit/test_deterministic_integration.py` (1) | `parrot_formdesigner.ui` transitively imports `.api` (a real layering regression); `test_duplicate_location_raises` leaks DB state (`23505 unique violation` escaping instead of the expected error). | **mixed** — the `ui → api` break is **product**, the other two are **test** |

Totals: 18 + 11 + 2 + 6 + 3 = 40 (of which 8, inside F2, are pollution-only).

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ScopePolicy` (`test_scope/policy.py:773`) | extends | gains one field for M2's guard |
| `plan_tests()` (`test_scope/select.py:123`) | modifies | cap-escalation branch at `:186` |
| `ScopePlan` / `notes` | uses | the guard reports through the existing `notes` list — no new return shape |
| root `[tool.pytest.ini_options]` (`pyproject.toml:234`) | modifies | M1 import mode |
| `FormAPIHandler._get_tenant()` | **unchanged** | F1 is a test-double fix; the handler is correct |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 | no | the two candidate strategies must be measured against the real suite before one is fixed | strategy choice is an open design question — see M1 |
| M2 | yes | guard placement, policy field, and the `notes` string are fixed below | — |
| M3 (F1) | yes | fold `_tenant_request` into `_make_request`; delete the wrapper | — |
| M4 (F3) | no | which snippet values are correct per `FieldType` is a product judgement | — |
| M5 (F4) | yes | every literal becomes a derivation from the source of truth | — |
| M6 (F2) | yes | snapshot/restore `_REGISTRY`; regenerate the schema fixture from the live endpoint | — |
| M7 (F5) | no | the `ui → api` import is a real layering break needing a design call | — |

### Module 1: Unique pytest collection identity per package

- **Path**: `packages/*/tests/__init__.py` (24 files), root `pyproject.toml`
- **Responsibility**: make every package test root resolve to a distinct
  import name so any set of them collects in one session.
- **Depends on**: nothing.
- **Open design question — resolve by measurement, not by preference.** Two
  candidates; the implementer MUST try (a) first and fall back to (b) only on
  recorded evidence, documenting the rejected option in the Completion Note:
  - **(a)** Delete all 24 `packages/*/tests/__init__.py` and set
    `--import-mode=importlib` in the root `addopts`. Constraint: **24 files
    import via `from tests.… import …`** (verified: `grep -rln -E '^\s*(from|import)\s+tests[.\s]' packages/` → 24).
    Each must be rewritten to a `conftest`-injected path or a relative import.
  - **(b)** Rename each `packages/<dist>/tests` package to a unique importable
    name. Keeps package semantics but touches every test path plus CI and
    selector path assumptions.
- **Acceptance regardless of strategy**: a new test asserts that collecting
  the embeddings + formdesigner trees together succeeds, so the collision
  cannot regress silently.

### Module 2: Merge-tier escalation may not import a foreign red baseline

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py`,
  `…/test_scope/policy.py`
- **Responsibility**: when a distribution is escalated to its full suite purely
  because its impacted set exceeded `impact_cap`, and that distribution is not
  one the changed files actually belong to, the gate must not fold that
  distribution's unrelated failures into the task's verdict.
- **Depends on**: nothing (M1 is independent).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py  (modifies :773)
  @dataclass(frozen=True)
  class ScopePolicy:
      impact_cap: int = DEFAULT_IMPACT_CAP        # line 776
      impact_depth: int = DEFAULT_IMPACT_DEPTH    # line 777
      escalate_foreign_dists: bool = False
      """When False, a cap-only escalation into a distribution that owns none of
      the changed files is recorded in `ScopePlan.notes` and skipped instead of
      contributing its whole suite. Set True to restore pre-FEAT-618 behaviour."""
  ```
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py  (modifies :186)
  # In plan_tests(), the `len(paths) > policy.impact_cap` branch:
  #   a cap-exceeded distribution that is NOT in {_dist(f) for f in changed_files}
  #   and is not reached by detect_core() is appended to `notes` as
  #   f"{dist}: cap-only escalation into a distribution owning none of the "
  #   f"changed files; skipped (ScopePolicy.escalate_foreign_dists=False)"
  #   and contributes no TestTarget.
  ```
- **Constraint**: `ScopePlan`'s shape, `cap_hits`, `cap_impacted` and the
  FEAT-604 ledger interaction are unchanged — a skipped foreign escalation must
  not appear in `escalated`, matching the existing comment at `select.py:191-198`.

### Module 3: formdesigner F1 — tenant test double (18 failures)

- **Path**: `packages/parrot-formdesigner/tests/unit/test_api_feat300.py`,
  `…/tests/unit/test_feat300_review_fixes.py`, `…/tests/test_form_uid_integration.py`
- **Responsibility**: `_make_request()` stubs `request.get("tenant")` the way
  the real `@requires_tenant` decorator does, so handler tests exercise the real
  tenant path. `_tenant_request()` becomes redundant and is deleted.
  `test_form_uid_integration.py:43` is a second, independent double needing the
  same stub.
- **Depends on**: M1 — `test_feat300_review_fixes.py:32` does
  `from tests.unit.test_api_feat300 import …`, one of the 24 sites M1 rewrites.
- **Touches no `src/`.** `FormAPIHandler._get_tenant()` (`handlers.py:270-295`)
  is correct; FEAT-421 rewrote it deliberately and the double lagged.

### Module 4: formdesigner F3 — schema-snippet coverage (2 failures)

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`
- **Responsibility**: every `FieldType` member has an entry in
  `_FIELD_SCHEMA_SNIPPETS` (`field_helpers.py:15`). Product gap — the tests are
  the contract and stay as they are.
- **Verified at spec time**: importing `parrot_formdesigner.controls.builtin`
  registers all **45** `FieldType` values with zero missing, so the control
  registry is NOT the gap — `controls/builtin.py` needs no change. The gap is
  the snippets dict that seeds it.
- **Depends on**: nothing.

### Module 5: formdesigner F4 — pinned-constant drift (6 failures)

- **Path**: `…/tests/unit/test_version_and_docs.py:11`,
  `…/tests/unit/test_init_imports_metadata_only.py`,
  `…/tests/unit/test_core_models.py`, `…/tests/test_edit_toolkit.py`,
  `…/tests/integration/test_msteams_import_compat.py`
- **Responsibility**: replace each hardcoded literal with a derivation from the
  source of truth (`importlib.metadata.version`, `len(FieldType)`, the registry
  itself). **No test may re-pin a fresh literal** — that only resets the clock.
- **Depends on**: M4 (the counts settle once M4's snippet entries land).

### Module 6: formdesigner F2 — registry fixture isolation + contract drift (11 failures)

- **Path**: `…/tests/integration/test_form_controls_contract.py`,
  `…/tests/unit/api/test_form_controls_endpoint.py`,
  `…/tests/fixtures/form_controls_response_schema.json`
- **Responsibility**: two things in the same two files.
  1. **Isolation (8 pollution failures).** Both fixtures call `_REGISTRY.clear()`
     (`test_form_controls_contract.py:33,37`; `test_form_controls_endpoint.py:19,23`)
     against the module-global `_REGISTRY` (`controls/registry.py:91`) and never
     restore it, so every later test in the session sees an empty or fake-seeded
     registry. Snapshot and restore it instead. This alone turns
     `tests/unit/controls/test_control_registry_capabilities.py` from 8 failures
     back to the 21/21 it already scores standalone — **that file is not edited.**
  2. **Contract drift (3 own failures).** `form_controls_response_schema.json`
     forbids fields the endpoint now returns (`supported_effects`, …).
     Regenerate the schema from the live endpoint; the endpoint is the contract,
     the fixture is the snapshot.
- **Depends on**: M4 (regenerate the schema only once the control set is final).

### Module 7: formdesigner F5 — layering & harness (3 failures)

- **Path**: `…/src/parrot_formdesigner/ui/`, `…/tests/unit/ui/test_ui_imports.py`,
  `…/tests/unit/test_venue_service.py`,
  `…/tests/unit/test_deterministic_integration.py`
- **Responsibility**: break the `parrot_formdesigner.ui → parrot_formdesigner.api`
  transitive import (**product fix** — the test asserts a real invariant);
  isolate `test_duplicate_location_raises` so the `23505` surfaces as the
  expected error rather than escaping.
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests
- M1: collecting `packages/ai-parrot-embeddings/tests` together with
  `packages/parrot-formdesigner/tests` exits 0 at `--collect-only`.
- M2: `plan_tests(tier="merge")` with a changed file in distribution *X* and a
  cap-exceeded impact set in unrelated distribution *Y* yields no *Y* target,
  records the skip note, and leaves *Y* out of `escalated`.
- M2 regression: with `escalate_foreign_dists=True` the pre-FEAT-618 targets
  are reproduced exactly.
- M3–M7: the 40 named failures, each asserted green.

### Integration Tests
- `packages/parrot-formdesigner/tests` runs clean: **0 failed, 0 error**.
- A merge-tier plan for a `parrot/outputs/a2ui/linked/*`-only change selects no
  `parrot-formdesigner` and no `ai-parrot-embeddings` target.

### Test Data / Fixtures
- `form_controls_response_schema.json` is regenerated from the live endpoint by
  M6, not hand-edited field by field.

---

## 5. Acceptance Criteria

- [ ] **AC1** `python -m pytest packages/parrot-formdesigner/tests -q -p no:randomly`
      → `0 failed`, `0 error`. Evidence pasted in the Completion Note.
- [ ] **AC2** `python -m pytest packages/ai-parrot-embeddings/tests packages/parrot-formdesigner/tests --collect-only -q`
      exits 0 — no `ImportPathMismatchError`, no pluggy double-registration.
- [ ] **AC3** `python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q` still passes 15/15.
- [ ] **AC4** A merge-tier plan for an `outputs/a2ui/linked/*`-only diff contains
      no `parrot-formdesigner` and no `ai-parrot-embeddings` target, and names
      each skipped foreign escalation in `notes`.
- [ ] **AC5** `ScopePolicy(escalate_foreign_dists=True)` reproduces the
      pre-FEAT-618 target set exactly (no silent behaviour change for callers
      that opt back in).
- [ ] **AC6** No product behaviour changed to satisfy a stale test: every F4/F2
      edit is a derivation or a regenerated snapshot, reviewable as such.
- [ ] **AC7** `ruff check` clean on every changed file.
- [ ] **AC8** No test re-pins a fresh hardcoded version/count literal (grep the
      M5 diff for new numeric/version equality literals).
- [ ] **AC9** `tests/unit/controls/test_control_registry_capabilities.py` scores
      21/21 both standalone AND inside the full package run, **without that file
      being edited** — proving M6's fixture restore fixed the pollution rather
      than the symptom.
- [ ] **AC10** No fixture in `packages/parrot-formdesigner/tests` leaves the
      module-global `_REGISTRY` (`controls/registry.py:91`) mutated after
      teardown.

---

## 6. Codebase Contract

> Verified against base commit **`8d2cf8510`** (`dev`, 2026-10-01).

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                    # verified: core/types.py:16
from parrot_formdesigner.tools.field_helpers import (                   # verified: tools/field_helpers.py:319,325
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)
from parrot_formdesigner.api.handlers import FormAPIHandler             # verified: tests/unit/test_api_feat300.py:30
from parrot_formdesigner.controls.registry import register_field_control # verified: controls/registry.py:94
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
class ScopePolicy:                       # line 773
    impact_cap: int = DEFAULT_IMPACT_CAP      # line 776
    impact_depth: int = DEFAULT_IMPACT_DEPTH  # line 777

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
               declared: Sequence[Sequence[str]] = (),
               policy: ScopePolicy | None = None) -> ScopePlan:   # line 123
def _dist(path: str) -> str:                                      # line 118

# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
    supported_effects: list[str] = []                             # line 84
def register_field_control(..., supported_effects: list[str] | None = None, ...)  # line 94/106

# packages/parrot-formdesigner/tests/unit/test_api_feat300.py
def _make_request(*, method="GET", form_uid=_UNKNOWN_FORM_UID, version=None,
                  body=None, session_programs=None, tenant="t1") -> MagicMock:  # line 125
def _tenant_request(*, tenant="t1", **kwargs) -> MagicMock:                     # line 173
def _make_handler(registry=None, *, tenant="t1") -> FormAPIHandler:             # line 193
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ScopePolicy.escalate_foreign_dists` | `plan_tests()` cap branch | attribute read | `select.py:186` |
| foreign-escalation skip note | `ScopePlan.notes` | `notes.append(...)` | `select.py:189` |
| `_make_request` tenant stub | `FormAPIHandler._get_tenant()` → `declared_tenant(request)` | `req.get("tenant")` | `test_api_feat300.py:173` (docstring) |

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/select_tests.py`~~ —
  **the path in the ledger issue's `about[2]` is wrong.** The selector is
  `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py`. A
  separate, unrelated CLI exists at `scripts/sdd/select_tests.py`.
- ~~`parrot/flows/dev_loop/validation/`~~ — no such package; the test-scope code
  lives in `test_scope/`.
- ~~`ScopePolicy.exclude_distributions`~~ — not a real field (only `impact_cap`
  and `impact_depth` exist at `policy.py:776-777`).
- ~~a control-registry gap~~ — **verified**: importing
  `parrot_formdesigner.controls.builtin` registers all 45 `FieldType` values
  with none missing. `controls/builtin.py` is NOT a target of this feature; the
  `KeyError: 'text'` failures are fixture pollution (M6), not a missing control.
- ~~a per-package `.venv`~~ — only the repo-root `.venv` exists; the ledger
  issue's reference to "a clean `packages/ai-parrot/.venv`" describes no
  current checkout state.

### Edit Sites (Blueprint Anchors)

> Verified against `8d2cf8510`. `/sdd-task` MUST re-run `grep -c` per row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `pyproject.toml` | MODIFY | `[tool.pytest.ini_options]` | `pyproject.toml:234` | 1 |
| `packages/*/tests/__init__.py` | DELETE/RENAME | — (24 files, M1 strategy) | — | 24 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | `class ScopePolicy:` | `policy.py:773` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `                if len(paths) > policy.impact_cap:` | `select.py:186` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | `def _make_request(` | `test_api_feat300.py:125` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | `def _tenant_request(*, tenant: str = "t1", **kwargs) -> MagicMock:` | `test_api_feat300.py:173` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | `_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {` | `field_helpers.py:15` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py` | MODIFY | `    _REGISTRY.clear()` | `test_form_controls_endpoint.py:19` | 2 |
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | MODIFY | `    _REGISTRY.clear()` | `test_form_controls_contract.py:33` | 2 |
| `packages/parrot-formdesigner/tests/unit/test_version_and_docs.py` | MODIFY | `    assert v.__version__ == "0.9.0"` | `test_version_and_docs.py:11` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_field_helpers.py` | MODIFY | `def test_field_schema_snippets_cover_all_types() -> None:` | `test_field_helpers.py:15` | 1 |
| `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json` | MODIFY | — (JSON fixture, regenerated) | — | — |
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | MODIFY | `async def test_endpoint_matches_schema(aiohttp_client):` | `test_form_controls_contract.py:51` | 1 |
| `packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py` | MODIFY | (unverified — check before use) | — | — |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | (unverified — check before use) | — | — |

---

## 7. Implementation Notes & Constraints

- **Worktree test invocation.** The shared `.venv` is editable-installed against
  the main checkout. Inside the worktree, prefix every run with
  `PYTHONPATH=packages/ai-parrot/src:packages/parrot-formdesigner/src`. Never
  `uv sync` in a worktree.
- **`-p no:randomly`** is required to reproduce the §1 baseline counts.
- **Do not run a full-suite `pytest`** — M1 changes collection semantics
  repo-wide, so validate per package and then the specific AC2 pair.
- **M1 is the riskiest module**: it changes how every test in the monorepo is
  imported. Land it on its own commit, with AC2 + AC3 evidence, before M3–M7
  rebase onto it.
- **Ordering**: M1 and M2 are independent of M3–M7 and of each other. Within
  formdesigner, M4 → (M5, M6); M3 and M7 are free.
- The 40-failure baseline is the contract: any task that reduces the count
  must state the new count in its Completion Note.
