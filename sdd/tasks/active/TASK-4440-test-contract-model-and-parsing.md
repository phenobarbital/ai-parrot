# TASK-4440: TestContract model, spec/index parsing and new kernel dataclasses

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Everything downstream (selector modes, cache, baseline, lint,
CLI, supervisor) consumes the dataclasses and parsers this task creates. Per the
spec's Worktree Strategy, **all** new kernel dataclasses land here so that
`datatypes.py` is touched by exactly one task.

The contract is authored in spec §4 as `### Validation Contract`, cached by
`/sdd-task` into the per-spec index header as a versioned `test_contract`
object, and read by the kernel ONLY from the index (never from the spec at
runtime). A malformed or unknown-schema payload fails closed (design research S3).

---

## Scope

- Add `TestContract`, `GreenCacheEntry`, `BaselineVerdict` frozen dataclasses to `datatypes.py`.
- Add two defaulted fields to `ScopePlan`: `mode: str = "fallback"` and `cached: tuple[str, ...] = ()`.
- Add to `contract.py`: `SPEC_CONTRACT_HEADING`, `TEST_CONTRACT_SCHEMA`, `contract_digest()`,
  `parse_spec_contract()`, `contract_from_index_header()`, `contract_to_header()`, `load_index_header()`.
- Write tests in a NEW file `test_spec_contract.py`.

**NOT in scope**: selector behaviour (TASK-4444/4445), lint (TASK-4441), the
`/sdd-task` caching script (TASK-4443), `__init__.py` exports (TASK-4445),
`models.py` (TASK-4445). Do NOT touch the existing `validation_contract`
header semantics anywhere.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | New dataclasses + two `ScopePlan` fields |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | Spec-subsection + index-header parsing |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside test_scope (relative imports — the package is also imported BY PATH as top-level `test_scope`)
from .datatypes import TestContract  # created by THIS task
from dataclasses import dataclass, field  # datatypes.py:5
from types import MappingProxyType         # datatypes.py:6
# tests:
from parrot.flows.dev_loop.test_scope.contract import parse_spec_contract, contract_from_index_header
from parrot.flows.dev_loop.test_scope.datatypes import TestContract, ScopePlan
```

### Existing Signatures to Use
```python
# test_scope/datatypes.py
class TestTarget:   # line 11 — has `__test__ = False` (line 14); copy that idiom for TestContract
class ScopePlan:    # line 42 — fields tier, invocations, escalated, core_hits, skipped_escalations, notes,
                    #   cap_hits=..., cap_impacted=... ; __post_init__ freezes mappings (line 54)
class LedgerEntry:  # line 63
class AttemptContext:  # line 73

# test_scope/contract.py
VALIDATION_HEADING: str = "## Validation Commands"          # line 10
_HEADING_RE / _NEXT_HEADING_RE                               # lines 11-12 (pattern style to copy)
def parse_validation_commands(task_md: str) -> list[list[str]]:  # line 63
```

### Does NOT Exist
- ~~`TestContract`, `GreenCacheEntry`, `BaselineVerdict`~~ — created here
- ~~`test_contract` index header field~~ — new; the EXISTING `validation_contract: "required"` string
  is a DIFFERENT FEAT-563 lint flag (`scripts/sdd/check_task_graph.py:425`) — never read or write it here
- ~~Pydantic in the kernel~~ — `datatypes.py`/`contract.py` are stdlib-only (`test_stdlib_only.py` enforces it)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#ScopePlan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#LedgerEntry",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#parse_validation_commands"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib only (`re`, `json`, `hashlib`, `pathlib`, `dataclasses`). `test_stdlib_only.py` must still pass.
- `parse_spec_contract` returns `None` for an explicit `none — fallback` (also accept `none - fallback`
  and `none` with ASCII hyphen); raises `ValueError` for a malformed subsection — fail closed.
- `contract_from_index_header` returns `None` when `test_contract` is ABSENT (legacy index → fallback
  mode); raises `ValueError` when it is PRESENT but malformed or `schema != 1`.
- Digest: `"sha256:" + sha256(json.dumps({"schema", "tests", "markers"}, sort_keys=True, separators=(",", ":")))`.
  `tests` keep author order but are de-duplicated; `markers` sorted.
- Operands: repo-relative, no leading `/`, no `..`, no glob chars (`*?[`), never a bare directory form
  like `tests` or `packages/<dist>/tests` (reuse `is_broad_pytest(["pytest", op])` to reject those).
- Marker `real_llm` is rejected by the parser (`ValueError`) — the lint (TASK-4441) reports it nicer.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three dataclasses + two `ScopePlan` fields — *why*: one owner for `datatypes.py` (spec Worktree Strategy).
2. Add the parsing helpers to `contract.py` — *why*: every consumer shares one normalizer, so digests agree.
3. Write `test_spec_contract.py` — *why*: AC1–AC6 below are the contract other tasks rely on.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class LedgerEntry:' datatypes.py)
# BEFORE — insert above `@dataclass(frozen=True)\nclass LedgerEntry:` (verified: datatypes.py:62-63)
@dataclass(frozen=True)
class TestContract:
    """Normalized spec-declared validation contract (per-spec index header ``test_contract``, FEAT-699)."""

    __test__ = False  # not a pytest test class

    schema: int  # payload version; only 1 is understood
    tests: tuple[str, ...]  # pytest operands: repo-relative file or file::node
    markers: tuple[str, ...]  # registered marker names, never "real_llm"
    digest: str  # "sha256:<hex>" of the normalized payload


@dataclass(frozen=True)
class GreenCacheEntry:
    """One cached-green test target within a feature (FEAT-699 green cache)."""

    target: str  # repo-relative file or file::node exactly as planned
    key: str  # content key, see green_cache.target_key
    recorded_at: str  # UTC ISO-8601


@dataclass(frozen=True)
class BaselineVerdict:
    """Classification of one failed node id against origin/<base_branch> (FEAT-699)."""

    nodeid: str
    status: str  # "new_red" | "baseline_red" | "unknown" | "flaky"
    detail: str = ""
```
```python
# occurrences: 1 (verified: grep -c 'cap_impacted: Mapping\[str, str\] = field' datatypes.py)
# AFTER — insert below `cap_impacted: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))` (verified: datatypes.py:52)
    mode: str = "fallback"  # "contract" | "fallback" (FEAT-699)
    cached: tuple[str, ...] = ()  # targets dropped by the green cache (FEAT-699)
```
**Why**: defaults keep every existing `ScopePlan(...)` constructor call and `models.py` working unchanged.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_ENV_ASSIGNMENT_RE = re.compile' contract.py)
# AFTER — insert below `_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")` (verified: contract.py:18)
SPEC_CONTRACT_HEADING: str = "### Validation Contract"
TEST_CONTRACT_SCHEMA: int = 1
_SPEC_CONTRACT_RE = re.compile(r"^### Validation Contract\s*$", re.M)
_SPEC_NEXT_RE = re.compile(r"^#{2,3} ", re.M)
```
```python
# Append at end of contract.py (after is_broad_pytest, contract.py:143-162). Needs: import hashlib, json;
# from collections.abc import Mapping; from .datatypes import TestContract
def contract_digest(tests: Sequence[str], markers: Sequence[str]) -> str:
    """``sha256:<hex>`` over the normalized payload; identical inputs always give identical digests."""
    payload = {"schema": TEST_CONTRACT_SCHEMA, "tests": list(tests), "markers": sorted(markers)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _normalize(tests: Sequence[str], markers: Sequence[str]) -> TestContract:
    """Validate operands/markers and build a TestContract; raises ValueError on any bad entry."""
    # FILL IN: reject leading '/', '..' segments, glob chars, broad operands (is_broad_pytest(["pytest", op])),
    #          and the marker "real_llm"; de-duplicate tests keeping order — bounded by Key Constraints
    raise NotImplementedError


def parse_spec_contract(spec_md: str) -> TestContract | None:
    """Parse spec §4 ``### Validation Contract``. None for an explicit ``none — fallback``.

    Raises:
        ValueError: subsection missing, or present but malformed (fail closed).
    """
    # FILL IN: locate heading; body ends at next '## '/'### '; read the `tests:` and `markers:` bullet
    #          lists ('- <value>'; strip trailing '# comment'); 'markers: none' == []. Blockquote lines
    #          ('>') are ignored. A body whose first non-blank, non-'>' line is 'none — fallback' → None.
    raise NotImplementedError


def contract_from_index_header(header: Mapping[str, object]) -> TestContract | None:
    """The cached ``test_contract`` payload; None when absent.

    Raises:
        ValueError: present but malformed, unknown schema, or a digest that does not match the content.
    """
    # FILL IN: shape-check dict{schema:int, tests:list[str], markers:list[str], digest:str}; recompute digest
    raise NotImplementedError


def contract_to_header(contract: TestContract) -> dict[str, object]:
    """JSON-ready ``test_contract`` header value (inverse of contract_from_index_header)."""
    return {
        "schema": contract.schema,
        "tests": list(contract.tests),
        "markers": list(contract.markers),
        "digest": contract.digest,
    }


def load_index_header(index_path: Path) -> dict[str, object]:
    """Read a per-spec index JSON and return it without ``tasks``. Raises ValueError on unreadable JSON."""
    # FILL IN: json.loads(read_text) inside try/except (OSError, ValueError) -> raise ValueError(...)
    raise NotImplementedError
```
**Why this shape**: names and signatures are fixed by the spec §3 M2 skeleton (plus `contract_to_header`
and `load_index_header`, which TASK-4443/4450/4451 need so they never re-implement JSON shape).
`real_llm` rejection lives in the parser so no consumer can ever plan one.

### FILL IN checklist
- [ ] `_normalize` — operand/marker validation; bounded by Key Constraints
- [ ] `parse_spec_contract` — subsection grammar; bounded by AC1–AC3
- [ ] `contract_from_index_header` — shape + digest check; bounded by AC4–AC5
- [ ] `load_index_header` — error mapping to ValueError

---

## Acceptance Criteria

- [ ] AC1: the template example subsection (tests + `markers: none`) parses into a `TestContract` with the right tuple order.
- [ ] AC2: `none — fallback` → `None`; missing heading → `ValueError`.
- [ ] AC3: a `real_llm` marker, a directory operand (`packages/ai-parrot/tests`), `..` or a glob → `ValueError`.
- [ ] AC4: `contract_from_index_header({})` → `None`; `{"test_contract": {...schema: 2}}` → `ValueError`.
- [ ] AC5: round trip `contract_from_index_header({"test_contract": contract_to_header(c)}) == c`; a tampered digest → `ValueError`.
- [ ] AC6: `ScopePlan(...)` without `mode`/`cached` still constructs (defaults) — existing tests unchanged.
- [ ] `test_stdlib_only.py` still passes; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_spec_contract.py
import pytest
from parrot.flows.dev_loop.test_scope.contract import (
    contract_from_index_header, contract_to_header, parse_spec_contract,
)

SPEC = """## 4. Test Specification
### Validation Contract

> note
tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- tests/sdd_scripts/test_check_task_graph.py::test_x
markers: none

### Next
"""


def test_parse_spec_contract_roundtrip():
    c = parse_spec_contract(SPEC)
    assert c.tests[1].endswith("::test_x") and c.markers == ()
    assert contract_from_index_header({"test_contract": contract_to_header(c)}) == c


@pytest.mark.parametrize("bad", ["packages/ai-parrot/tests", "../x.py", "tests/*.py"])
def test_bad_operands_fail_closed(bad):
    with pytest.raises(ValueError):
        parse_spec_contract(SPEC.replace("tests/sdd_scripts/test_check_task_graph.py::test_x", bad))

# FILL IN: none-fallback, real_llm marker, absent header, schema 2, tampered digest (AC2–AC5)
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions: work in the FEAT-699 worktree, verify the Codebase
Contract, implement from the blueprint, run the Validation Commands with
`PYTHONPATH=packages/ai-parrot/src`, commit only the listed files, close with
`scripts/sdd/close_task.sh TASK-4440 tests-optimization-sdd-flow verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
