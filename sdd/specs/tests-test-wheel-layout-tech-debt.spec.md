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
**Status**: draft
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
distinct root causes (§2 *Failure taxonomy*), the largest of which — 15 of the
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

Counts are from the §1 run at `8d2cf8510`. Every failure appears in exactly
one cluster.

| Cluster | n | Root cause | Which side moves |
|---|---|---|---|
| **F1 tenant double** | 15 | `_make_request()` (`test_api_feat300.py:125`) never stubs `request.get("tenant")`; `MagicMock(spec=web.Request).get()` returns a truthy MagicMock, so `_get_tenant()` resolves garbage → handler 404s. `_tenant_request()` (`:173`) already fixes it for a subset. | **test** — fold `_tenant_request`'s patch into `_make_request`, delete the now-redundant wrapper |
| **F2 registry/enum coverage** | 11 | New `FieldType` members shipped without matching control-capability and schema-snippet entries. `_FIELD_SCHEMA_SNIPPETS` (`field_helpers.py:15`) and the builtin control table are missing keys (`KeyError: 'text' / 'number' / 'select' / 'nps' / 'group' / 'version'`, `Missing control for FieldType.TEXT`). | **product** — these are genuine gaps; register the missing entries |
| **F3 pinned-constant drift** | 7 | Tests assert literals the product legitimately grew past: `'1.0.6' == '0.9.0'`, `'1.0.6' == '0.3.0'`, `45 == 32` (×3, controls), `22 == 15` (tool defs), `60 < 50` (line count). | **test** — derive from the source of truth, never re-pin a new literal |
| **F4 contract/metadata drift** | 4 | `form_controls_response_schema.json` forbids fields the endpoint now returns (`Additional properties are not allowed ('supported_effects', …)`); two metadata key-set assertions drift with it. | **test fixture** — the schema is a snapshot of the endpoint, so it follows the endpoint |
| **F5 isolation & harness** | 3 | `parrot_formdesigner.ui` transitively imports `.api` (a real layering regression); `test_duplicate_location_raises` leaks DB state (`23505 unique violation` escaping instead of the expected error); `test_shortcut_equals_explicit`. | **mixed** — F5a is **product**, F5b/F5c are **test** |

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
| M4 (F2) | no | which snippet/capability values are correct per `FieldType` is a product judgement | — |
| M5 (F3) | yes | every literal becomes a derivation from the source of truth | — |
| M6 (F4) | yes | regenerate the schema fixture from the live endpoint, assert round-trip | — |
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

### Module 3: formdesigner F1 — tenant test double (15 failures)

- **Path**: `packages/parrot-formdesigner/tests/unit/test_api_feat300.py`,
  `…/tests/unit/test_feat300_review_fixes.py`, `…/tests/test_form_uid_integration.py`
- **Responsibility**: `_make_request()` stubs `request.get("tenant")` the way
  the real `@requires_tenant` decorator does, so handler tests exercise the
  real tenant path. `_tenant_request()` becomes redundant and is deleted.
- **Depends on**: nothing. **Touches no `src/`.**

### Module 4: formdesigner F2 — registry & snippet coverage (11 failures)

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`,
  `…/src/parrot_formdesigner/controls/builtin.py`
- **Responsibility**: every `FieldType` member (45 verified) has a schema
  snippet in `_FIELD_SCHEMA_SNIPPETS` and a registered builtin control with
  correct `supported_effects`. Product gap — tests stay as the contract.
- **Depends on**: nothing.

### Module 5: formdesigner F3 — pinned-constant drift (7 failures)

- **Path**: `…/tests/unit/test_version_and_docs.py:11`,
  `…/tests/unit/test_init_imports_metadata_only.py`,
  `…/tests/unit/test_core_models.py`, `…/tests/unit/test_controls_registry.py`,
  `…/tests/test_edit_toolkit.py`,
  `…/tests/integration/test_msteams_import_compat.py`
- **Responsibility**: replace each hardcoded literal with a derivation from the
  source of truth (`importlib.metadata.version`, `len(FieldType)`, the registry
  itself). **No test may re-pin a fresh literal** — that only resets the clock.
- **Depends on**: M4 (counts settle once M4's entries land).

### Module 6: formdesigner F4 — controls contract fixture (4 failures)

- **Path**: `…/tests/fixtures/form_controls_response_schema.json`,
  `…/tests/integration/test_form_controls_contract.py`,
  `…/tests/unit/api/test_form_controls_endpoint.py`,
  `…/tests/unit/controls/test_metadata_dump_keys.py`
- **Responsibility**: the response schema admits the fields the endpoint
  actually returns (`supported_effects`, …); the metadata key-set assertions
  follow. The endpoint is the contract; the fixture is the snapshot.
- **Depends on**: M4.

### Module 7: formdesigner F5 — layering & harness (3 failures)

- **Path**: `…/src/parrot_formdesigner/ui/`, `…/tests/unit/ui/test_ui_imports.py`,
  `…/tests/unit/test_venue_service.py`,
  `…/tests/unit/test_deterministic_integration.py`
- **Responsibility**: break the `parrot_formdesigner.ui → parrot_formdesigner.api`
  transitive import (**product fix** — the test is asserting a real invariant);
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
- [ ] **AC6** No product behaviour changed to satisfy a stale test: every F3/F4
      edit is a derivation or a regenerated snapshot, reviewable as such.
- [ ] **AC7** `ruff check` clean on every changed file.
- [ ] **AC8** No test re-pins a fresh hardcoded version/count literal (grep the
      M5 diff for new numeric/version equality literals).

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
| `packages/parrot-formdesigner/src/parrot_formdesigner/controls/builtin.py` | MODIFY | (unverified — check before use) | — | — |
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
