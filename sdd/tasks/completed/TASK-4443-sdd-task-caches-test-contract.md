# TASK-4443: `/sdd-task` caches the spec contract into the index header

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4440
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (decomposition half), §5 AC2. The kernel never parses a spec at runtime; it reads the
cached `test_contract` object from the per-spec index header. Caching must be deterministic (same spec ⇒
same digest), so it is a script, not prose the LLM re-implements on every `/sdd-task` run.

---

## Scope

- Create `scripts/sdd/cache_test_contract.py`:
  `python -m scripts.sdd.cache_test_contract --spec <spec.md> --index <index.json> [--check]`
  - parses the spec subsection with `parse_spec_contract`;
  - contract present → writes `test_contract` (via `contract_to_header`) into the index header, keeping
    key order stable (insert right after `validation_contract` when present, else after `base_branch`);
  - `none — fallback` → removes any `test_contract` key and prints `fallback`;
  - malformed / missing subsection → exit 2 with the parser's message (no write);
  - `--check` → exit 1 when the index's cached value differs from the spec (no write).
- Update `/sdd-task` (`.claude/commands/sdd-task.md` + identical twin `.agent/workflows/sdd-task.md`):
  add a `test_contract` line to the index-schema example and a new §4 step "Cache the Validation Contract"
  that runs the script before §4b, and make each task's `## Validation Commands` list that task's OWN test files.
- One bullet in `.agents/skills/sdd-task/SKILL.md` under its Validation Commands section.
- Tests: `tests/sdd_scripts/test_cache_test_contract.py`.

**NOT in scope**: linting the cached value (TASK-4441), kernel use (TASK-4445+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/cache_test_contract.py` | CREATE | Deterministic spec → index header caching |
| `tests/sdd_scripts/test_cache_test_contract.py` | CREATE | CLI tests |
| `.claude/commands/sdd-task.md` | MODIFY | Schema line + caching step |
| `.agent/workflows/sdd-task.md` | MODIFY | Twin — identical body change |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | One bullet |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# by-path kernel load, exactly like scripts/sdd/select_tests.py:18-27
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
import test_scope.contract as contract  # parse_spec_contract, contract_to_header, contract_from_index_header (TASK-4440)
```

### Existing Signatures to Use
- `.claude/commands/sdd-task.md:301` / `.agent/workflows/sdd-task.md:297` — `  "validation_contract": "required",` (occurrences: 1 each)
- `.claude/commands/sdd-task.md:364` / `.agent/workflows/sdd-task.md:360` — `#### Validation Commands (mandatory, per task — FEAT-563)`
- `.agents/skills/sdd-task/SKILL.md:102` — `#### Validation Commands (mandatory, per task — FEAT-563)`
- `scripts/sdd/test_report.py:21-27` — `_load_report()` by-path loader pattern; `main(argv) -> int` returning 0/1/2

### Does NOT Exist
- ~~`scripts/sdd/cache_test_contract.py`~~ — created here
- ~~any existing writer of `test_contract`~~ — none

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/cache_test_contract.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_cache_test_contract.py", "action": "CREATE"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-task/SKILL.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the script — *why*: deterministic digest; the LLM only invokes it.
2. Edit both sdd-task twins identically — *why*: `test_command_twin_parity.py`.
3. Write CLI tests (write, fallback removal, malformed exit 2, --check drift exit 1, idempotent re-run).

### `scripts/sdd/cache_test_contract.py` (CREATE)
```python
"""``cache_test_contract.py`` — cache a spec's §4 Validation Contract into its per-spec index (FEAT-699).

Usage:
    python -m scripts.sdd.cache_test_contract --spec sdd/specs/<slug>.spec.md --index sdd/tasks/index/<slug>.json [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"


def _load_contract() -> ModuleType:
    """Import ``test_scope.contract`` by path (never ``import parrot``)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope.contract as contract_mod  # noqa: PLC0415 -- path-dependent import

    return contract_mod


def _with_contract(index: dict, value: dict | None) -> dict:
    """Return a new index dict with ``test_contract`` set/removed at a stable position."""
    # FILL IN: rebuild key order — drop existing key; insert after "validation_contract" if present else
    #          after "base_branch"; value None ⇒ key absent — bounded by Scope (stable key order)
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """0 cached/unchanged/fallback, 1 --check drift, 2 usage error or malformed contract."""
    parser = argparse.ArgumentParser(description="Cache a spec's Validation Contract into its index header.")
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    contract_mod = _load_contract()
    # FILL IN: read spec + index (OSError/JSON error → 2); parse (ValueError → print to stderr, 2);
    #          compute new index; --check compares header values → 0/1; else write with indent=2 +
    #          trailing newline, print "cached <digest>" or "fallback"
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
```

### `.claude/commands/sdd-task.md` + `.agent/workflows/sdd-task.md` (MODIFY — identical)
```markdown
<!-- occurrences: 1 per file (verified: grep -c '  "validation_contract": "required",') -->
<!-- AFTER — insert below `  "validation_contract": "required",` in the index schema example -->
  "test_contract": {"schema": 1, "tests": ["<operand>", "..."], "markers": [], "digest": "sha256:<hex>"},
```
```markdown
<!-- BEFORE — insert above `#### Validation Commands (mandatory, per task — FEAT-563)` -->
#### Cache the Validation Contract (FEAT-699, mandatory)

After writing the index and before §4b, run:
```bash
python -m scripts.sdd.cache_test_contract --spec <spec-path> --index sdd/tasks/index/<feature-slug>.json
```
It writes the spec §4 `### Validation Contract` into the header as `test_contract` (or removes it for
`none — fallback`). Never hand-write `test_contract`. Exit 2 means the spec subsection is malformed or
missing — fix the spec, do not skip the step. Each task's `## Validation Commands` lists that task's OWN
test files; the contract is added by the selector at merge/feature tier, never copied into every task.

```

### FILL IN checklist
- [ ] `_with_contract` stable key order
- [ ] `main` I/O + exit codes
- [ ] identical twin edits (check with the parity test)
- [ ] SKILL.md bullet under its Validation Commands heading
- [ ] tests for the 5 behaviours in Steps 3

---

## Acceptance Criteria

- [ ] Running twice on the same spec produces a byte-identical index (idempotent).
- [ ] `none — fallback` removes the key; malformed exits 2 without writing; `--check` detects drift.
- [ ] Twin parity passes for `sdd-task`.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_cache_test_contract.py -q`
- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_cache_test_contract.py
from scripts.sdd import cache_test_contract as cli

def test_cache_is_idempotent(tmp_path):
    """Write spec+index fixtures, run main twice, assert identical bytes and a test_contract key."""
    # FILL IN
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4443 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
