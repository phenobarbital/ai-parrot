# TASK-4519: Tests — contract-probe claim mapping and classification

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4515, TASK-4516
**Assigned-to**: unassigned

---

## Context

Spec Module 6 (M6) for M7. Reference implementations of claim → probe-check
mapping and probe-result → verified/stale/missing classification, tested
against the spec's fixtures, plus assertions that both commands delegate to
`sdd-contract-probe` and never to a fork.

## Scope

- Create `tests/sdd_scripts/test_contract_validation.py` with the M7 tests from spec §4.

**NOT in scope**: testing the probe agent itself (PR #1742 owns that).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_contract_validation.py` | CREATE | M7 tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path
import re
import pytest
```
Repo root idiom: `Path(__file__).resolve().parents[2]`.

### Existing Signatures to Use
- `.claude/commands/sdd-brainstorm.md` Step 4/10 probe text (TASK-4515)
- `.claude/commands/sdd-proposal.md` `#### 4d. Citation probe` (TASK-4516)
- Probe report shape and fixtures: spec §4 `sample_contract_claims`, `sample_probe_report`, `expected_classification` — copy verbatim.

### Does NOT Exist
- ~~an importable classifier~~ — reference functions live in the test file
- ~~probe statuses `verified|stale|missing`~~

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": "tests/sdd_scripts/test_contract_validation.py", "action": "CREATE"}],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)
1. Copy the three spec fixtures.
2. Write `_to_check(claim)` and `_classify(result, expected)` per spec M7 tables.
3. Behavior tests, then command-text contract tests.

### `tests/sdd_scripts/test_contract_validation.py` (CREATE)
```python
"""FEAT-708 M7 — claim → sdd-contract-probe check mapping and caller-side classification."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMANDS = {
    name: _REPO_ROOT / ".claude" / "commands" / f"{name}.md" for name in ("sdd-brainstorm", "sdd-proposal")
}


def _classify(result: dict, expected: str | None) -> str:
    """Map one verified probe result to verified | stale | missing (spec M7 table)."""
    # FILL IN — bounded by spec M7 "Classification" table; whitespace-normalize signatures


def _report_usable(report: dict, head: str) -> bool:
    """A report is usable only when its `head` equals the current short HEAD."""
    return report.get("head") == head
```

### FILL IN checklist
- [ ] `test_claim_extraction_imports|signatures|absent|files` — assert each fixture claim's `check` has the right `kind` and keys (`absent` scope is a directory, not a file)
- [ ] `test_classify_verified`, `test_classify_stale_signature`, `test_classify_absent_present_is_stale`, `test_classify_missing` — full table incl. `module-missing`, `short`, `anchor ambiguous`; and `expected_classification` matches for the sample report
- [ ] `test_probe_report_head_mismatch_rejected`
- [ ] `test_fallback_inline_verification` — both commands' text mention inline fallback (`~10`, Agent unavailable)
- [ ] `test_uses_shared_probe_agent` — both commands contain `sdd-contract-probe`; regex: no `subagent_type: "fork"` within the probe paragraphs and no `model: "haiku"` anywhere in either file

## Acceptance Criteria

- [ ] All spec §4 M7 unit tests present and passing
- [ ] `ruff check tests/sdd_scripts/test_contract_validation.py` clean

## Validation Commands

- `pytest tests/sdd_scripts/test_contract_validation.py -q`

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

**Completed by**: sdd-worker (orchestrator) — coder seat zai.glm-4.7-flash (nova), attempt 1
**Date**: 2026-10-20
**Notes**: created tests/sdd_scripts/test_contract_validation.py; attempt 1 on codex-spark failed (infra: model unsupported with ChatGPT account), attempt 2 on glm succeeded. Orchestrator read the full diff (42589592b); merge-tier validation green. Seat: zai.glm-4.7-flash · Backend: nova · Attempts: 1 · Duration: 78.1s. Closed via close_task.sh (finalize_task unavailable: no review EvidenceRef resolvable from the engine store).

**Deviations from spec**: none
