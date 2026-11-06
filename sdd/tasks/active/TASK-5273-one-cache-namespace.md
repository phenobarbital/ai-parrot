# TASK-5273: One green-cache namespace for CLI and supervisor; null-safe base ref

**Feature**: FEAT-830 — test-scope report fixes
**Spec**: `sdd/specs/test-scope-report-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bfb29d4ffe49`

---

## Context

Spec §1 items 2 and 4c / Modules 2 and 4 (select_tests part). The CLI builds the green-cache namespace with
digest `"none"` for a contract-less feature (select_tests.py:413-416) while the supervisor uses `""`
(background.py:621-626 via `_index_runtime_metadata`, and background.py:867-871). The store keeps one
namespace and wipes on change, so the two drivers clear each other's cache. Separately, select_tests.py:378
builds `origin/None` when the index header carries `"base_branch": null`. Both fixes touch `select_tests.py`,
so they are one task.

---

## Scope

- Add `green_cache.namespace_for(*, feature_id, base_ref, contract)` (contract `None` → digest `""`).
- Use it in `select_tests.main` (replacing the `"none"` call) and in `ValidationSupervisor._plan_selection`'s
  merge-tier block (background.py:867-871).
- Leave the run-validation site (background.py:621-626) on `_index_runtime_metadata`'s digest — it is already
  `contract.digest` or `""` — and pin that equality with a test.
- Add `select_tests._default_base_ref(index_header)` and use it at select_tests.py:378.
- Tests: `namespace_for`, supervisor equality, `_default_base_ref`.

**NOT in scope**: the cache key depth, `CACHE_SCHEMA`, `filter_cached`/`record_green` behaviour; the cached
count (TASK-5274); the wiki doc (TASK-5275).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | MODIFY | add `namespace_for` |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | use `namespace_for`; add `_default_base_ref` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | merge-tier site uses `namespace_for` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py` | MODIFY | `namespace_for` tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py` | MODIFY | namespace equality test |
| `packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py` | CREATE | `_default_base_ref` tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import green_cache as gc  # verified: tests/flows/dev_loop/test_scope/test_green_cache.py:9
from .datatypes import GreenCacheEntry, ScopePlan, TestContract, TestTarget  # verified: test_scope/green_cache.py:19 (TestContract already imported)
from parrot.flows.dev_loop.test_scope import baseline, green_cache  # verified: sdd_coder/background.py:47
from parrot.flows.dev_loop.sdd_coder import background as background_module  # verified: tests/.../test_background_contract.py:13
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor  # verified: tests/.../test_background_contract.py:14
from parrot.flows.dev_loop.test_scope.contract import contract_to_header, parse_spec_contract  # verified: tests/.../test_background_contract.py:16
from parrot.sdd.scripts import select_tests  # verified: tests/sdd/test_test_command_fallback.py:17
from collections.abc import Sequence  # verified: sdd/scripts/select_tests.py:17 — add Mapping to this line
```

### Existing Signatures to Use
```python
# test_scope/green_cache.py
def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:  # line 38
# TestContract has `.digest: str` (datatypes.py)

# sdd/scripts/select_tests.py
def main(argv: list[str] | None = None) -> int:  # line 355
#   index_header, index_notes = _resolve_index(args, worktree, kernel)       # line 373 (index_header may be {})
#   base_ref = args.base or f"origin/{index_header.get('base_branch', 'dev')}"  # line 378
#   import test_scope.green_cache as green_cache  # noqa: PLC0415            # line 411
#   namespace = green_cache.cache_namespace(feature_id=args.feature, base_ref=base_ref,
#       contract_digest=contract.digest if contract else "none")           # lines 413-417

# sdd_coder/background.py
_DEFAULT_BASE_REF = "origin/dev"  # line 90
class ValidationSupervisor:  # line 452
    async def _plan_selection(self, *, worktree, tier, base_ref=None, index_path=None, task_ids=..., feature_id=..., registry=...)  # line 828
    #   merge-tier block: namespace = await asyncio.to_thread(green_cache.cache_namespace, feature_id=feature_id,
    #       base_ref=baseline_ref, contract_digest=contract.digest if contract is not None else "")  # lines 866-871
    @classmethod
    def _index_runtime_metadata(cls, index_path: Optional[Path]) -> tuple[str, str]:  # line 924 — ("origin/<base>", digest or "")
    # run-validation site, lines 621-627 — UNCHANGED by this task
```

### Does NOT Exist
- ~~`green_cache.namespace_for`~~ — this task creates it.
- ~~`select_tests._default_base_ref`~~ — this task creates it.
- ~~`green_cache.NO_CONTRACT_DIGEST`~~ — no such constant; use the literal `""`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py#cache_namespace",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._plan_selection",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._index_runtime_metadata"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `test_scope/` stays stdlib-only; `select_tests` imports `green_cache` path-dependently (`test_scope.green_cache`),
  so `namespace_for` must live in `green_cache.py`, nowhere else.
- Keep `asyncio.to_thread` around the call in `background.py` (it was there for `cache_namespace`).
- A CLI cache written under the old `"none"` digest is invalidated once — expected (spec §7).

---

## Implementation Blueprint

### Steps (in order)
1. Add `namespace_for` below `cache_namespace` — *why*: one helper is the fix (AC-4).
2. Switch select_tests.py:413-417 to `green_cache.namespace_for(feature_id=args.feature, base_ref=base_ref, contract=contract)`.
3. Switch background.py:866-871 to `asyncio.to_thread(green_cache.namespace_for, feature_id=..., base_ref=baseline_ref, contract=contract)`.
4. Add `_default_base_ref` to select_tests and use it at line 378 — *why*: `dict.get(key, default)` returns `None`
   when the key exists with a null value (AC-7).
5. Write the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _file_part(target: str) -> str:' green_cache.py)
# BEFORE — insert above `def _file_part(target: str) -> str:` (verified: green_cache.py:44)
def namespace_for(*, feature_id: str, base_ref: str, contract: TestContract | None) -> str:
    """Return the one namespace every driver uses for this feature/base/contract.

    Args:
        feature_id: ``FEAT-<NNN>`` / ``BRIEF-<KEY>`` the cache belongs to.
        base_ref: Baseline ref, e.g. ``origin/dev``.
        contract: The feature's test contract, or ``None`` when it declares none.

    Returns:
        ``cache_namespace`` with ``contract.digest``, or ``""`` when there is no contract.
    """
    return cache_namespace(
        feature_id=feature_id, base_ref=base_ref, contract_digest=contract.digest if contract is not None else ""
    )


```
**Why**: `""` is the supervisor's existing value, so supervisor-written entries survive the upgrade.

### `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        namespace = green_cache.cache_namespace(' select_tests.py)
# REPLACE lines 413-417 (`        namespace = green_cache.cache_namespace(` … closing `)`) with:
        namespace = green_cache.namespace_for(feature_id=args.feature, base_ref=base_ref, contract=contract)

# occurrences: 1 (verified: grep -c "    base_ref = args.base or f\"origin/{index_header.get('base_branch', 'dev')}\"" select_tests.py)
# REPLACE line 378 with:
    base_ref = args.base or _default_base_ref(index_header)

# occurrences: 1 (verified: grep -c 'def _resolve_index(' select_tests.py)
# BEFORE — insert above `def _resolve_index(` (verified: select_tests.py:83)
def _default_base_ref(index_header: Mapping[str, object]) -> str:
    """Return ``origin/<base_branch>`` from an index header.

    Args:
        index_header: The per-spec index header (may be empty).

    Returns:
        ``origin/<base_branch>``; a missing, null or blank ``base_branch`` falls back to ``origin/dev``.
    """
    # FILL IN: read base_branch, accept only a non-blank str (strip it), else "dev" — bounded by AC-7


# line 17: `from collections.abc import Sequence` -> `from collections.abc import Mapping, Sequence`
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '                green_cache.cache_namespace,' background.py) — change ONLY the
# second one, disambiguated by its context (background.py:866-871):
#         if tier == "merge":
#             namespace = await asyncio.to_thread(
#                 green_cache.cache_namespace,
#                 feature_id=feature_id,
#                 base_ref=baseline_ref,
#                 contract_digest=contract.digest if contract is not None else "",
#             )
# becomes:
        if tier == "merge":
            namespace = await asyncio.to_thread(
                green_cache.namespace_for,
                feature_id=feature_id,
                base_ref=baseline_ref,
                contract=contract,
            )
```
**Why**: the first occurrence (line 623, run-validation path) only has the digest string; it already uses `""`.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py` (MODIFY — append)
```python
def test_namespace_for_without_contract_matches_empty_digest():
    assert gc.namespace_for(feature_id="FEAT-1", base_ref="origin/dev", contract=None) == gc.cache_namespace(
        feature_id="FEAT-1", base_ref="origin/dev", contract_digest=""
    )


def test_namespace_for_uses_contract_digest():
    # FILL IN: build a contract with parse_spec_contract (parrot.flows.dev_loop.test_scope.contract) and assert
    # namespace_for(..., contract=c) == cache_namespace(..., contract_digest=c.digest) — bounded by AC-4
    ...
```

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py` (MODIFY — append)
```python
def test_run_validation_digest_matches_namespace_for_without_contract(tmp_path: Path) -> None:
    """Both supervisor sites and the CLI agree on the namespace of a contract-less index (FEAT-830)."""
    # FILL IN: write an index header like _index() but WITHOUT "test_contract"; call
    # ValidationSupervisor._index_runtime_metadata(index_path) -> (base_ref, digest); assert digest == "" and
    # background_module.green_cache.cache_namespace(feature_id="FEAT-699", base_ref=base_ref, contract_digest=digest)
    # == background_module.green_cache.namespace_for(feature_id="FEAT-699", base_ref=base_ref, contract=None)
    # — bounded by AC-4
```

### `packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py` (CREATE)
```python
"""select_tests._default_base_ref — null-safe base ref (FEAT-830, issue:bfb29d4ffe49)."""

from __future__ import annotations

import pytest

from parrot.sdd.scripts import select_tests


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({}, "origin/dev"),
        ({"base_branch": None}, "origin/dev"),
        ({"base_branch": "  "}, "origin/dev"),
        ({"base_branch": "staging"}, "origin/staging"),
    ],
)
def test_default_base_ref(header: dict, expected: str) -> None:
    assert select_tests._default_base_ref(header) == expected
```

### FILL IN checklist
- [ ] `select_tests._default_base_ref` body — AC-7
- [ ] `test_namespace_for_uses_contract_digest` — AC-4
- [ ] `test_run_validation_digest_matches_namespace_for_without_contract` — AC-4

---

## Acceptance Criteria

- [ ] AC-4 `namespace_for(..., contract=None) == cache_namespace(..., contract_digest="")`; select_tests and the
      merge-tier supervisor site call it; no `"none"` digest remains in select_tests.
- [ ] AC-7 `_default_base_ref` returns `origin/dev` for a missing, null or blank `base_branch`.
- [ ] `ruff check` clean on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py -q`

---

## Test Specification

See the Blueprint test blocks above.

---

## Agent Instructions

1. Work in `feat-FEAT-830-test-scope-report-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Verify the anchors (`grep -c`) before editing; background.py has two `green_cache.cache_namespace,` lines — edit only the merge-tier one.
3. Implement from the Blueprint, complete every `FILL IN`, run the Validation Commands.
4. Commit only the listed files; close with `parrot sdd task close TASK-5273 test-scope-report-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*
