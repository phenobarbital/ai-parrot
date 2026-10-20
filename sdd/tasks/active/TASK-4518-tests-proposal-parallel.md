# TASK-4518: Tests — parallel research invariants (partition, budget, merge, schema)

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4511, TASK-4514
**Assigned-to**: unassigned

---

## Context

Spec Module 6 (M6), S9. The dispatch/merge logic is agent-executed Markdown,
so the tests do two things: (a) **reference implementations** of the
deterministic rules (partition, allocation, dedup) written in the test module
and checked against the spec's fixtures, and (b) **contract assertions** that
`.claude/commands/sdd-proposal.md` states those exact rules, plus JSON-Schema
validation of `state.schema.json`.

## Scope

- Create `tests/sdd_scripts/test_proposal_parallel.py` with the M1–M4 tests from spec §4.

**NOT in scope**: M7 tests (TASK-4519), twin parity (TASK-4517). No new non-test module.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_proposal_parallel.py` | CREATE | M1–M4 tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from jsonschema import Draft202012Validator  # verified: tests/sdd_scripts/test_intake_templates.py:10
from pathlib import Path
import json, math, re
import pytest
```
Repo root idiom: `Path(__file__).resolve().parents[2]` (verified: test_command_twin_parity.py:21).

### Existing Signatures to Use
- `sdd/templates/state.schema.json` — `research.parallel`, `$defs/lane_record` (TASK-4511). Check `$schema` key to pick the validator class.
- `.claude/commands/sdd-proposal.md` — `#### 4.0 Dispatch` (4513), `#### Per-lane allocation` (4512), `#### 4c. Merge lane findings` (4514).

### Does NOT Exist
- ~~`scripts/sdd/proposal_parallel.py`~~ or any importable helper — reference functions live in the test file
- ~~`merge_findings()`~~ in the codebase

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": "tests/sdd_scripts/test_proposal_parallel.py", "action": "CREATE"}],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)
1. Write reference helpers `_partition`, `_allocate`, `_merge` mirroring the command text.
2. Write behavior tests on them with spec §4 fixtures.
3. Write contract tests that grep the command for the rule text (table rows, prefixes, `.audit`, sequential conditions).
4. Write schema tests.

### `tests/sdd_scripts/test_proposal_parallel.py` (CREATE)
```python
"""FEAT-708 — parallel /sdd-proposal research invariants.

The dispatch and merge are agent-executed Markdown, so this module holds
reference implementations of the deterministic rules and asserts that
`.claude/commands/sdd-proposal.md` states the same rules.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMAND = _REPO_ROOT / ".claude" / "commands" / "sdd-proposal.md"
_SCHEMA = _REPO_ROOT / "sdd" / "templates" / "state.schema.json"

_LANES = {
    "codebase": ("FC", {"grep", "glob", "read", "tree"}),
    "git": ("FG", {"git_log"}),
    "wiki": ("FW", {"wiki_query", "wiki_page", "wiki_related"}),
}


def _partition(queries: list[dict]) -> dict[str, list[str]]:
    """Split plan queries into lanes by type; a child follows its parent's lane."""
    # FILL IN — bounded by spec M1 / S4


def _allocate(profile: dict) -> dict[str, dict[str, int]]:
    """Per-lane quotas: floor fractions from the spec M2 table."""
    # FILL IN — bounded by spec M2 table


def _merge(findings: list[dict]) -> list[dict]:
    """Citation-identity dedup; returns canonical findings with ids F001..."""
    # FILL IN — bounded by spec M3; finding = {"id", "citations": [(path, symbol, (start, end))], "depth", "notes"}


@pytest.fixture
def command_text() -> str:
    return _COMMAND.read_text(encoding="utf-8")


@pytest.fixture
def schema_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))

# fixtures sample_research_plan / sample_budget_profile: copy spec §4 verbatim
# tests: FILL IN (list below)
```
**Why**: no Python product code exists for this feature (spec §2 "No new public Python interfaces"); reference functions make the rules testable without inventing a module.

### FILL IN checklist
- [ ] `test_partition_by_type`, `test_partition_preserves_parent_chains` (Q003 → wiki), `test_partition_cross_lane_followup_recorded` (command text contains `[cross-lane: type=`)
- [ ] `test_budget_allocation_floor_rounding` (default: codebase files 24, greps 20; git files 8, git 10; wiki files 8, greps 5; sums ≤ profile), `test_budget_merge_window_reserved` (300 → lanes 255, window 45), `test_budget_custom_forces_sequential`, `test_budget_tight_forces_sequential` (command text)
- [ ] `test_dedup_same_symbol_merged`, `test_dedup_different_symbols_preserved`, `test_dedup_canonical_renumbering`, `test_dedup_audit_directory` (command text names `findings/.audit/`)
- [ ] `test_state_parallel_optional` (state without and with spec §2 example), `test_state_lane_record_shape` (bad status enum rejected; extra key in `parallel` rejected)
- [ ] Build a minimal valid state.json — read the schema's top-level `required` list first

## Acceptance Criteria

- [ ] All spec §4 M1–M4 unit tests present and passing
- [ ] No helper module outside the test file
- [ ] `ruff check tests/sdd_scripts/test_proposal_parallel.py` clean

## Validation Commands

- `pytest tests/sdd_scripts/test_proposal_parallel.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-proposal-parallel-research --feature-id FEAT-708`)
2. **Read the spec** at `sdd/specs/sdd-proposal-parallel-research.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-proposal-parallel-research.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor check before editing;
   if an anchor moved, fix the blueprint first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `FILL IN`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (`.claude/` paths need `git add -f`)
9. **Close** with `scripts/sdd/close_task.sh <TASK-ID> sdd-proposal-parallel-research verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
