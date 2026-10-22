# TASK-4522: Validation Contract schema 2 (`runners[]`), schema-1 lift on read, tier validation

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4520, TASK-4521
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (contract half), brainstorm Q8 (lift on read) and codex S11 (forbidden tier is an
admission error, never an empty green plan). `TestContract` becomes `schema/runners/digest` with a
`pytest` convenience property; every existing consumer of `contract.tests` / `contract.markers` switches to
`contract.pytest`.

---

## Scope

- Add `RunnerContract` and reshape `TestContract` (`schema`, `runners`, `digest`, property `pytest`).
- `TEST_CONTRACT_SCHEMA = 2`; `parse_spec_contract` accepts the flat `tests:/markers:` form (lifted) and the `runners:` form.
- `contract_from_index_header` lifts schema 1 (digest recomputed, header untouched) and validates schema 2 against the registry (unknown kind, forbidden tier, `validate_settings` diagnostics ⇒ `ValueError`).
- `contract_to_header` always writes schema 2; add `lift_schema1`; `contract_digest` over the normalised v2 payload.
- Switch consumers: `select.py:149`, `planner.py:105-108`, `green_cache.py:185`, `check_task_graph.py:331-332` to `contract.pytest` (targets + `settings['markers']`).
- Add the §4 integration test `test_legacy_schema1_index_unchanged`.

**NOT in scope**: Registry-backed lint rules (TASK-4535); planner grouping per runner (TASK-4524).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | RunnerContract + TestContract v2 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | schema 2 parse/lift/write |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | contract.pytest consumer |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | contract.pytest markers |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | MODIFY | contract.pytest markers |
| `scripts/sdd/check_task_graph.py` | MODIFY | contract.pytest operands |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py` | MODIFY | schema 2 tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py` | MODIFY | runners: form |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract_schema2.py` | CREATE | lift + tier validation + legacy index |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.contract import (  # contract.py
    contract_from_index_header, contract_to_header, parse_spec_contract, contract_digest, load_index_header,
)
from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry, load_registry  # TASK-4521
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py:66
class TestContract:  schema: int; tests: tuple[str, ...]; markers: tuple[str, ...]; digest: str
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py
TEST_CONTRACT_SCHEMA: int = 1                                    # line 24
def contract_digest(tests, markers) -> str                       # line 173
def _normalize(tests, markers) -> TestContract                   # line 180
def parse_spec_contract(spec_md: str) -> TestContract | None     # line 227
def contract_from_index_header(header) -> TestContract | None    # line 291 — ValueError on shape/schema/digest
def contract_to_header(contract) -> dict[str, object]            # line 316
# consumers
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:149        for operand in contract.tests:
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py:105       if contract is not None and contract.markers:
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py:108       marker_expression = f"({' or '.join(contract.markers)}) and {OVERRIDE_MARKER_EXPRESSION}"
packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py:185   … and contract is not None and contract.markers:
scripts/sdd/check_task_graph.py:331-332   contract.tests
# live schema-1 payload: sdd/tasks/index/tests-optimization-sdd-flow.json header test_contract
```

### Does NOT Exist
- ~~`TestContract.runners` / `.pytest`~~ — added here
- ~~`RunnerContract`~~ — added here
- ~~a one-shot index migration~~ — lift on read only (brainstorm Q8)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py",
      "action": "MODIFY"
    },
    {
      "path": "scripts/sdd/check_task_graph.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract_schema2.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#TestContract",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#parse_spec_contract",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#contract_from_index_header",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#contract_to_header",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan",
    "sym:scripts/sdd/check_task_graph.py#_check_test_contract"
  ]
}
```

---

## Implementation Notes

- `registry=None` ⇒ validation of kinds limited to the four built-in names and tiers ⊆ TIERS (no import) — keeps `contract.py` importable without loading adapters; when a registry is passed, `tiers_for`/`validate_settings` are used.
- `RunnerContract.settings` is a frozen Mapping (MappingProxyType). `markers` live in `settings["markers"]` as a comma-joined string.
- The digest must be stable across lift: lifting the FEAT-699 header and writing it back yields a schema-2 header whose `digest` is deterministic (test it).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Reshape the dataclasses — *why*: every other change reads them.
2. Rewrite parse/lift/validate/write in contract.py — *why*: single source of truth for both header schemas.
3. Switch the four consumers to `contract.pytest` — *why*: hard cut of `.tests/.markers`.
4. Tests — *why*: lift must be byte-stable on the live FEAT-699 index.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestContract:' …/datatypes.py)
# REPLACE the TestContract class (datatypes.py:66-75) with:
@dataclass(frozen=True)
class RunnerContract:
    """One runner block of a schema-2 Validation Contract (FEAT-709)."""

    __test__ = False
    kind: str
    targets: tuple[str, ...]
    settings: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    tiers: tuple[str, ...] = ("task", "merge", "feature")

    def __post_init__(self) -> None:
        # FILL IN: freeze settings (MappingProxyType)
        ...


@dataclass(frozen=True)
class TestContract:
    """Normalized Validation Contract (index header ``test_contract``; schema 2, schema 1 lifted)."""

    __test__ = False
    schema: int
    runners: tuple[RunnerContract, ...]
    digest: str

    @property
    def pytest(self) -> RunnerContract | None:
        """The pytest block, if any (green cache, planner markers, legacy consumers)."""
        return next((r for r in self.runners if r.kind == "pytest"), None)
```
**Why**: Field names fixed by spec §2; `pytest` property keeps consumer edits one-liners.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'TEST_CONTRACT_SCHEMA: int = 1' …/contract.py)
# REPLACE line 24 with:
TEST_CONTRACT_SCHEMA: int = 2
KNOWN_RUNNER_KINDS: frozenset[str] = frozenset({"pytest", "vitest", "cargo", "parrot-e2e"})

# NEW, below contract_digest (contract.py:173):
def lift_schema1(payload: Mapping[str, object]) -> TestContract:
    """Schema-1 ``{tests, markers, digest}`` ⇒ one pytest RunnerContract (digest recomputed)."""
    # FILL IN: validate v1 shape + its own digest exactly as today, then build v2 — bounded by brainstorm Q8

# REPLACE parse_spec_contract (contract.py:227), contract_from_index_header (:291), contract_to_header (:316)
# with the spec §3 M2 skeleton signatures:
def parse_spec_contract(spec_md: str, *, registry: "RunnerRegistry | None" = None) -> TestContract | None: ...
def contract_from_index_header(header: Mapping[str, object], *, registry: "RunnerRegistry | None" = None) -> TestContract | None: ...
def contract_to_header(contract: TestContract) -> dict[str, object]:
    """Always schema 2: {"schema": 2, "runners": [{kind, targets, settings, tiers}], "digest": …}."""
# FILL IN: bodies — unknown kind / forbidden tier / settings diagnostics ⇒ ValueError (S11)
```
**Why**: Keep `_normalize`'s existing operand rules for pytest targets (no directories, no `real_llm`).

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        for operand in contract.tests:' …/select.py)
# REPLACE `for operand in contract.tests:` (select.py:149) with:
        pytest_block = contract.pytest
        for operand in (pytest_block.targets if pytest_block is not None else ()):
```
**Why**: Only the pytest block feeds pytest selection here; other runners are planned by TASK-4524.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c 'contract.markers' …/planner.py → 2 lines, 105 and 108)
# line 105: `if contract is not None and contract.markers:` →
            markers = _contract_markers(contract)
            if markers:
# line 108: use `markers` instead of `contract.markers`
# NEW helper above build_plan:
def _contract_markers(contract: TestContract | None) -> tuple[str, ...]:
    block = contract.pytest if contract is not None else None
    raw = block.settings.get("markers", "") if block is not None else ""
    return tuple(m for m in raw.split(",") if m)
```
**Why**: Same helper shape is reused by green_cache.py:185 (import it from planner, do not duplicate).

### `scripts/sdd/check_task_graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'for operand in contract.tests' scripts/sdd/check_task_graph.py)
# lines 331-332: replace `contract.tests` with
    pytest_ops = contract.pytest.targets if contract.pytest is not None else ()
# and iterate `pytest_ops` in both places (TASK-4535 rewrites this function fully later)
```
**Why**: Minimal edit to keep the lint green; the registry-backed rules are TASK-4535.

### FILL IN checklist
- [ ] `RunnerContract.__post_init__` freeze
- [ ] `lift_schema1` — v1 validation + digest check, then v2
- [ ] `parse_spec_contract` both forms; `none — fallback` ⇒ None
- [ ] `contract_from_index_header` schema switch + S11 validation
- [ ] `green_cache.py:185` — use `_contract_markers(contract)`
- [ ] tests listed in Test Specification

---

## Acceptance Criteria

- [ ] The live FEAT-699 header lifts to a one-pytest-runner contract with identical targets/markers and is not rewritten on read.
- [ ] `parrot-e2e` with `task` in tiers, an unknown kind, or a malformed runner block ⇒ `ValueError`.
- [ ] `contract_to_header(parse_spec_contract(md))` round-trips for both authoring forms.
- [ ] No remaining `contract.tests` / `contract.markers` references (`grep`).
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract_schema2.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- `pytest tests/sdd_scripts/test_check_task_graph.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4522 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by gpt-5.6-sol (codex), attempt 2 after attempt 1 infrastructure failure/fidelity violation
**Date**: 2026-10-20
**Notes**: Merge-tier validation: only 5 pre-existing bwrap failures plus 2 expected downstream reds caused by schema-2 contract normalisation (markers stored sorted; TestContract.tests removed): test_planner.py::test_contract_markers_add_distribution_sweep (owned by TASK-4524) and test_background_contract.py::test_supervisor_passes_declared_and_contract (owned by TASK-4530). Closed via close_task.sh.

**Deviations from spec**: none
