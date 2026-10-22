---
type: feature
base_branch: dev
projects: [parrot-formdesigner, ai-parrot, dev-loop]
tags: [formdesigner, test-baseline, merge-tier, tech-debt, pytest]
---

# Feature Specification: parrot-formdesigner Baseline Repair

**Feature ID**: FEAT-618
**Date**: 2026-10-01 (rev 0.4: 2026-10-22)
**Author**: Jesus Lara
**Status**: approved
**Revision**: 0.4
**Target version**: 1.2.5

> **Slug note.** The slug `tests-test-wheel-layout-tech-debt` is inherited
> verbatim from `wikitoolkit ledger plan-fix`'s `suggested_slug` for
> `fixgroup:3d65aa0b3ffd` (the planner derives it from the first `about`
> anchor). It under-describes the feature — and after rev 0.4 it describes the
> *wrong* feature, since `test_wheel_layout.py` moved out of scope. It is kept
> unchanged because the slug owns `FEAT-618`'s identity: re-deriving it would
> fork the feature's id, orphan the worktree and the five live task files, and
> break `DevelopmentNode._find_feature_slug`.

**Originally resolved**: `issue:181bd0c01bb4` — *FEAT-598 merge-tier validation
blast-radius pulls in ~2800 unrelated tests with pre-existing failures*. **That
issue is now `closed`**, `resolved_by: task:TASK-3919` (FEAT-620, PR #1553). See
§1 *What rev 0.4 changes*.

**Still resolves**: the `parrot-formdesigner` red baseline that the issue
surfaced — 40 failures on `dev`, which no other feature has picked up.

---

## Revision History

| Rev | Date | Change |
|---|---|---|
| 0.1 | 2026-10-01 | Initial spec from `fixgroup:3d65aa0b3ffd`. |
| 0.2 | 2026-10-01 | Re-triaged the 40 failures per file. |
| 0.3 | 2026-10-01 | Split F3/F4 by measurement. |
| **0.4** | **2026-10-22** | **Scope cut on measured evidence.** M2 retired as *delivered* (and its premise corrected — the escalation was core-driven, not cap-driven; the real fix shipped as FEAT-620). M1 **split out** to `issue:45cf6a054e06` — measured at 10× rev 0.3's estimate. Every remaining fact re-verified against `dev` `986601b4b`; all anchors in §6 refreshed. F4's one non-literal outlier re-assigned to the product side. Added §4 *Validation Contract*, *Worktree Strategy*, §9. |

---

## 1. Motivation & Business Requirements

### What rev 0.4 changes

Rev 0.1–0.3 described **three** compounding causes of an unwinnable merge-tier
gate. Three weeks of measurement resolved two of them elsewhere and showed the
third to be an order of magnitude larger than estimated. What is left is one
coherent, fully-measured job: **make `parrot-formdesigner` green**.

**Cause C (merge-tier escalation) — resolved, by a different mechanism than rev
0.3 assumed.** Rev 0.3 blamed `test_scope/select.py`'s cap-exceeded escalation.
Measured in the FEAT-618 worktree at `275a8d2bd`, that was **wrong**: a merge
plan for a diff confined to `outputs/a2ui/linked/dsl.py` yields
`core_hits=[(dsl.py, 26)]` and an **empty** `cap_hits`. The entire ~2800-test
blast radius came from `detect_core()`, not from the impact cap. Filed as
`issue:7f2f3d4d7828`; fixed by **FEAT-620** (`source_fanin()` now counts
**direct** importers instead of walking transitively, `DEFAULT_CORE_FANIN_THRESHOLD`
50 → 30, `CORE_PATHS` regenerated 724 → 29 entries). Both issues are `closed`.
M2's guard shipped anyway and is correct on its own terms — see §2 *Delivered*.

**Cause B (pytest collection identity) — split out, not dropped.** Still real,
still reproduces verbatim on `986601b4b` (§6). But rev 0.3 sized it at 24 files;
it is 25 top-level `__init__.py`, 267 under the test trees, **34** `from tests.…`
import sites, and a measured ~60 broken collection sites across 6 distributions
for the only strategy that works. It touches every test tree in the monorepo and
therefore conflicts with every in-flight worktree. It shares no file, no test and
no reviewer with the formdesigner repair, and keeping the two together blocked
five ready tasks for three weeks. Re-homed to **`issue:45cf6a054e06`** with the
full measurement record; it needs its own spec and a landing window.

**Cause A (the formdesigner red baseline) — unchanged, and now the whole
feature.** Re-measured on `986601b4b`: still exactly 40 failures, in the same
sixteen files, with the same per-cluster counts.

### Problem Statement

`packages/parrot-formdesigner/tests` is red on `dev` and has been for months:

```
$ python -m pytest packages/parrot-formdesigner/tests -q -p no:randomly
40 failed, 3825 passed, 31 skipped, 3 xfailed in 47.56s     # dev 986601b4b, 2026-10-22
40 failed, 2982 passed, 31 skipped, 3 xfailed in 37.03s     # dev 8d2cf8510, 2026-10-01
```

843 tests were added in those three weeks and **not one** of the 40 failures was
fixed, nor did any new one appear. The baseline is stable, well-understood and
nobody's — it is pure interest on a debt no feature owns.

It is not harmless. Any merge-tier plan that legitimately reaches
`parrot-formdesigner` inherits all 40, so the gate reports a red that the task's
diff did not cause. FEAT-620 narrowed *how often* that happens; it did not make
the baseline green.

The ledger issue named **two** of these failures. There are forty, and they
partition cleanly into five root causes (§2). The largest — 18 of 40 — is a
**knowingly deferred** test double. `test_api_feat300.py:173` documents its own
deferral:

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

### Goals

1. `packages/parrot-formdesigner/tests` is **green on `dev`** — 0 failures, 0 errors.
2. Every fix addresses the root cause named in §2, not the symptom: where a test
   is right, the product moves; where the product is right, the test moves. Each
   cluster states which, and why, before any code is written.
3. No test is left asserting a fresh hardcoded literal that will drift again.
4. Regressions are caught by tests, not by the next feature's merge gate.

### Non-Goals (explicitly out of scope)

- **Pytest collection identity** (the former M1). Split out to
  `issue:45cf6a054e06` — see §1. Nothing in this feature deletes, renames or
  adds a `tests/__init__.py`, and nothing touches the root `pyproject.toml`.
- **Merge-tier scope selection** (the former M2). Delivered; `test_scope/` is
  not a target of this feature. Impact analysis and the escalation ledger belong
  to FEAT-604/FEAT-620.
- The xdist flakiness in `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/*`
  (`KeyError: OutputMode.STRUCTURED_CHART`). The ledger issue records it as
  "reproduced once, then passed … confirmed flaky, not diff-caused". Not
  reproducible on demand; tracked separately.
- Changing `parrot-formdesigner`'s public API, routes, or `FieldType` members.
  **Product behaviour is never changed to satisfy a stale test.** Two product
  edits *are* in scope (M4's missing snippets, M7's layering break, and M5's one
  example-size fix) — in each the test asserts a real invariant and the product
  is what drifted. §2 states the side per cluster.

---

## 2. Architectural Design

### Overview

One workstream, five independent modules, no shared code:

```
M3 (F1) ─ tenant test double ────────→ tests/unit/test_api_feat300.py + 2 callers
M4 (F3) ─ schema-snippet coverage ───→ src/tools/field_helpers.py          [product]
M5 (F4) ─ pinned-constant drift ─────→ 6 test files + examples/forms/form_server.py
M6 (F2) ─ registry fixture isolation →  2 test files + 1 JSON fixture
M7 (F5) ─ layering & harness ────────→ src/ui/ + 3 test files             [mixed]
```

Module numbering is **deliberately not compacted**: `TASK-3910`–`TASK-3914`
already exist on `dev` and name M3–M7. Renumbering would invalidate five live
task files for no gain. M1 and M2 are retired in place (below), leaving a
numbering gap by design.

### Retired modules

**M1 — Unique pytest collection identity.** Split out to `issue:45cf6a054e06`
(2026-10-22). `TASK-3908` is `pending` on `dev` and must be retired as
out-of-scope rather than implemented; its round-2 measurement block is the
substance of the new issue and must not be lost. The defect still reproduces —
§6 records it as a *verified non-target* so a later reader does not mistake its
absence here for its absence from the repo.

**M2 — Merge-tier escalation guard. DELIVERED.** `TASK-3909` merged
`ScopePolicy.escalate_foreign_dists` (now `policy.py:90`) and closed
`done-with-issues`. The guard is correct for the cap path and is a real
safeguard, but it was never the fix for the reported symptom: with it on and
off, the FEAT-598 plan is **byte-identical**, because `cap_hits` was empty and
every escalation came through `detect_core()`. Rev 0.3's AC4 was therefore
unmeetable by M2 and is withdrawn, not inherited. The symptom is resolved by
FEAT-620 (`issue:181bd0c01bb4` closed, measured 2026-10-18 on `dev f3d22f21f`:
the `dsl.py`-only plan is now **1** invocation, down from 26).

> **Do not re-open M2 from this spec.** The guard exists, the root cause is
> fixed, and the two ledger issues are closed. A future regression belongs in a
> new issue against `test_scope/`, not in FEAT-618.

### Failure taxonomy — all 40, partitioned

Counts re-verified on **`dev 986601b4b`, 2026-10-22**, identical to the
`8d2cf8510` run three weeks earlier. Every failure appears in exactly one
cluster. Each failing file was also run standalone, which splits the 40 into
**32 genuine** failures that reproduce in isolation and **8 pollution-only**
failures that appear solely in a shared session.

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
| **F3 snippet coverage gap** | 1 | `tests/unit/test_field_helpers.py` (1) | `_FIELD_SCHEMA_SNIPPETS` (`field_helpers.py:15`) holds **34** of the **45** `FieldType` values. Exactly 11 are missing, re-measured 2026-10-22: `ai_capture`, `audio`, `color_picker`, `credit_card`, `cron`, `emoji`, `masked`, `place`, `search`, `signature_pad`, `tree_select`. **Verified**: with `controls.builtin` imported all 45 DO register (`len(_REGISTRY) == 45`, zero missing), so this is a snippets gap, not a registry gap. | **product** — add the 11 missing snippets |
| **F4 pinned-constant drift** | 6 + 1 | `tests/unit/test_version_and_docs.py` (1), `tests/unit/test_init_imports_metadata_only.py` (1), `tests/unit/test_core_models.py` (1), `tests/unit/test_controls_registry.py` (1), `tests/test_edit_toolkit.py` (2), `tests/integration/test_msteams_import_compat.py` (1) | **Six** assert literals or frozen name sets the product grew past: `'1.2.4' == '0.9.0'` (`:11`), `'1.2.4' == '0.3.0'` (`:93`), `len(FieldType) == 32` → 45 (`:246`), `len(controls) == 32` → 45 (`:180`), `len(tools) == 15` → 22 (`:608`), and `tool_names == expected_names` against a frozen 15-name set (`:615`). **The seventh is not a literal drift at all** — see the outlier note below. | **test** for the six — derive from the source of truth, never re-pin a new literal |
| **F5 isolation & harness** | 3 | `tests/unit/ui/test_ui_imports.py` (1), `tests/unit/test_venue_service.py` (1), `tests/unit/test_deterministic_integration.py` (1) | `parrot_formdesigner.ui` transitively imports `.api` via `ui/__init__.py:12 → .routes` (a real layering regression); `test_duplicate_location_raises` leaks DB state (`23505 unique violation` escaping instead of the expected error). | **mixed** — the `ui → api` break is **product**, the other two are **test** |

Totals: 18 + 11 + 1 + 7 + 3 = 40 (of which 8, inside F2, are pollution-only).

#### F4 outlier — resolved in rev 0.4

`test_msteams_import_compat.py::test_example_form_server_is_short` asserts
`len(lines) < 50` over `examples/forms/form_server.py` (`:50`); the file is now
**60** non-empty lines. Rev 0.3 filed it under F4 and applied M5's rule — *derive
from the source of truth, never re-pin a literal*. **That rule cannot apply
here**: a line budget has no source of truth to derive from, so M5's rule would
silently become "re-pin to 60", which is exactly what the rule forbids.

**Decision (rev 0.4): the product moves.** The `< 50` budget is a real
acceptance criterion inherited from the MSTeams spec — the test asserts that the
example stays a readable demo, and it is the example that drifted. M5 trims
`examples/forms/form_server.py` back under 50 non-empty lines; the assertion is
not touched. This is the one F4 edit that is **not** a test edit, and it is the
only place in this feature where an example's content changes.

### Delivered — not re-implemented

| Component | State on `dev 986601b4b` | Evidence |
|---|---|---|
| `ScopePolicy.escalate_foreign_dists` | present, default `False` | `policy.py:90` |
| `source_fanin()` direct-importer counting | present (FEAT-620) | `issue:7f2f3d4d7828` closed, `resolved_by: task:TASK-3919` |
| `CORE_PATHS` 724 → 29 entries | present (FEAT-620) | same |
| ~2800-test blast radius | resolved — 1 invocation, measured 2026-10-18 | `issue:181bd0c01bb4` closed |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormAPIHandler._get_tenant()` (`api/handlers.py:367`) | **unchanged** | F1 is a test-double fix; the handler is correct (FEAT-421 rewrote it deliberately and the double lagged) |
| `_REGISTRY` (`controls/registry.py:91`) | reads/restores | M6 snapshots and restores it; the dict itself is unchanged |
| `_FIELD_SCHEMA_SNIPPETS` (`tools/field_helpers.py:15`) | extends | M4 adds 11 entries; no key is changed or removed |
| `parrot_formdesigner.ui` → `.api` | **severs** | M7 breaks the transitive import; `ui/` stays independently mountable |
| `examples/forms/form_server.py` | modifies | M5's outlier fix only |
| `test_scope/*`, `pyproject.toml`, `packages/*/tests/__init__.py` | **not touched** | out of scope — §1 Non-Goals |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M3 (F1) | yes | fold `_tenant_request` into `_make_request`; delete the wrapper | — |
| M4 (F3) | no | which snippet value is correct per `FieldType` is a product judgement | — |
| M5 (F4) | partly | the six literal derivations are mechanical; the `form_server.py` trim is an editorial judgement | the outlier needs a human eye on what the example may lose |
| M6 (F2) | yes | snapshot/restore `_REGISTRY`; regenerate the schema fixture from the live endpoint | — |
| M7 (F5) | no | the `ui → api` import is a real layering break needing a design call | — |

### Module 3: formdesigner F1 — tenant test double (18 failures)

- **Path**: `packages/parrot-formdesigner/tests/unit/test_api_feat300.py`,
  `…/tests/unit/test_feat300_review_fixes.py`, `…/tests/test_form_uid_integration.py`
- **Responsibility**: `_make_request()` stubs `request.get("tenant")` the way
  the real `@requires_tenant` decorator does, so handler tests exercise the real
  tenant path. `_tenant_request()` becomes redundant and is deleted.
  `test_form_uid_integration.py:43` is a second, independent double needing the
  same stub.
- **Depends on**: nothing. *(Rev 0.3 made this depend on M1, because
  `test_feat300_review_fixes.py:32` does `from tests.unit.test_api_feat300
  import …`. With M1 split out, that import is left exactly as it is and the
  dependency disappears — M3 must **not** rewrite it.)*
- **Touches no `src/`.** `FormAPIHandler._get_tenant()` (`handlers.py:367`) is
  correct.
- **Interface Skeleton**:
  ```python
  # packages/parrot-formdesigner/tests/unit/test_api_feat300.py  (modifies :125)
  def _make_request(                                    # verified: test_api_feat300.py:125
      *, method: str = "GET", form_uid: str = _UNKNOWN_FORM_UID,
      version: str | None = None, body: dict | None = None,
      session_programs: list | None = None, tenant: str = "t1",
  ) -> MagicMock:
      """Build a `web.Request` double whose `.get("tenant")` returns `tenant`.

      The `MagicMock(spec=web.Request)` default returns a fresh truthy MagicMock
      for every key, which `declared_tenant(request)` then rejects; stubbing
      `.get` is what makes `_get_tenant()` resolve the intended tenant.
      """

  # DELETED — every call site now passes `tenant=` to _make_request directly.
  # def _tenant_request(*, tenant: str = "t1", **kwargs) -> MagicMock:   # verified: :173
  ```

### Module 4: formdesigner F3 — schema-snippet coverage (1 failure)

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py`
- **Responsibility**: every `FieldType` member has an entry in
  `_FIELD_SCHEMA_SNIPPETS` (`field_helpers.py:15`). The dict holds 34 of 45;
  add exactly these 11: `ai_capture`, `audio`, `color_picker`, `credit_card`,
  `cron`, `emoji`, `masked`, `place`, `search`, `signature_pad`, `tree_select`.
  Product gap — the test is the contract and stays as it is.
- **Re-verified 2026-10-22**: `len(FieldType) == 45`, `len(_FIELD_SCHEMA_SNIPPETS) == 34`,
  `len(_REGISTRY) == 45` with zero missing after importing
  `parrot_formdesigner.controls.builtin`, and **zero extra** snippet keys. The
  control registry is NOT the gap; `controls/builtin.py` needs no change.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
  _FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {   # verified: field_helpers.py:15
      ...,                                                 # 34 existing entries, unchanged
      "ai_capture": {...}, "audio": {...}, "color_picker": {...},
      "credit_card": {...}, "cron": {...}, "emoji": {...}, "masked": {...},
      "place": {...}, "search": {...}, "signature_pad": {...},
      "tree_select": {...},
  }
  # Public accessors are unchanged:
  def list_supported_form_field_types() -> list[str]: ...   # verified: field_helpers.py:319
  def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]: ...  # verified: :325
  ```

### Module 5: formdesigner F4 — pinned-constant drift (7 failures)

- **Path**: `…/tests/unit/test_version_and_docs.py:11`,
  `…/tests/unit/test_init_imports_metadata_only.py:93`,
  `…/tests/unit/test_core_models.py:246`, `…/tests/unit/test_controls_registry.py:180`,
  `…/tests/test_edit_toolkit.py:608,615`,
  `…/tests/integration/test_msteams_import_compat.py` *(assertion unchanged)*,
  `examples/forms/form_server.py` *(product)*
- **Responsibility**, in two distinct parts:
  1. **Six literal/name-set derivations.** Replace each hardcoded value with a
     derivation from the source of truth (`importlib.metadata.version`,
     `len(FieldType)`, the registry itself, the toolkit's own definitions).
     **No test may re-pin a fresh literal** — that only resets the clock. The
     frozen 15-name set at `:615` becomes a subset assertion against the live
     tool definitions, so adding a tool cannot break it again.
  2. **One product trim.** `examples/forms/form_server.py` is 60 non-empty lines
     and must come back under 50; the `< 50` assertion at
     `test_msteams_import_compat.py:50` is **not** edited. See §2 *F4 outlier*.
- **Depends on**: M4 — the `FieldType`/registry counts settle once M4's snippet
  entries land. *(M4 adds no `FieldType` member, so the count is 45 either way;
  the dependency is ordering hygiene, not a hard block.)*

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
- **Depends on**: M4 — regenerate the schema only once the control set is final.
- **Interface Skeleton**:
  ```python
  # packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py
  # and …/tests/integration/test_form_controls_contract.py
  @pytest.fixture
  def _isolated_registry():
      """Snapshot `_REGISTRY`, let the test seed it, restore it on teardown.

      Replaces the bare `_REGISTRY.clear()` calls that leaked an empty registry
      into every later test in the session.
      """
      saved = dict(_REGISTRY)        # verified: controls/registry.py:91
      try:
          yield _REGISTRY
      finally:
          _REGISTRY.clear()
          _REGISTRY.update(saved)
  ```

### Module 7: formdesigner F5 — layering & harness (3 failures)

- **Path**: `…/src/parrot_formdesigner/ui/`, `…/tests/unit/ui/test_ui_imports.py`,
  `…/tests/unit/test_venue_service.py`,
  `…/tests/unit/test_deterministic_integration.py`
- **Responsibility**: break the `parrot_formdesigner.ui → parrot_formdesigner.api`
  transitive import (**product fix** — the test at
  `test_ui_imports.py:9` asserts a real invariant: `ui/` is independently
  mountable from `api/`). The edge enters through `ui/__init__.py:12`
  (`from .routes import setup_form_ui`); `routes` is what reaches `api`.
  Then isolate `test_duplicate_location_raises` so the `23505` unique violation
  surfaces as the expected error rather than escaping.
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests
- M3–M7: the 40 named failures, each asserted green, with the per-cluster counts
  of §2 as the contract.
- M5: a test that the six derivations hold against a *changed* source of truth
  (e.g. bumping the package version does not re-red `test_version_bumped`).
- M6: a test that the registry fixture restores `_REGISTRY` exactly, asserted by
  comparing the dict before and after.

### Integration Tests
- `packages/parrot-formdesigner/tests` runs clean: **0 failed, 0 error**.
- `tests/unit/controls/test_control_registry_capabilities.py` scores 21/21 both
  standalone and inside the full package run.

### Validation Contract

Integration tests that prove this feature works. These replace heuristic test
breadth in every tier.

```yaml
runners:
  - kind: pytest
    tier: [task, feature, merge]
    tests:
      - packages/parrot-formdesigner/tests/unit/test_api_feat300.py
      - packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py
      - packages/parrot-formdesigner/tests/test_form_uid_integration.py
      - packages/parrot-formdesigner/tests/unit/test_field_helpers.py
      - packages/parrot-formdesigner/tests/unit/controls/test_control_registry_capabilities.py
      - packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py
      - packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py
      - packages/parrot-formdesigner/tests/unit/test_version_and_docs.py
      - packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py
      - packages/parrot-formdesigner/tests/unit/test_core_models.py
      - packages/parrot-formdesigner/tests/unit/test_controls_registry.py
      - packages/parrot-formdesigner/tests/test_edit_toolkit.py
      - packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py
      - packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py
      - packages/parrot-formdesigner/tests/unit/test_venue_service.py
      - packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py
    settings:
      addopts: "-p no:randomly"
```

`-p no:randomly` is **required**: F2's whole point is order-dependent pollution,
and random ordering makes the 8 pollution failures appear and disappear.

### Test Data / Fixtures
- `form_controls_response_schema.json` is regenerated from the live endpoint by
  M6, not hand-edited field by field.

---

## 5. Acceptance Criteria

- [ ] **AC1** `python -m pytest packages/parrot-formdesigner/tests -q -p no:randomly`
      → `0 failed`, `0 error`. Evidence pasted in the Completion Note.
- [ ] **AC2** No product behaviour is changed to satisfy a stale test. The only
      `src/` and `examples/` edits are M4's 11 snippets, M7's `ui → api` sever,
      and M5's `form_server.py` trim — in each the test asserts a live invariant
      and is left unedited. Reviewable as such in the diff.
- [ ] **AC3** No test re-pins a fresh hardcoded version/count literal: grep the
      M5 diff for new numeric/version equality literals and find none. The
      frozen 15-name set at `test_edit_toolkit.py:615` becomes a subset
      assertion, not a longer frozen set.
- [ ] **AC4** `tests/unit/controls/test_control_registry_capabilities.py` scores
      21/21 both standalone AND inside the full package run, **without that file
      being edited** — proving M6's fixture restore fixed the pollution rather
      than the symptom.
- [ ] **AC5** No fixture in `packages/parrot-formdesigner/tests` leaves the
      module-global `_REGISTRY` (`controls/registry.py:91`) mutated after
      teardown, asserted by a test, not by inspection.
- [ ] **AC6** `len(get_form_field_schema_snippets()) == len(FieldType) == 45`,
      and the equality is asserted by derivation so a 46th `FieldType` fails the
      test rather than silently passing.
- [ ] **AC7** `import parrot_formdesigner.ui` does not import
      `parrot_formdesigner.api` (`test_ui_imports.py:9` green on a cold
      `sys.modules`).
- [ ] **AC8** `examples/forms/form_server.py` is under 50 non-empty lines and
      still runs as a demo; `test_msteams_import_compat.py:50` is unedited.
- [ ] **AC9** `ruff check` clean on every changed file.
- [ ] **AC10** The diff touches **no** file under `packages/*/tests/__init__.py`,
      **no** `test_scope/` module, and **not** the root `pyproject.toml` —
      the two retired modules stay retired.

---

## 6. Codebase Contract

> Verified against base commit **`986601b4b`** (`dev`, 2026-10-22). Rev 0.3's
> contract was verified against `8d2cf8510`; every line number below was
> re-measured, and the ones that moved are marked **(moved)**.

### Verified Imports
```python
from parrot_formdesigner.core.types import FieldType                     # verified: core/types.py:16
from parrot_formdesigner.tools.field_helpers import (                    # verified: tools/field_helpers.py:319,325
    get_form_field_schema_snippets,
    list_supported_form_field_types,
)
from parrot_formdesigner.api.handlers import FormAPIHandler              # verified: tests/unit/test_api_feat300.py:30
from parrot_formdesigner.controls.registry import register_field_control # verified: controls/registry.py:94
from parrot_formdesigner.controls.registry import _REGISTRY              # verified: controls/registry.py:91
```

### Existing Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/controls/registry.py
_REGISTRY: dict[str, FieldControlMetadata] = {}                   # line 91
    supported_effects: list[str] = []                             # line 84
def register_field_control(..., supported_effects: list[str] | None = None, ...)  # line 94 / 106

# packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py
_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {             # line 15
def list_supported_form_field_types() -> list[str]:               # line 319
def get_form_field_schema_snippets() -> dict[str, dict[str, Any]]:# line 325

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    def _get_tenant(self, request: web.Request) -> str:           # line 367   (moved — was 270-295)

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/__init__.py
from .routes import setup_form_ui                                 # line 12   (the ui → api edge)

# packages/parrot-formdesigner/tests/unit/test_api_feat300.py
def _make_request(*, method="GET", form_uid=_UNKNOWN_FORM_UID, version=None,
                  body=None, session_programs=None, tenant="t1") -> MagicMock:  # line 125
def _tenant_request(*, tenant="t1", **kwargs) -> MagicMock:                     # line 173
def _make_handler(registry=None, *, tenant="t1") -> FormAPIHandler:             # line 193
```

### Measured constants (2026-10-22)

| Fact | Value | How measured |
|---|---|---|
| `parrot_formdesigner.__version__` | `1.2.4` | `python -c "import parrot_formdesigner as p; print(p.__version__)"` |
| `len(FieldType)` | `45` | `len({f.value for f in FieldType})` |
| `len(_FIELD_SCHEMA_SNIPPETS)` | `34` | import `tools.field_helpers` |
| missing snippet keys | the 11 named in §2 F3 | set difference; **extra keys: 0** |
| `len(_REGISTRY)` after `import controls.builtin` | `45` | **registry is complete** |
| `examples/forms/form_server.py` non-empty lines | `60` | `grep -c . examples/forms/form_server.py` |
| formdesigner baseline | `40 failed, 3825 passed, 31 skipped, 3 xfailed` | §1 |

### Does NOT Exist (Anti-Hallucination)
- ~~`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/select_tests.py`~~ —
  **the path in the ledger issue's `about[2]` is wrong.** The selector is
  `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py`. A
  separate, unrelated CLI exists at `scripts/sdd/select_tests.py`.
- ~~`parrot/flows/dev_loop/validation/`~~ — no such package; the test-scope code
  lives in `test_scope/`.
- ~~`ScopePolicy.exclude_distributions`~~ — not a real field. `ScopePolicy`
  (`policy.py:82`) has `impact_cap` (`:85`), `impact_depth` (`:86`) and
  `escalate_foreign_dists` (`:90`).
- ~~a control-registry gap~~ — **re-verified 2026-10-22**: importing
  `parrot_formdesigner.controls.builtin` registers all 45 `FieldType` values
  with none missing. `controls/builtin.py` is NOT a target of this feature; the
  `KeyError: 'text'` failures are fixture pollution (M6), not a missing control.
- ~~a per-package `.venv`~~ — only the repo-root `.venv` exists; the ledger
  issue's reference to "a clean `packages/ai-parrot/.venv`" describes no
  current checkout state.

### Verified NON-targets (real, but out of scope — do not "fix in passing")

These reproduce on `986601b4b` and are deliberately left alone. A task that
touches them is out of scope and fails AC10.

```
$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py \
                   packages/parrot-formdesigner/tests/unit/test_version_and_docs.py --co -q
_pytest.pathlib.ImportPathMismatchError: ('tests.conftest',
  '…/packages/ai-parrot-embeddings/tests/conftest.py',
  PosixPath('…/packages/parrot-formdesigner/tests/conftest.py'))

$ python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q
15 passed in 1.34s
```

| Non-target | Current measurement | Owner |
|---|---|---|
| `packages/*/tests/__init__.py` collision | 25 top-level, 267 total under the test trees, 34 `from tests.…` sites | `issue:45cf6a054e06` |
| root `[tool.pytest.ini_options]` | `pyproject.toml:247` *(moved — was 234)*; no `--import-mode` set | `issue:45cf6a054e06` |
| `ScopePolicy` / `plan_tests()` | `policy.py:82`, `select.py:139` *(moved — was 773 / 123)*; cap branch `select.py:228` *(moved — was 186)*; `_dist()` `select.py:126` *(moved — was 118)* | FEAT-620 (delivered) |

### Edit Sites (Blueprint Anchors)

> Verified against `986601b4b`. `/sdd-task` MUST re-run `grep -c` per row.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | `def _make_request(` | `test_api_feat300.py:125` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | DELETE | `def _tenant_request(*, tenant: str = "t1", **kwargs) -> MagicMock:` | `test_api_feat300.py:173` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | (call sites of `_tenant_request`) | — | re-grep |
| `packages/parrot-formdesigner/tests/test_form_uid_integration.py` | MODIFY | (second request double) | `test_form_uid_integration.py:43` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/field_helpers.py` | MODIFY | `_FIELD_SCHEMA_SNIPPETS: dict[str, dict[str, Any]] = {` | `field_helpers.py:15` | 1 |
| `packages/parrot-formdesigner/tests/unit/api/test_form_controls_endpoint.py` | MODIFY | `    _REGISTRY.clear()` | `test_form_controls_endpoint.py:19,23` | 2 |
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | MODIFY | `    _REGISTRY.clear()` | `test_form_controls_contract.py:33,37` | 2 |
| `packages/parrot-formdesigner/tests/integration/test_form_controls_contract.py` | MODIFY | `async def test_endpoint_matches_schema(aiohttp_client):` | `test_form_controls_contract.py:51` | 1 |
| `packages/parrot-formdesigner/tests/fixtures/form_controls_response_schema.json` | MODIFY | — (JSON fixture, regenerated) | — | — |
| `packages/parrot-formdesigner/tests/unit/test_version_and_docs.py` | MODIFY | `    assert v.__version__ == "0.9.0"` | `test_version_and_docs.py:11` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py` | MODIFY | `    assert pkg.__version__ == "0.3.0"` | `test_init_imports_metadata_only.py:93` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | `    assert len(FieldType) == 32` | `test_core_models.py:246` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_controls_registry.py` | MODIFY | `    assert len(controls) == 32, f"Expected 32 controls, got {len(controls)}"` | `test_controls_registry.py:180` | 1 |
| `packages/parrot-formdesigner/tests/test_edit_toolkit.py` | MODIFY | `        assert len(tools) == 15` | `test_edit_toolkit.py:608` | 1 |
| `packages/parrot-formdesigner/tests/test_edit_toolkit.py` | MODIFY | `        assert tool_names == expected_names` | `test_edit_toolkit.py:615` | 1 |
| `examples/forms/form_server.py` | MODIFY | — (whole-file trim to < 50 non-empty lines) | 60 lines | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/__init__.py` | MODIFY | `from .routes import setup_form_ui` | `ui/__init__.py:12` | 1 |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | `def test_duplicate_location_raises` | — | re-grep |
| `packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py` | MODIFY | `def test_shortcut_equals_explicit` | — | re-grep |

**Not an edit site** (unchanged by design, listed to forestall the guess):
`tests/unit/controls/test_control_registry_capabilities.py` (AC4),
`tests/integration/test_msteams_import_compat.py` (AC8),
`src/parrot_formdesigner/controls/builtin.py`, `src/.../api/handlers.py`.

---

## 7. Implementation Notes & Constraints

- **Worktree test invocation.** The shared `.venv` is editable-installed against
  the main checkout. Inside the worktree, prefix every run with
  `PYTHONPATH=packages/parrot-formdesigner/src`. Never `uv sync` in a worktree.
- **`-p no:randomly`** is required to reproduce the §1 baseline counts, and is
  part of the Validation Contract for the same reason: F2 is order-dependent.
- **Scope per package.** Run `packages/parrot-formdesigner/tests` — never a
  full-suite `pytest`, which still trips the collection collision recorded in §6
  as a non-target.
- **The 40-failure baseline is the contract**: any task that reduces the count
  must state the new count in its Completion Note, measured with the §1 command.
- **Ordering**: M4 → (M5, M6). M3 and M7 are free. Nothing depends on M3's
  former M1 edge any more.
- **Stale state to retire before implementing.** `TASK-3908` is `pending` on
  `dev` for the split-out M1. It must be closed as out-of-scope (pointing at
  `issue:45cf6a054e06`) rather than implemented; leaving it pending will make
  `/sdd-done` and `/sdd-status` report FEAT-618 as unfinished forever. The
  feature branch `feat-FEAT-618-tests-test-wheel-layout-tech-debt` already
  dropped it in commit `3bad3776e`; `dev`'s index has not caught up.

---

## 8. Open Questions

- [x] Which side moves for `test_example_form_server_is_short`? — *Resolved
      2026-10-22*: **the product.** The `< 50` budget is a real inherited
      acceptance criterion; M5 trims `examples/forms/form_server.py` and leaves
      the assertion alone. See §2 *F4 outlier*.
- [x] Keep M1 inside FEAT-618, expand it, or split it out? — *Resolved
      2026-10-22*: **split out** to `issue:45cf6a054e06`. Measured at 25 + 267
      files, 34 import sites and ~60 broken collection sites across 6
      distributions; it conflicts with every in-flight worktree and was blocking
      five ready tasks.
- [x] Does M2 still need implementing? — *Resolved 2026-10-22*: **no, it is
      delivered.** `TASK-3909` merged the guard; FEAT-620 fixed the actual root
      cause; `issue:181bd0c01bb4` and `issue:7f2f3d4d7828` are both closed.
- [ ] Should the `parrot-formdesigner` suite be added to a nightly green-gate so
      a 41st failure is caught the day it lands, rather than by the next
      feature's merge-tier plan? — *Owner: Jesus Lara.* Out of scope for the
      modules above; decide at `/sdd-done`.

---

## 9. Design Research Cross-Check

**Model**: —
**Status**: skipped (rev 0.4 is a scope reduction over an approved spec — it
introduces no new architectural design. Every change is a retirement or a
re-measurement of an existing, already-reviewed module, so an independent design
opinion would have no design to review. The original design passed review at rev
0.1–0.3.)

| Suggestion | Disposition | Reason | Landed in |
|---|---|---|---|
| — | — | — | — |

---

## Worktree Strategy

- **Isolation**: ONE feature worktree,
  `.claude/worktrees/feat-FEAT-618-tests-test-wheel-layout-tech-debt` (already
  exists, branch pushed, based on `origin/dev`). The `sdd-coder` engine gives
  each task its own sub-worktree inside it.
- **Module dependency graph**: `M4 → M5` and `M4 → M6` (both read the final
  control/`FieldType` set; M6 regenerates its JSON snapshot from it). `M3` and
  `M7` have no inbound or outbound edges. M3, M4 and M7 are therefore expected to
  run concurrently; M5 and M6 run concurrently with each other once M4 lands.
- **Shared files**: none. The five modules partition the sixteen failing files
  with zero overlap — that partition is the whole point of §2's taxonomy. The
  only file touched by two concerns is
  `tests/integration/test_form_controls_contract.py`, and both are M6's.
- **Exclusive resources**: none. No migration, no lockfile, no extension
  rebuild. Every task is `parallel: true`.
- **Cross-feature dependencies**: none blocking. FEAT-620 is already merged to
  `dev`; `issue:45cf6a054e06` is a follow-up, not a prerequisite — this feature
  must land without it.
